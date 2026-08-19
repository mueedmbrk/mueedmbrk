"""Ingestion: documents on disk into the vector store."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from .chunking import Chunk, chunk_document
from .vector_store import VectorStore

logger = logging.getLogger(__name__)

SUPPORTED_SUFFIXES = {".txt", ".md", ".markdown", ".rst"}
MANIFEST_NAME = ".ingest_manifest.json"


@dataclass
class IngestReport:
    documents_processed: int = 0
    documents_skipped: int = 0
    chunks_written: int = 0
    failures: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"{self.documents_processed} document(s) indexed, "
            f"{self.documents_skipped} unchanged, "
            f"{self.chunks_written} chunk(s) written"
        )


def file_fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:32]


class Ingestor:
    """Indexes a folder, re-processing only what actually changed.

    A manifest of content hashes is kept alongside the corpus. Re-indexing an
    unchanged 500-document folder then costs nothing — which is what makes it
    reasonable to run on every file change rather than nightly.
    """

    def __init__(
        self,
        store: VectorStore,
        chunk_size: int = 800,
        chunk_overlap: int = 150,
    ) -> None:
        self.store = store
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def _load_manifest(self, directory: Path) -> dict[str, str]:
        path = directory / MANIFEST_NAME
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("Manifest unreadable; re-indexing everything")
            return {}

    def _save_manifest(self, directory: Path, manifest: dict[str, str]) -> None:
        try:
            (directory / MANIFEST_NAME).write_text(
                json.dumps(manifest, indent=2), encoding="utf-8"
            )
        except OSError as exc:
            logger.error("Could not write manifest: %s", exc)

    def ingest_file(self, path: str | Path, document_id: str | None = None) -> list[Chunk]:
        chunks = chunk_document(
            str(path),
            document_id=document_id,
            chunk_size=self.chunk_size,
            overlap=self.chunk_overlap,
        )
        if chunks:
            self.store.upsert(chunks)
        return chunks

    def ingest_directory(self, directory: str | Path, force: bool = False) -> IngestReport:
        directory = Path(directory)
        if not directory.is_dir():
            raise NotADirectoryError(f"not a directory: {directory}")

        manifest = {} if force else self._load_manifest(directory)
        report = IngestReport()

        for path in sorted(directory.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in SUPPORTED_SUFFIXES:
                continue

            key = str(path.relative_to(directory))
            try:
                fingerprint = file_fingerprint(path)
            except OSError as exc:
                report.failures.append(f"{key}: {exc}")
                continue

            if manifest.get(key) == fingerprint:
                report.documents_skipped += 1
                continue

            try:
                # Drop the old chunks first — an edit that shortens a document would
                # otherwise leave orphaned chunks that still surface in retrieval.
                self.store.delete_document(path.stem)
                chunks = self.ingest_file(path)
            except Exception as exc:  # noqa: BLE001 - one bad file must not stop the batch
                logger.error("Failed to ingest %s: %s", key, exc)
                report.failures.append(f"{key}: {exc}")
                continue

            manifest[key] = fingerprint
            report.documents_processed += 1
            report.chunks_written += len(chunks)
            logger.info("📚 %s → %d chunk(s)", key, len(chunks))

        self._save_manifest(directory, manifest)
        return report
