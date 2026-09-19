"""Build both indexes. Run this once before main.py.

    python ex03_rag_hybrid/ingest.py
    python ex03_rag_hybrid/ingest.py --rebuild     # drop and recreate

Two indexes over the same chunks, in the same order:

  1. Chroma — dense vectors from gemini-embedding-001, for semantic matching.
  2. BM25   — a sparse lexical index, for exact terms the embedder blurs.

They are built together, from one chunk list, so that the two retrievers can
never drift out of sync. A hybrid retriever whose sparse index is one ingest
behind its dense index returns citations that point at the wrong clause, which
is worse than either retriever alone.
"""

from __future__ import annotations

import argparse
import pickle
import shutil
import sys
from pathlib import Path

# Run as a script, import as a package: the repo root goes on sys.path so
# that `python exNN_x/main.py` and `adk web .` resolve imports identically.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import chromadb  # noqa: E402
from rank_bm25 import BM25Okapi  # noqa: E402

from ex03_rag_hybrid.chunking import Chunk, load_and_chunk, tokenize  # noqa: E402
from ex03_rag_hybrid.config import (  # noqa: E402
    BM25_PATH,
    CHROMA_DIR,
    COLLECTION_NAME,
    KB_DIR,
    verify_credentials,
)
from ex03_rag_hybrid.embeddings import GeminiEmbeddingFunction  # noqa: E402


def build_dense_index(chunks: list[Chunk], rebuild: bool) -> None:
    """Embed every chunk and persist it to a local Chroma collection."""
    if rebuild and CHROMA_DIR.exists():
        shutil.rmtree(CHROMA_DIR)

    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=GeminiEmbeddingFunction(),
        # Cosine is the right space for normalised text embeddings. Chroma's
        # default is L2, which is a silent quality bug on this workload.
        metadata={"hnsw:space": "cosine"},
    )

    print(f"  embedding {len(chunks)} chunks with gemini-embedding-001 ...")
    collection.upsert(
        ids=[c.chunk_id for c in chunks],
        documents=[c.text for c in chunks],
        metadatas=[c.to_chroma_metadata() for c in chunks],
    )
    print(f"  chroma collection '{COLLECTION_NAME}' now holds {collection.count()} chunks")


def build_sparse_index(chunks: list[Chunk]) -> None:
    """Build and persist the BM25 index over the identical chunk list."""
    corpus_tokens = [tokenize(c.text) for c in chunks]
    bm25 = BM25Okapi(corpus_tokens)

    payload = {
        "bm25": bm25,
        # Storing the chunks alongside the index keeps ordering authoritative:
        # BM25 returns positions, and position i must mean chunk i forever.
        "chunks": chunks,
    }
    BM25_PATH.write_bytes(pickle.dumps(payload))
    print(f"  bm25 index written to {BM25_PATH.name} over {len(chunks)} chunks")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the Aurora policy KB indexes")
    parser.add_argument("--rebuild", action="store_true", help="Drop and recreate")
    args = parser.parse_args()

    verify_credentials()

    print(f"Loading knowledge base from {KB_DIR} ...")
    chunks = load_and_chunk(KB_DIR)
    if not chunks:
        raise SystemExit(f"No Markdown documents found in {KB_DIR}")

    docs = {c.doc_id for c in chunks}
    avg = sum(len(c.text) for c in chunks) / len(chunks)
    print(f"  {len(docs)} documents -> {len(chunks)} chunks (avg {avg:.0f} chars)")

    build_dense_index(chunks, rebuild=args.rebuild)
    build_sparse_index(chunks)

    print("\nSample chunks:")
    for chunk in chunks[:3]:
        preview = chunk.body[:90].replace("\n", " ")
        print(f"  {chunk.chunk_id:<22} {chunk.section[:34]:<36} {preview}...")

    print("\nDone. Now run:  python ex03_rag_hybrid/main.py")


if __name__ == "__main__":
    main()
