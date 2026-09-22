"""Search Northwind's policy documents (Day 6: Ground).

The policies are short markdown files in policies/. Each "##" section is one chunk.
A question is matched to chunks by the words they share, with the ontology's
synonyms added (refund = money back), and rarer words counting for more.
Only the best few chunks come back, each with its source, so the agent can cite it.

Backend: local by default. Set RAG_BACKEND=vertex and VERTEX_RAG_CORPUS to the
corpus resource name to search a Vertex AI RAG Engine corpus instead.
"""
import math
import os
import re
from pathlib import Path

import yaml

KIT = Path(__file__).resolve().parents[1]
POLICIES = KIT / "policies"
SYNONYMS = yaml.safe_load((KIT / "ontology.yaml").read_text(encoding="utf-8")).get("synonyms", {})
STOP = set("a an the of to for and or in on is are be it its this that what which who how do does can may we our "
           "with by at from as if any every than then there their they them".split())


def _words(text):
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP]


def _chunks():
    out = []
    for path in sorted(POLICIES.glob("*.md")):
        title, section, lines = "", "", []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
            elif line.startswith("## "):
                if lines:
                    out.append((path.name, title, section, " ".join(lines).strip()))
                section, lines = line[3:].strip(), []
            elif line.strip():
                lines.append(line.strip("- ").strip())
        if lines:
            out.append((path.name, title, section, " ".join(lines).strip()))
    return out


CHUNKS = _chunks()


def _expand(words):
    extra = []
    for key, alts in SYNONYMS.items():
        group = [key] + list(alts)
        joined = " ".join(words)
        if any(term in joined for term in group):
            for term in group:
                extra += _words(term)
    return words + extra


def search(question, top_k=3):
    if os.getenv("RAG_BACKEND", "local") == "vertex":
        return _vertex(question, top_k)
    query = set(_expand(_words(question)))
    docs = [_words(f"{title} {section} {text}") for _, title, section, text in CHUNKS]
    n = len(docs)
    scored = []
    for (source, title, section, text), words in zip(CHUNKS, docs):
        score = 0.0
        for w in query:
            df = sum(1 for d in docs if w in d)
            if w in words and df:
                score += math.log(1 + n / df) * (1 + math.log(words.count(w)))
        if score > 0:
            scored.append((score, source, title, section, text))
    scored.sort(reverse=True)
    return {"status": "ok", "backend": "local", "passages": [
        {"source": f"{s}#{sec}", "policy": t, "section": sec, "text": txt, "score": round(sc, 2)}
        for sc, s, t, sec, txt in scored[:top_k]]}


def _vertex_init():
    import vertexai  # only needed for the Vertex option
    vertexai.init(project=os.environ["GOOGLE_CLOUD_PROJECT"],
                  location=os.getenv("VERTEX_RAG_LOCATION", "us-central1"))


def _vertex(question, top_k):
    from vertexai import rag
    _vertex_init()
    response = rag.retrieval_query(
        rag_resources=[rag.RagResource(rag_corpus=os.environ["VERTEX_RAG_CORPUS"])],
        text=question,
        rag_retrieval_config=rag.RagRetrievalConfig(top_k=top_k),
    )
    return {"status": "ok", "backend": "vertex", "passages": [
        {"source": c.source_uri, "text": c.text} for c in response.contexts.contexts]}


def vertex_setup():
    """Create a Vertex AI RAG corpus and upload the six policy files to it. Run once.
    Prints the corpus name to put in VERTEX_RAG_CORPUS."""
    from vertexai import rag
    _vertex_init()
    corpus = rag.create_corpus(display_name="northwind-policies")
    for path in sorted(POLICIES.glob("*.md")):
        rag.upload_file(corpus_name=corpus.name, path=str(path), display_name=path.name)
        print(f"  uploaded {path.name}")
    print(f"\nexport VERTEX_RAG_CORPUS={corpus.name}")
