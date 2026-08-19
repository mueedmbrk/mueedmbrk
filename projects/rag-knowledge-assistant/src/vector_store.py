"""Vector storage: an in-memory store for development, Supabase pgvector for production."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol, Sequence

import numpy as np

from .chunking import Chunk
from .embeddings import EmbeddingProvider, cosine_similarity

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """A retrieved chunk and how well it matched."""

    chunk: Chunk
    score: float

    def as_dict(self) -> dict:
        return {**self.chunk.as_dict(), "score": round(self.score, 4)}


class VectorStore(Protocol):
    def upsert(self, chunks: Sequence[Chunk]) -> int: ...
    def search(self, query: str, top_k: int, min_score: float) -> list[SearchResult]: ...
    def delete_document(self, document_id: str) -> int: ...
    def count(self) -> int: ...


class InMemoryVectorStore:
    """Keeps vectors in a NumPy matrix. Ideal for tests and small corpora."""

    def __init__(self, embedder: EmbeddingProvider) -> None:
        self.embedder = embedder
        self._chunks: dict[str, Chunk] = {}
        self._vectors: dict[str, np.ndarray] = {}

    def upsert(self, chunks: Sequence[Chunk]) -> int:
        """Insert or replace chunks. Idempotent, because chunk IDs are deterministic."""
        if not chunks:
            return 0

        vectors = self.embedder.embed([c.text for c in chunks], input_type="document")
        for chunk, vector in zip(chunks, vectors):
            self._chunks[chunk.chunk_id] = chunk
            self._vectors[chunk.chunk_id] = vector

        return len(chunks)

    def search(self, query: str, top_k: int = 5, min_score: float = 0.0) -> list[SearchResult]:
        if not self._chunks or not query.strip():
            return []

        # "query" input type, not "document" — the distinction affects retrieval quality.
        query_vector = self.embedder.embed([query], input_type="query")[0]

        ids = list(self._chunks)
        matrix = np.vstack([self._vectors[i] for i in ids])
        scores = cosine_similarity(query_vector, matrix)

        ranked = np.argsort(scores)[::-1][:top_k]
        return [
            SearchResult(chunk=self._chunks[ids[i]], score=float(scores[i]))
            for i in ranked
            if scores[i] >= min_score
        ]

    def delete_document(self, document_id: str) -> int:
        stale = [cid for cid, chunk in self._chunks.items() if chunk.document_id == document_id]
        for chunk_id in stale:
            self._chunks.pop(chunk_id, None)
            self._vectors.pop(chunk_id, None)
        return len(stale)

    def count(self) -> int:
        return len(self._chunks)


class SupabaseVectorStore:
    """Supabase with the pgvector extension. See ``sql/schema.sql`` for the setup."""

    def __init__(
        self,
        url: str,
        key: str,
        embedder: EmbeddingProvider,
        table: str = "document_chunks",
        match_function: str = "match_document_chunks",
    ) -> None:
        if not url or not key:
            raise ValueError("SUPABASE_URL and SUPABASE_KEY are required")

        from supabase import create_client

        self.table = table
        self.match_function = match_function
        self.embedder = embedder
        self._client = create_client(url, key)

    def upsert(self, chunks: Sequence[Chunk]) -> int:
        if not chunks:
            return 0

        vectors = self.embedder.embed([c.text for c in chunks], input_type="document")
        rows = [
            {
                "chunk_id": chunk.chunk_id,
                "document_id": chunk.document_id,
                "chunk_index": chunk.chunk_index,
                "content": chunk.text,
                "source": chunk.source,
                "title": chunk.title,
                "metadata": chunk.metadata,
                "embedding": vector.tolist(),
            }
            for chunk, vector in zip(chunks, vectors)
        ]

        # Conflict on chunk_id makes re-ingesting an unchanged document a no-op.
        self._client.table(self.table).upsert(rows, on_conflict="chunk_id").execute()
        return len(rows)

    def search(self, query: str, top_k: int = 5, min_score: float = 0.0) -> list[SearchResult]:
        if not query.strip():
            return []

        query_vector = self.embedder.embed([query], input_type="query")[0]
        response = self._client.rpc(
            self.match_function,
            {
                "query_embedding": query_vector.tolist(),
                "match_count": top_k,
                "min_similarity": min_score,
            },
        ).execute()

        return [
            SearchResult(
                chunk=Chunk(
                    text=row["content"],
                    document_id=row["document_id"],
                    chunk_index=row["chunk_index"],
                    source=row.get("source", ""),
                    title=row.get("title", ""),
                    metadata=row.get("metadata") or {},
                ),
                score=float(row["similarity"]),
            )
            for row in (response.data or [])
        ]

    def delete_document(self, document_id: str) -> int:
        response = (
            self._client.table(self.table).delete().eq("document_id", document_id).execute()
        )
        return len(response.data or [])

    def count(self) -> int:
        response = self._client.table(self.table).select("chunk_id", count="exact").execute()
        return response.count or 0
