"""FastAPI service for the knowledge assistant."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .assistant import ClaudeClient, KnowledgeAssistant
from .config import settings
from .embeddings import HashingEmbeddings, VoyageEmbeddings
from .ingest import Ingestor
from .vector_store import InMemoryVectorStore, SupabaseVectorStore

app = FastAPI(
    title="RAG Knowledge Assistant",
    description="Answers staff questions from company documents, with cited sources.",
    version="1.0.0",
)

_assistant: KnowledgeAssistant | None = None
_store = None


def get_store():
    """Supabase when configured, in-memory otherwise — so it runs with zero setup."""
    global _store
    if _store is not None:
        return _store

    embedder = (
        VoyageEmbeddings(
            settings.voyage_api_key,
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
        )
        if settings.voyage_api_key
        else HashingEmbeddings()
    )

    _store = (
        SupabaseVectorStore(
            settings.supabase_url, settings.supabase_key, embedder, table=settings.supabase_table
        )
        if settings.supabase_url and settings.supabase_key
        else InMemoryVectorStore(embedder)
    )
    return _store


def get_assistant() -> KnowledgeAssistant:
    global _assistant
    if _assistant is None:
        _assistant = KnowledgeAssistant(
            llm=ClaudeClient(settings.api_key, settings.model, settings.max_tokens),
            store=get_store(),
            top_k=settings.top_k,
            min_similarity=settings.min_similarity,
        )
    return _assistant


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1)
    top_k: int | None = Field(None, ge=1, le=20)


class IngestRequest(BaseModel):
    directory: str = Field(..., min_length=1)
    force: bool = False


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model": settings.model, "chunks": get_store().count()}


@app.post("/ask")
def ask(request: AskRequest) -> dict:
    try:
        return get_assistant().ask(request.question, top_k=request.top_k).as_dict()
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/ingest")
def ingest(request: IngestRequest) -> dict:
    ingestor = Ingestor(
        get_store(), chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap
    )
    try:
        report = ingestor.ingest_directory(request.directory, force=request.force)
    except NotADirectoryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "documents_processed": report.documents_processed,
        "documents_skipped": report.documents_skipped,
        "chunks_written": report.chunks_written,
        "failures": report.failures,
        "summary": report.summary(),
    }
