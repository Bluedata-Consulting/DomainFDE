"""Environment, model and retrieval configuration for the hybrid RAG example."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

# --- Models ---------------------------------------------------------------
FLASH = "gemini-2.5-flash"
PRO = "gemini-2.5-pro"

# Gemini's current general-purpose embedding model. It is task-type aware, which
# is why embeddings.py embeds documents and queries differently.
EMBED_MODEL = "gemini-embedding-001"

# gemini-embedding-001 defaults to 3072 dimensions and supports Matryoshka
# truncation. 768 keeps recall within noise of the full size on corpora this
# shape while cutting index size and query latency by 4x.
EMBED_DIM = 768

# --- Paths ----------------------------------------------------------------
BASE_DIR = Path(__file__).parent
KB_DIR = BASE_DIR / "data" / "kb"
CHROMA_DIR = BASE_DIR / "chroma_store"
BM25_PATH = BASE_DIR / "bm25_index.pkl"
COLLECTION_NAME = "aurora_policy_kb"

# --- Chunking -------------------------------------------------------------
# Chunks are built per heading, then split if a section runs long. Policy
# documents are written in self-contained clauses, so heading boundaries are
# meaningful semantic boundaries -- do not assume this for every corpus.
MAX_CHUNK_CHARS = 1400
CHUNK_OVERLAP_CHARS = 200

# --- Retrieval ------------------------------------------------------------
DENSE_TOP_K = 8      # candidates from the vector store
SPARSE_TOP_K = 8     # candidates from BM25
RRF_K = 60           # RRF damping constant; 60 is the value from the original paper
FUSED_TOP_K = 6      # candidates surviving fusion, sent to the reranker
FINAL_TOP_K = 4      # chunks actually placed in the model's context

APP_NAME = "aurora_policy_rag"
USER_ID = "ops_user_001"


def verify_credentials() -> None:
    """Fail fast with a useful message instead of a 401 deep inside the SDK."""
    use_vertex = os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "FALSE").upper() == "TRUE"
    if use_vertex:
        if not os.environ.get("GOOGLE_CLOUD_PROJECT"):
            raise RuntimeError(
                "GOOGLE_GENAI_USE_VERTEXAI=TRUE but GOOGLE_CLOUD_PROJECT is not set. "
                "Set it in .env and run: gcloud auth application-default login"
            )
        return
    if not os.environ.get("GOOGLE_API_KEY"):
        raise RuntimeError(
            "GOOGLE_API_KEY is not set. Copy .env.example to .env and add your key "
            "from https://aistudio.google.com/apikey"
        )
