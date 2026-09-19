"""Gemini embeddings wired into Chroma.

The important detail is task types. `gemini-embedding-001` is trained to place a
question and the passage that answers it near each other only when you tell it
which is which:

    RETRIEVAL_DOCUMENT  -> for corpus text at ingest time
    RETRIEVAL_QUERY     -> for the user's question at search time

Embedding both sides as RETRIEVAL_DOCUMENT is a common and quiet mistake. It
still "works" — cosine similarity still returns something — but it measures
passage-to-passage similarity rather than question-to-answer relevance, and
recall drops in a way that is hard to notice without an eval set.

Chroma's EmbeddingFunction protocol supports exactly this split via `__call__`
(documents) and `embed_query` (queries), so the distinction survives into the
collection rather than living in application code.
"""

from __future__ import annotations

import os
from typing import Any

from chromadb import Documents, EmbeddingFunction, Embeddings
from google import genai
from google.genai import types

from .config import EMBED_DIM, EMBED_MODEL

# The API caps how many texts one embed_content call may carry. Batching also
# bounds the blast radius of a transient failure during a long ingest.
BATCH_SIZE = 50


def _client() -> genai.Client:
    """Build a genai client honouring the AI Studio / Vertex switch in .env."""
    if os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "FALSE").upper() == "TRUE":
        return genai.Client(
            vertexai=True,
            project=os.environ["GOOGLE_CLOUD_PROJECT"],
            location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
        )
    return genai.Client(api_key=os.environ["GOOGLE_API_KEY"])


class GeminiEmbeddingFunction(EmbeddingFunction[Documents]):
    """Chroma-compatible embedding function backed by Gemini."""

    def __init__(self, model: str = EMBED_MODEL, dimensions: int = EMBED_DIM) -> None:
        self._model = model
        self._dimensions = dimensions
        self._client = _client()

    # Chroma requires these three for config round-tripping when a collection
    # is reopened from disk.
    @staticmethod
    def name() -> str:
        return "gemini_embedding"

    def get_config(self) -> dict[str, Any]:
        return {"model": self._model, "dimensions": self._dimensions}

    @staticmethod
    def build_from_config(config: dict[str, Any]) -> "GeminiEmbeddingFunction":
        return GeminiEmbeddingFunction(
            model=config.get("model", EMBED_MODEL),
            dimensions=config.get("dimensions", EMBED_DIM),
        )

    def _embed(self, texts: list[str], task_type: str) -> Embeddings:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), BATCH_SIZE):
            batch = texts[start : start + BATCH_SIZE]
            response = self._client.models.embed_content(
                model=self._model,
                contents=batch,
                config=types.EmbedContentConfig(
                    task_type=task_type,
                    output_dimensionality=self._dimensions,
                ),
            )
            vectors.extend(list(e.values) for e in response.embeddings)
        return vectors

    def __call__(self, input: Documents) -> Embeddings:
        """Embed corpus documents. Called by Chroma at add() time."""
        return self._embed(list(input), "RETRIEVAL_DOCUMENT")

    def embed_query(self, input: Documents) -> Embeddings:
        """Embed search queries. Called by Chroma at query() time."""
        return self._embed(list(input), "RETRIEVAL_QUERY")
