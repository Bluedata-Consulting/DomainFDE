# 03 — Hybrid RAG (dense + BM25 + RRF + reranking)

**Knowledge moves out of the prompt and into a corpus. The agent's job becomes
retrieve, then answer only from what came back.**

Use case: Aurora Retail has five policy and SOP documents governing returns, delivery
exceptions, goodwill, product quarantine and inventory allocation. Care agents and
planners need exact answers with citations, and the policies change on their own
release cycle — so putting them in a prompt is a maintenance problem waiting to happen.

## Run it

```bash
python ex03_rag_hybrid/ingest.py            # build both indexes — do this first
python ex03_rag_hybrid/main.py              # sample questions
python ex03_rag_hybrid/main.py --chat       # interactive; /r <query> shows retrieval
python ex03_rag_hybrid/main.py --retrieval-only "goodwill ceiling"
python ex03_rag_hybrid/evaluate.py          # dense vs bm25 vs hybrid vs +rerank
```

## Architecture

```
INGEST (ingest.py)
  5 markdown docs
      ├─ front-matter parsed (doc_id, owner, version, effective_from)
      ├─ split on H2 clause boundaries, long clauses split with 200-char overlap
      ├─ each chunk prefixed "Doc title > Section" before embedding
      └─ 34 chunks
            ├──▶ Chroma      gemini-embedding-001, RETRIEVAL_DOCUMENT, 768-d, cosine
            └──▶ BM25Okapi   identifier-preserving tokenizer
                             ^ both built from ONE chunk list, in one pass

QUERY (retriever.py)
  question
      ├──▶ dense_search   top 8    (RETRIEVAL_QUERY embedding)
      └──▶ sparse_search  top 8    (BM25, zero-score matches dropped)
                │
                ▼
          Reciprocal Rank Fusion   score = Σ 1/(60 + rank)
                │  top 6
                ▼
          Gemini reranker          scores each passage 0-3 against the question
                │  drop score 0, keep top 4
                ▼
          formatted context with [CHUNK-ID] citations
                │
                ▼
ANSWER (agent.py)   LlmAgent + search_policy_kb tool, cites every claim
```

## What to study here

**Task-type embeddings (`embeddings.py`).** `gemini-embedding-001` embeds a question
and a passage differently — `RETRIEVAL_QUERY` versus `RETRIEVAL_DOCUMENT`. Embedding
both sides as documents is a common, silent quality bug: cosine still returns results,
but you are measuring passage-to-passage similarity instead of question-to-answer
relevance. Chroma's protocol exposes `__call__` for documents and `embed_query` for
queries, so the distinction is enforced by the collection rather than remembered by a
developer.

**Why hybrid, concretely.** Run these two against the sample corpus:

| Query | Dense | BM25 |
|---|---|---|
| "customer opened a face wash and it smells off" | finds it — the clause says "off odour", not "face wash" | weak |
| "what does POL-GDW-001 say about goodwill ceilings" | weak — all document IDs embed near each other | rank 1 |

Fusion is not hedging. The two retrievers fail in opposite places, which is exactly
the condition where combining them beats tuning either.

**RRF fuses ranks, not scores.** Cosine similarity and BM25 scores are on different
scales with different distributions. Normalising them into a weighted sum requires
per-corpus tuning that rots as the corpus grows. RRF needs no tuning, and `k=60` damps
the head of each list so a document found by *both* retrievers outranks one found
brilliantly by either — the consensus behaviour you want.

**Chunking carries context.** Every chunk is embedded as `"Goodwill Credit and
Escalation Matrix > Goodwill ceilings\n\n<clause>"`. Without that prefix, a clause
reading "the cap rises to 15 percent" is unretrievable and uncitable. Chunk strategy
moves retrieval quality far more than the choice of vector store does.

**The tokenizer preserves identifiers.** `[a-z0-9]+(?:-[a-z0-9]+)*` keeps
`POL-GDW-001` and `AUR-DIFF-CER-01` as single tokens. A tokenizer that shreds them on
the hyphen throws away the main thing BM25 contributes to the hybrid.

**Rerank after fusion, never instead of it.** Fusion is a recall stage — get the right
chunk into the candidate pool. Reranking is a precision stage — get it to the top. The
reranker sees 6 candidates, not 34, because it costs an LLM call per query. Chunks
scoring 0 are dropped rather than padded into context, which is how you avoid confident
answers built on unrelated clauses.

**Graceful degradation.** If the reranker call fails, `gemini_rerank` logs and returns
the RRF ordering. An optional precision stage must never take down the required
retrieval stage.

**Grounding is enforced in the instruction, not assumed.** Rules 3 to 6 in `agent.py`
tell the model to decline when the corpus is silent, cite chunk IDs after every claim,
surface conflicts instead of picking silently, and copy thresholds exactly rather than
rounding "7 days" to "about a week". The last sample question — cryptocurrency payments
— exists to test the decline path. An assistant that answers it is guessing.

## The evaluation harness

`evaluate.py` is the most reusable file here. Twelve questions with known-correct chunk
IDs, scored four ways:

```
                                 dense    bm25     rrf   +rank
MEAN RECALL@4                     0.xx    0.xx    0.xx    0.xx
MEAN MRR                          0.xx    0.xx    0.xx    0.xx
```

Read it per row: BM25 winning means the query hinged on an exact term; dense winning
means it was a paraphrase; RRF at or above both means fusion is working; `+rank`
lifting MRR without lifting recall means the reranker is sharpening order, not
coverage — which is exactly its job.

**If hybrid never beats dense on your corpus, delete the BM25 index.** That is a
legitimate result, and this harness exists to find it before you ship the complexity.

## When this pattern is the right answer

- The knowledge is larger than a prompt, or changes faster than you want to redeploy.
- Answers must be traceable to a source clause.
- You need to update knowledge without touching the agent.

## When to move to pattern 4

When the agent needs to *do* things, not just know things — look up a live order,
check current stock, create a request. Retrieval reads a corpus; tools touch systems.

## Production notes

- **Chroma is the right choice for this example and the wrong one at scale.** It is a
  local file store: perfect for a reference implementation, single-node, no HA. In
  production on GCP, move to Vertex AI Vector Search or AlloyDB with `pgvector` and keep
  the retriever interface identical — `hybrid_search` is the seam.
- **Re-embed on model change.** Vectors from different embedding models are not
  comparable. Changing `EMBED_MODEL` means a full rebuild, not an incremental upsert.
- **Chunk IDs are your citation contract.** `POL-GDW-001#S02.1` is stable as long as
  section order is stable. If your source documents get reordered often, hash the
  clause text into the ID instead.
- **Watch for stale answers.** Documents carry `effective_from` and `version` in
  metadata and the agent is told to surface conflicts by date. In a live deployment,
  filter on effective date at query time rather than trusting the model to notice.
- **`hnsw:space: cosine` is set explicitly** — Chroma defaults to L2, which is a quiet
  quality regression on normalised text embeddings.
