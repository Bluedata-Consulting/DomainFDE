"""Hybrid retrieval: dense + sparse, fused with RRF, reranked by Gemini.

The pipeline, and why each stage exists:

    query
      ├─▶ dense search (Chroma, gemini-embedding-001)   semantic match
      └─▶ sparse search (BM25)                          exact lexical match
              │
              ▼
        Reciprocal Rank Fusion                          merge two rankings
              │
              ▼
        Gemini cross-encoder rerank                     precision at the top
              │
              ▼
        top-k chunks + citations                        into the model's context

Dense retrieval finds "what happens if a parcel never turns up" against a clause
titled "Lost in transit" that shares not one content word with the question.
It is also the thing that fails on "POL-GDW-001" or "AUR-DIFF-CER-01", because
an embedding of an identifier is close to every other identifier.

BM25 is the exact opposite on both counts. Running them together and fusing is
not a hedge — the two are strong in complementary places, which is precisely the
condition under which fusion beats either input.
"""

from __future__ import annotations

import json
import pickle
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import chromadb

from .chunking import Chunk, tokenize
from .config import (
    BM25_PATH,
    CHROMA_DIR,
    COLLECTION_NAME,
    DENSE_TOP_K,
    FINAL_TOP_K,
    FLASH,
    FUSED_TOP_K,
    RRF_K,
    SPARSE_TOP_K,
)
from .embeddings import GeminiEmbeddingFunction, _client


@dataclass
class Retrieved:
    """A chunk plus the scores that got it here — keep provenance for debugging."""

    chunk: Chunk
    dense_rank: int | None = None
    sparse_rank: int | None = None
    rrf_score: float = 0.0
    rerank_score: float | None = None

    @property
    def final_score(self) -> float:
        return self.rerank_score if self.rerank_score is not None else self.rrf_score

    def provenance(self) -> str:
        bits = []
        if self.dense_rank is not None:
            bits.append(f"dense#{self.dense_rank}")
        if self.sparse_rank is not None:
            bits.append(f"bm25#{self.sparse_rank}")
        return "+".join(bits) or "none"


# ---------------------------------------------------------------------------
# Index handles. Loaded once per process — embedding clients and unpickling are
# both too expensive to repeat on every tool call.
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _dense_collection():
    if not CHROMA_DIR.exists():
        raise RuntimeError(
            f"No Chroma store at {CHROMA_DIR}. Run: python ex03_rag_hybrid/ingest.py"
        )
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    return client.get_collection(
        name=COLLECTION_NAME, embedding_function=GeminiEmbeddingFunction()
    )


@lru_cache(maxsize=1)
def _sparse_index() -> tuple[Any, list[Chunk]]:
    if not BM25_PATH.exists():
        raise RuntimeError(
            f"No BM25 index at {BM25_PATH}. Run: python ex03_rag_hybrid/ingest.py"
        )
    payload = pickle.loads(BM25_PATH.read_bytes())
    return payload["bm25"], payload["chunks"]


# ---------------------------------------------------------------------------
# The two retrievers
# ---------------------------------------------------------------------------


def dense_search(query: str, top_k: int = DENSE_TOP_K) -> list[tuple[str, int]]:
    """Vector search. Returns (chunk_id, rank) pairs, rank starting at 1."""
    collection = _dense_collection()
    result = collection.query(query_texts=[query], n_results=top_k)
    ids = result["ids"][0] if result["ids"] else []
    return [(chunk_id, rank) for rank, chunk_id in enumerate(ids, start=1)]


def sparse_search(query: str, top_k: int = SPARSE_TOP_K) -> list[tuple[str, int]]:
    """BM25 search over the same chunks. Returns (chunk_id, rank) pairs."""
    bm25, chunks = _sparse_index()
    scores = bm25.get_scores(tokenize(query))

    ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    # A BM25 score of zero means no query term appeared at all. Those are not
    # weak matches, they are non-matches, and letting them into fusion just
    # adds noise at the tail.
    ranked = [i for i in ranked if scores[i] > 0][:top_k]
    return [(chunks[i].chunk_id, rank) for rank, i in enumerate(ranked, start=1)]


# ---------------------------------------------------------------------------
# Fusion
# ---------------------------------------------------------------------------


def reciprocal_rank_fusion(
    dense: list[tuple[str, int]],
    sparse: list[tuple[str, int]],
    k: int = RRF_K,
) -> dict[str, tuple[float, int | None, int | None]]:
    """Fuse two ranked lists into one.

        score(d) = sum over retrievers of  1 / (k + rank(d))

    RRF fuses *ranks*, not scores, which is the point. Cosine similarity and
    BM25 scores live on different scales with different distributions, and any
    attempt to normalise them into a weighted sum needs per-corpus tuning that
    silently rots. RRF needs no tuning and is hard to beat.

    k=60 damps the top of each list so that rank 1 does not dominate rank 2.
    A document found by both retrievers outranks one found brilliantly by
    either — which is exactly the consensus behaviour you want.
    """
    fused: dict[str, tuple[float, int | None, int | None]] = {}

    for chunk_id, rank in dense:
        score, _, sparse_rank = fused.get(chunk_id, (0.0, None, None))
        fused[chunk_id] = (score + 1.0 / (k + rank), rank, sparse_rank)

    for chunk_id, rank in sparse:
        score, dense_rank, _ = fused.get(chunk_id, (0.0, None, None))
        fused[chunk_id] = (score + 1.0 / (k + rank), dense_rank, rank)

    return fused


