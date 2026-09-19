"""Retrieval evaluation — dense vs sparse vs hybrid vs hybrid+rerank.

    python ex03_rag_hybrid/evaluate.py

Without this file the rest of the example is an opinion. A golden set of
questions with known-correct chunk IDs is the cheapest useful evaluation in RAG,
and it answers the question everyone actually has: is the hybrid complexity
earning its keep on *my* corpus, or would dense alone have been fine?

Metrics:
  Recall@k — was the correct chunk anywhere in the top k? Retrieval's real job,
             because a chunk that never surfaces cannot be cited.
  MRR      — 1/rank of the first correct chunk. Rewards putting it at the top,
             which matters once you truncate context to save tokens.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Run as a script, import as a package: the repo root goes on sys.path so
# that `python exNN_x/main.py` and `adk web .` resolve imports identically.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ex03_rag_hybrid.config import FINAL_TOP_K, verify_credentials  # noqa: E402
from ex03_rag_hybrid.retriever import (  # noqa: E402
    Retrieved,
    dense_search,
    hybrid_search,
    reciprocal_rank_fusion,
    sparse_search,
    _sparse_index,
)

# Each case: the question, and the chunk IDs that genuinely answer it.
# Written by reading the corpus, not by running the retriever and blessing
# whatever came back — that circularity is how eval sets become useless.
GOLDEN_SET: list[dict] = [
    {
        "question": "How long do I have to return an unopened item?",
        "relevant": ["POL-RET-004#S01.1"],
        "probes": "plain semantic match",
    },
    {
        "question": "Customer opened a face wash and says it smells off. Can they return it?",
        "relevant": ["POL-RET-004#S02.1"],
        "probes": "paraphrase — 'off odour' appears, 'face wash' does not",
    },
    {
        "question": "When is a parcel officially declared lost?",
        "relevant": ["POL-DEL-002#S02.1"],
        "probes": "semantic — question shares few words with the clause",
    },
    {
        "question": "What does POL-GDW-001 say about goodwill ceilings?",
        "relevant": ["POL-GDW-001#S02.1"],
        "probes": "exact document ID — BM25 territory, dense usually misses",
    },
    {
        "question": "What is the goodwill cap after a second failure within 90 days?",
        "relevant": ["POL-GDW-001#S02.1"],
        "probes": "numeric threshold lookup",
    },
    {
        "question": "Can we use quarantined stock for a replacement we already promised?",
        "relevant": ["SOP-QLT-011#S03.1"],
        "probes": "cross-document reasoning; inventory clauses compete",
    },
    {
        "question": "Customer reports hives after using a scrub. What happens next?",
        "relevant": ["POL-GDW-001#S05.1", "POL-GDW-001#S04.1"],
        "probes": "multi-chunk; escalation matrix plus adverse reaction handling",
    },
    {
        "question": "How much safety stock do we hold for A-class SKUs?",
        "relevant": ["SOP-INV-007#S02.1"],
        "probes": "jargon term 'A-class' — lexical anchor",
    },
    {
        "question": "Three delivery attempts failed because nobody was home. Do we pay goodwill?",
        "relevant": ["POL-DEL-002#S06.1", "POL-GDW-001#S03.1"],
        "probes": "the answer is a refusal, spread across two documents",
    },
    {
        "question": "What is the supplier lead time for ceramics?",
        "relevant": ["SOP-INV-007#S07.1"],
        "probes": "specific noun, single clause",
    },
    {
        "question": "How long do Malaysian FPX refunds take to settle?",
        "relevant": ["POL-RET-004#S04.1"],
        "probes": "acronym FPX — dense embeddings blur acronyms",
    },
    {
        "question": "Seasonal gift set was lost in transit and there is no stock. What do we do?",
        "relevant": ["SOP-INV-007#S06.1"],
        "probes": "situational; needs the no-replenishment clause, not the lost-parcel one",
    },
]


def _ids(results: list) -> list[str]:
    return [r.chunk.chunk_id if isinstance(r, Retrieved) else r[0] for r in results]


def recall_at_k(retrieved: list[str], relevant: list[str], k: int) -> float:
    """Fraction of the relevant chunks present in the top k."""
    top = set(retrieved[:k])
    return len([r for r in relevant if r in top]) / len(relevant)


def mrr(retrieved: list[str], relevant: list[str]) -> float:
    for rank, chunk_id in enumerate(retrieved, start=1):
        if chunk_id in relevant:
            return 1.0 / rank
    return 0.0


def hybrid_no_rerank(query: str, k: int) -> list[str]:
    """RRF ordering only, so the reranker's contribution is isolatable."""
    _, chunks = _sparse_index()
    by_id = {c.chunk_id: c for c in chunks}
    fused = reciprocal_rank_fusion(dense_search(query), sparse_search(query))
    ordered = sorted(fused.items(), key=lambda kv: kv[1][0], reverse=True)
    return [cid for cid, _ in ordered if cid in by_id][:k]


def main() -> None:
    verify_credentials()
    k = FINAL_TOP_K

    strategies = {
        "dense only": lambda q: [cid for cid, _ in dense_search(q)][:k],
        "bm25 only": lambda q: [cid for cid, _ in sparse_search(q)][:k],
        "hybrid (RRF)": lambda q: hybrid_no_rerank(q, k),
        "hybrid + rerank": lambda q: _ids(hybrid_search(q, final_k=k, use_rerank=True)),
    }

    totals = {name: {"recall": 0.0, "mrr": 0.0} for name in strategies}

    print(f"Evaluating {len(GOLDEN_SET)} questions at k={k}\n")
    print(f"{'question':<52} {'dense':>7} {'bm25':>7} {'rrf':>7} {'+rank':>7}")
    print("-" * 84)

    for case in GOLDEN_SET:
        row = []
        for name, fn in strategies.items():
            retrieved = fn(case["question"])
            recall = recall_at_k(retrieved, case["relevant"], k)
            totals[name]["recall"] += recall
            totals[name]["mrr"] += mrr(retrieved, case["relevant"])
            row.append(recall)

        label = case["question"][:50]
        print(f"{label:<52} " + " ".join(f"{v:>7.2f}" for v in row))

    n = len(GOLDEN_SET)
    print("-" * 84)
    print(f"{'MEAN RECALL@' + str(k):<52} " + " ".join(
        f"{totals[name]['recall'] / n:>7.2f}" for name in strategies))
    print(f"{'MEAN MRR':<52} " + " ".join(
        f"{totals[name]['mrr'] / n:>7.2f}" for name in strategies))

    print("\nRead it like this:")
    print("  bm25 beating dense on a row  -> the query hinges on an exact term")
    print("  dense beating bm25 on a row  -> the query is a paraphrase")
    print("  rrf at or above both         -> fusion is doing its job")
    print("  +rank lifting MRR not recall -> reranking sharpens order, not coverage")
    print("\nIf hybrid never beats dense on your own corpus, drop the complexity.")
    print("That is a legitimate result and this harness exists to find it.")


if __name__ == "__main__":
    main()
