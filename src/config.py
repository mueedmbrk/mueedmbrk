"""Configuration for the RAG assistant."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    model: str = os.getenv("CLAUDE_MODEL", "claude-opus-5")
    max_tokens: int = int(os.getenv("MAX_TOKENS") or 2048)

    voyage_api_key: str = os.getenv("VOYAGE_API_KEY", "")
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "voyage-3")
    embedding_dimensions: int = int(os.getenv("EMBEDDING_DIMENSIONS") or 1024)

    supabase_url: str = os.getenv("SUPABASE_URL", "")
    supabase_key: str = os.getenv("SUPABASE_KEY", "")
    supabase_table: str = os.getenv("SUPABASE_TABLE", "document_chunks")

    chunk_size: int = int(os.getenv("CHUNK_SIZE") or 800)
    chunk_overlap: int = int(os.getenv("CHUNK_OVERLAP") or 150)

    top_k: int = int(os.getenv("TOP_K") or 5)
    min_similarity: float = float(os.getenv("MIN_SIMILARITY") or 0.35)


settings = Settings()
