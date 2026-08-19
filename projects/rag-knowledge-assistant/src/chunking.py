"""Splitting documents into retrievable chunks.

Chunk quality sets the ceiling on answer quality — retrieval cannot recover
information that a bad split severed. Two rules matter most:

* **Split on structure, not character count.** A chunk that ends mid-sentence
  retrieves badly and reads worse when quoted back as a citation.
* **Overlap neighbours.** A fact that straddles a boundary would otherwise be
  invisible to both chunks.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

# Prefer to break at a paragraph, then a sentence, then a line, then a word.
BOUNDARY_PATTERNS = (
    re.compile(r"\n\s*\n"),          # paragraph
    re.compile(r"(?<=[.!?])\s+"),    # sentence
    re.compile(r"\n"),               # line
    re.compile(r"\s+"),              # word
)


@dataclass
class Chunk:
    """One retrievable passage plus enough metadata to cite it."""

    text: str
    document_id: str
    chunk_index: int
    source: str = ""
    title: str = ""
    metadata: dict = field(default_factory=dict)

    @property
    def chunk_id(self) -> str:
        """Deterministic ID: re-ingesting an unchanged document reuses the same rows.

        This is what makes re-indexing idempotent — without it, every ingest would
        duplicate the corpus and retrieval would return the same passage repeatedly.
        """
        digest = hashlib.sha256(f"{self.document_id}:{self.chunk_index}:{self.text}".encode())
        return digest.hexdigest()[:32]

    @property
    def citation(self) -> str:
        label = self.title or self.source or self.document_id
        return f"{label} (part {self.chunk_index + 1})"

    def as_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "chunk_index": self.chunk_index,
            "text": self.text,
            "source": self.source,
            "title": self.title,
            "metadata": self.metadata,
        }


def _find_split_point(text: str, target: int) -> int:
    """Find the best boundary at or before ``target``, falling back down the hierarchy."""
    window = text[:target]

    for pattern in BOUNDARY_PATTERNS:
        matches = list(pattern.finditer(window))
        if matches:
            # Only accept a boundary that is not uselessly early in the chunk.
            position = matches[-1].end()
            if position > target * 0.5:
                return position

    return target


def chunk_text(
    text: str,
    document_id: str,
    chunk_size: int = 800,
    overlap: int = 150,
    source: str = "",
    title: str = "",
    metadata: dict | None = None,
) -> list[Chunk]:
    """Split ``text`` into overlapping chunks that end on natural boundaries."""
    if chunk_size < 1:
        raise ValueError("chunk_size must be positive")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be non-negative and smaller than chunk_size")

    cleaned = re.sub(r"[ \t]+", " ", text).strip()
    if not cleaned:
        return []

    chunks: list[Chunk] = []
    position = 0
    index = 0

    while position < len(cleaned):
        remaining = cleaned[position:]

        if len(remaining) <= chunk_size:
            body = remaining
            advance = len(remaining)
        else:
            split = _find_split_point(remaining, chunk_size)
            body = remaining[:split]
            # Step back by the overlap so a fact spanning the boundary is in both chunks.
            advance = max(1, split - overlap)

        body = body.strip()
        if body:
            chunks.append(
                Chunk(
                    text=body,
                    document_id=document_id,
                    chunk_index=index,
                    source=source,
                    title=title,
                    metadata=dict(metadata or {}),
                )
            )
            index += 1

        position += advance

    return chunks


def chunk_document(
    path: str,
    document_id: str | None = None,
    chunk_size: int = 800,
    overlap: int = 150,
    metadata: dict | None = None,
) -> list[Chunk]:
    """Read a text file from disk and chunk it."""
    from pathlib import Path

    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8", errors="replace")

    return chunk_text(
        text,
        document_id=document_id or file_path.stem,
        chunk_size=chunk_size,
        overlap=overlap,
        source=str(file_path),
        title=file_path.stem.replace("_", " ").replace("-", " ").title(),
        metadata=metadata,
    )