# ---------------------------------------------------------------------------
# Reranking
# ---------------------------------------------------------------------------

RERANK_PROMPT = """\
You are a retrieval reranker for Aurora Retail's policy knowledge base. Score how \
well each passage answers the question.

Scoring scale:
  3 = directly and completely answers the question
  2 = contains part of the answer, or necessary supporting detail
  1 = same topic area but does not answer the question
  0 = irrelevant

Judge only whether the passage answers THIS question. A passage that is well \
written, authoritative, or about a related policy still scores 0 if it does not \
address the question asked.

Question: {question}

Passages:
{passages}

Return a JSON array only, no prose, no markdown fence. One object per passage, \
each with keys "id" (the passage id exactly as given) and "score" (integer 0-3).
"""


def gemini_rerank(query: str, candidates: list[Retrieved]) -> list[Retrieved]:
    """Score candidates against the query with Gemini, then sort by score.

    This is a cross-encoder in spirit: the query and the passage are read
    together, so the model can judge relevance rather than compare two vectors
    that were computed independently.

    It is the expensive stage — one LLM call per query — which is why it sits
    after fusion and sees only FUSED_TOP_K candidates rather than the corpus.
    Fusion is for recall, reranking is for precision, and the order matters.
    """
    if not candidates:
        return candidates

    passages = "\n\n".join(
        f"[{c.chunk.chunk_id}]\n{c.chunk.text}" for c in candidates
    )
    prompt = RERANK_PROMPT.format(question=query, passages=passages)

    try:
        response = _client().models.generate_content(
            model=FLASH,
            contents=prompt,
            config={
                "temperature": 0.0,
                "max_output_tokens": 1024,
                "response_mime_type": "application/json",
            },
        )
        scores = {item["id"]: float(item["score"]) for item in json.loads(response.text)}
    except Exception as exc:  # noqa: BLE001
        # Never let the optional stage take down the required one. A degraded
        # answer from RRF ordering beats no answer at all.
        print(f"  [rerank unavailable, falling back to RRF order: {exc}]")
        return candidates

    for candidate in candidates:
        candidate.rerank_score = scores.get(candidate.chunk.chunk_id, 0.0)

    # Ties on the reranker's coarse 0-3 scale are broken by RRF score, which
    # keeps the fusion signal rather than discarding it.
    return sorted(
        candidates, key=lambda c: (c.rerank_score or 0.0, c.rrf_score), reverse=True
    )


# ---------------------------------------------------------------------------
# The public entry point
# ---------------------------------------------------------------------------


def hybrid_search(
    query: str,
    final_k: int = FINAL_TOP_K,
    use_rerank: bool = True,
) -> list[Retrieved]:
    """Run the full retrieval pipeline and return the top chunks."""
    _, chunks = _sparse_index()
    by_id = {c.chunk_id: c for c in chunks}

    dense = dense_search(query)
    sparse = sparse_search(query)
    fused = reciprocal_rank_fusion(dense, sparse)

    candidates = [
        Retrieved(
            chunk=by_id[chunk_id],
            rrf_score=score,
            dense_rank=dense_rank,
            sparse_rank=sparse_rank,
        )
        for chunk_id, (score, dense_rank, sparse_rank) in fused.items()
        if chunk_id in by_id
    ]
    candidates.sort(key=lambda c: c.rrf_score, reverse=True)
    candidates = candidates[:FUSED_TOP_K]

    if use_rerank:
        candidates = gemini_rerank(query, candidates)
        # A reranker score of 0 means "irrelevant". Passing it to the answering
        # model anyway is how you get confident answers from unrelated clauses.
        candidates = [c for c in candidates if (c.rerank_score or 0) > 0]

    return candidates[:final_k]


def format_context(results: list[Retrieved]) -> str:
    """Render retrieved chunks for the model, with citable identifiers."""
    if not results:
        return "NO_RELEVANT_POLICY_FOUND"

    blocks = []
    for result in results:
        chunk = result.chunk
        blocks.append(
            f"[{chunk.chunk_id}] {chunk.doc_title} > {chunk.section}\n"
            f"(source: {chunk.source_file}, version {chunk.metadata.get('version', 'n/a')})\n"
            f"{chunk.body}"
        )
    return "\n\n---\n\n".join(blocks)
