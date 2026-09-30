"""Retrieval over Meridian's policy, quality, procurement and incident documents.

The database says what happened. These documents say what the rules are, what
should have happened, and what happened last time. Two tools:

    search_policy_documents   find passages by meaning or by exact reference
    get_document_section      fetch one section by id, to follow a cross-reference

Retrieval is hybrid on purpose. Pure semantic search misses exact section
references like "7.3" and document codes like "MR-QA-STD-002", and people type
both; pure keyword search misses a question phrased in plain language. Every
passage carries doc_id, version, section and page, because a retrieval layer
that cannot cite is not auditable.

The index is built by v5Agent/build_index.py. Run that first.
"""

from __future__ import annotations

import json
import math
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

INDEX_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "data"
    / "EnterpriseKnoweledge"
    / "index.json"
)

# Words too common in these documents to discriminate between passages.
_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
    "is", "are", "was", "were", "be", "been", "it", "this", "that", "we",
    "our", "us", "i", "can", "do", "does", "did", "what", "which", "who",
    "why", "how", "when", "should", "would", "could", "may", "might",
    "policy", "document", "section", "meridian",
}


class KnowledgeIndexMissing(RuntimeError):
    """Raised when the index has not been built yet."""


@lru_cache(maxsize=1)
def _index() -> dict[str, Any]:
    """Load and cache index.json."""
    if not INDEX_PATH.exists():
        raise KnowledgeIndexMissing(
            f"No document index at {INDEX_PATH}. Run:\n"
            f"    python v5Agent/build_index.py"
        )
    with INDEX_PATH.open() as handle:
        return json.load(handle)


def _chunks() -> list[dict]:
    return _index()["chunks"]


# --------------------------------------------------------------------------
# scoring
# --------------------------------------------------------------------------


def _terms(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9][a-z0-9.\-]*", text.lower())} - _STOPWORDS


def _references(query: str) -> tuple[set[str], set[str]]:
    """Exact handles a person might type: section numbers and document codes.

    These are matched literally rather than semantically -- "7.3" and "7.4" are
    near-identical to an embedding model and completely different to a reader.
    """
    sections = set(re.findall(r"(?:§|section\s+)\s*(\d+(?:\.\d+)*)", query, re.I))
    sections |= set(re.findall(r"\b(\d+\.\d+(?:\.\d+)*)\b", query))
    codes = {c.upper() for c in re.findall(r"\bMR-[A-Z]{2,4}-[A-Z0-9-]{2,}\b", query, re.I)}
    return sections, codes


def _keyword_score(chunk: dict, query_terms: set[str]) -> float:
    """Overlap between the query and the chunk text plus its section title."""
    if not query_terms:
        return 0.0
    haystack = _terms(f"{chunk['section_title']} {chunk['text']}")
    if not haystack:
        return 0.0
    hits = query_terms & haystack
    # Weight title hits: a section titled "Force majeure" beats a passage that
    # merely mentions the phrase.
    title_hits = query_terms & _terms(chunk["section_title"])
    return (len(hits) + 2.0 * len(title_hits)) / len(query_terms)


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _embed_query(query: str) -> list[float]:
    """Embed the query with the same model the index was built with.

    Returns an empty vector if embedding is unavailable, in which case the
    search degrades to keyword-only rather than failing: a slightly worse
    passage is better than no answer at all.
    """
    model = _index().get("embed_model")
    if not model:
        return []
    try:
        import os

        from google import genai

        if os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").upper() in ("1", "TRUE"):
            client = genai.Client(
                vertexai=True,
                project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
                location=os.environ.get("GOOGLE_CLOUD_LOCATION") or "us-central1",
            )
        else:
            client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
        response = client.models.embed_content(model=model, contents=[query])
        return list(response.embeddings[0].values)
    except Exception:
        return []


# --------------------------------------------------------------------------
# tools
# --------------------------------------------------------------------------


