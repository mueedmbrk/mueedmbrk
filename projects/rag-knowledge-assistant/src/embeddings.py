"""Embedding providers.

Behind a protocol so the store, retriever and assistant never depend on which
provider is in use — and so the test suite can run deterministically offline.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Protocol, Sequence

import numpy as np
import requests

logger = logging.getLogger(__name__)


class EmbeddingError(RuntimeError):
    """Raised when embeddings cannot be produced."""


class EmbeddingProvider(Protocol):
    dimensions: int

    def embed(self, texts: Sequence[str], input_type: str = "document") -> np.ndarray: ...


class VoyageEmbeddings:
    """Voyage AI embeddings — the recommended pairing for Claude-based RAG."""

    API_URL = "https://api.voyageai.com/v1/embeddings"
    # Voyage caps a single request; larger corpora are sent in batches.
    BATCH_SIZE = 128

    def __init__(
        self,
        api_key: str,
        model: str = "voyage-3",
        dimensions: int = 1024,
        timeout: float = 60.0,
    ) -> None:
        if not api_key:
            raise ValueError("VOYAGE_API_KEY is not set")
        self.api_key = api_key
        self.model = model
        self.dimensions = dimensions
        self.timeout = timeout

    def embed(self, texts: Sequence[str], input_type: str = "document") -> np.ndarray:
        """Embed a batch of texts.

        ``input_type`` matters: Voyage embeds queries and documents into the same
        space but with different optimisations, and using "document" for a user's
        question measurably degrades retrieval.
        """
        if not texts:
            return np.zeros((0, self.dimensions), dtype=np.float32)

        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.BATCH_SIZE):
            batch = list(texts[start : start + self.BATCH_SIZE])
            try:
                response = requests.post(
                    self.API_URL,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={"input": batch, "model": self.model, "input_type": input_type},
                    timeout=self.timeout,
                )
                response.raise_for_status()
                payload = response.json()
            except requests.RequestException as exc:
                raise EmbeddingError(f"embedding request failed: {exc}") from exc

            # Sort by index — the API does not guarantee response ordering.
            items = sorted(payload["data"], key=lambda item: item["index"])
            vectors.extend(item["embedding"] for item in items)

        return np.asarray(vectors, dtype=np.float32)


class HashingEmbeddings:
    """A deterministic, dependency-free embedder for tests and local development.

    This is a hashed bag-of-words projection, not a semantic model: it matches on
    shared vocabulary rather than meaning. That is enough to exercise the retrieval,
    threshold and citation machinery end to end without a network call or an API key.
    Never use it in production — it cannot match a paraphrase.
    """

    def __init__(self, dimensions: int = 256) -> None:
        self.dimensions = dimensions

    def _embed_one(self, text: str) -> np.ndarray:
        vector = np.zeros(self.dimensions, dtype=np.float32)
        tokens = [t for t in text.lower().split() if t.strip()]

        for token in tokens:
            cleaned = "".join(ch for ch in token if ch.isalnum())
            if not cleaned:
                continue
            digest = hashlib.md5(cleaned.encode()).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            vector[index] += 1.0

        norm = np.linalg.norm(vector)
        return vector / norm if norm > 0 else vector

    def embed(self, texts: Sequence[str], input_type: str = "document") -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dimensions), dtype=np.float32)
        return np.vstack([self._embed_one(text) for text in texts])


def cosine_similarity(query: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """Cosine similarity of one vector against many, safe against zero vectors."""
    if matrix.size == 0:
        return np.zeros(0, dtype=np.float32)

    query_norm = np.linalg.norm(query)
    matrix_norms = np.linalg.norm(matrix, axis=1)
    denominator = query_norm * matrix_norms
    # A zero-norm row would divide by zero; report no similarity instead.
    denominator = np.where(denominator == 0, 1e-9, denominator)

    return (matrix @ query) / denominator
