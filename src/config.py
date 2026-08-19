"""Configuration for the voice appointment agent."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _working_days() -> frozenset[int]:
    raw = os.getenv("WORKING_DAYS", "0,1,2,3,4")
    return frozenset(int(part) for part in raw.split(",") if part.strip().isdigit())


@dataclass(frozen=True)
class Settings:
    api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    model: str = os.getenv("CLAUDE_MODEL", "claude-opus-5")
    whisper_model: str = os.getenv("WHISPER_MODEL", "base")

    timezone: str = os.getenv("TIMEZONE", "Asia/Karachi")
    opening_hour: int = int(os.getenv("OPENING_HOUR") or 9)
    closing_hour: int = int(os.getenv("CLOSING_HOUR") or 17)
    slot_minutes: int = int(os.getenv("SLOT_MINUTES") or 30)
    buffer_minutes: int = int(os.getenv("BUFFER_MINUTES") or 0)
    max_days_ahead: int = int(os.getenv("MAX_DAYS_AHEAD") or 30)
    working_days: frozenset[int] = field(default_factory=_working_days)

    calendar_id: str = os.getenv("GOOGLE_CALENDAR_ID", "primary")
    credentials_file: str = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
    token_file: str = os.getenv("GOOGLE_TOKEN_FILE", "token.json")

    twilio_sid: str = os.getenv("TWILIO_ACCOUNT_SID", "")
    twilio_token: str = os.getenv("TWILIO_AUTH_TOKEN", "")
    twilio_from: str = os.getenv("TWILIO_FROM_NUMBER", "")

    elevenlabs_key: str = os.getenv("ELEVENLABS_API_KEY", "")
    elevenlabs_voice: str = os.getenv("ELEVENLABS_VOICE_ID", "")

    escalation_webhook_url: str = os.getenv("ESCALATION_WEBHOOK_URL", "")


settings = Settings()