def search_policy_documents(
    query: str,
    doc_id: Optional[str] = None,
    include_superseded: bool = False,
    top_k: int = 5,
) -> list[dict]:
    """Search Meridian's policy, quality, procurement and incident documents.

    Use this for questions about RULES, SPECIFICATIONS, CONTRACT TERMS,
    AUTHORITY, APPROVAL, or PAST INCIDENTS. The database holds what happened;
    these documents hold what the rules are and what happened before.

    Args:
        query: what you want to know, in plain language
        doc_id: optional filter, e.g. "MR-CC-POL-004"
        include_superseded: default False. Set True ONLY when explicitly
            asked what a rule used to be. Superseded content must never be
            used to decide a current case.
        top_k: number of passages to return

    Returns:
        One dict per passage with: text, doc_id, doc_title, doc_version,
        section, section_title, page, effective_date, superseded, score.
    """
    try:
        chunks = _chunks()
    except KnowledgeIndexMissing as exc:
        return [{"error": str(exc)}]

    pool = [c for c in chunks if include_superseded or not c["superseded"]]
    if doc_id:
        wanted = doc_id.strip().upper()
        pool = [c for c in pool if c["doc_id"].upper() == wanted]
        if not pool:
            known = sorted({c["doc_id"] for c in chunks})
            return [{"error": f"No document '{doc_id}'. Known: {', '.join(known)}"}]

    query_terms = _terms(query)
    sections, codes = _references(query)
    query_vector = _embed_query(query)

    scored: list[tuple[float, dict]] = []
    for chunk in pool:
        keyword = _keyword_score(chunk, query_terms)
        semantic = _cosine(query_vector, chunk.get("embedding") or [])
        # Exact handles dominate: someone typing "§7.3" wants 7.3, not the
        # passage that reads most like it.
        exact = 0.0
        if sections and chunk["section"] in sections:
            exact += 1.0
        if codes and chunk["doc_id"].upper() in codes:
            exact += 0.5
        score = (0.35 * keyword) + (0.65 * semantic) + exact
        if score > 0:
            scored.append((score, chunk))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [_passage(chunk, score) for score, chunk in scored[: max(1, top_k)]]


def get_document_section(doc_id: str, section: str) -> dict:
    """Fetch one exact section by document id and section number.

    Use when a passage cross-references another section, e.g. a remedy
    clause pointing at MR-QA-STD-002 §5.4. Follow the reference rather than
    guessing what it says.

    Args:
        doc_id: The document code, e.g. "MR-QA-STD-002".
        section: The section number, e.g. "5.4" or "Appendix B".

    Returns:
        {doc_id, doc_title, doc_version, section, section_title, page,
        effective_date, superseded, text}, or {error} when no such section
        exists, listing the sections that do.
    """
    try:
        chunks = _chunks()
    except KnowledgeIndexMissing as exc:
        return {"error": str(exc)}

    wanted_doc = doc_id.strip().upper()
    wanted_section = section.strip().lstrip("§").rstrip(".")

    in_doc = [c for c in chunks if c["doc_id"].upper() == wanted_doc]
    if not in_doc:
        known = sorted({c["doc_id"] for c in chunks})
        return {"error": f"No document '{doc_id}'. Known: {', '.join(known)}"}

    exact = [c for c in in_doc if c["section"].rstrip(".") == wanted_section]
    if not exact:
        # A request for 7 should still find 7.1/7.2/7.3 rather than nothing.
        exact = [c for c in in_doc if c["section"].startswith(wanted_section + ".")]
    if not exact:
        available = sorted({c["section"] for c in in_doc if c["section"]})
        return {
            "error": f"No section '{section}' in {wanted_doc}.",
            "available_sections": available,
        }

    head = exact[0]
    merged = "\n\n".join(c["text"] for c in exact)
    return {
        "doc_id": head["doc_id"],
        "doc_title": head["doc_title"],
        "doc_version": head["doc_version"],
        "section": head["section"],
        "section_title": head["section_title"],
        "page": head["page"],
        "effective_date": head["effective_date"],
        "superseded": any(c["superseded"] for c in exact),
        "parts": len(exact),
        "text": merged,
    }


def _passage(chunk: dict, score: float) -> dict:
    """One search hit, carrying everything needed to cite it."""
    return {
        "text": chunk["text"],
        "doc_id": chunk["doc_id"],
        "doc_title": chunk["doc_title"],
        "doc_version": chunk["doc_version"],
        "section": chunk["section"],
        "section_title": chunk["section_title"],
        "page": chunk["page"],
        "effective_date": chunk["effective_date"],
        "superseded": chunk["superseded"],
        "score": round(score, 4),
        "cite": _cite(chunk),
    }


def _cite(chunk: dict) -> str:
    """The citation string the agent is required to reproduce."""
    version = f" v{chunk['doc_version']}" if chunk["doc_version"] else ""
    section = f" §{chunk['section']}" if chunk["section"] else ""
    return f"{chunk['doc_id']}{version}{section}, p.{chunk['page']}"


KNOWLEDGE_TOOLS = [search_policy_documents, get_document_section]
