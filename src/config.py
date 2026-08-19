"""Configuration for the chatbot, loaded from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    model: str = os.getenv("CLAUDE_MODEL", "claude-opus-5")
    max_tokens: int = int(os.getenv("MAX_TOKENS") or 1024)

    business_name: str = os.getenv("BUSINESS_NAME", "our company")
    business_hours: str = os.getenv("BUSINESS_HOURS", "Mon-Fri 9am-6pm")
    support_email: str = os.getenv("SUPPORT_EMAIL", "support@example.com")

    faq_confidence_threshold: float = float(os.getenv("FAQ_CONFIDENCE_THRESHOLD") or 0.35)
    max_history_turns: int = int(os.getenv("MAX_HISTORY_TURNS") or 12)
    handoff_webhook_url: str = os.getenv("HANDOFF_WEBHOOK_URL", "")


settings = Settings()
