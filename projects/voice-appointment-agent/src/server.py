"""Webhook layer — the entry point for Twilio, n8n or any telephony provider."""

from __future__ import annotations

import tempfile
from pathlib import Path

import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .agent import ClaudeClient
from .config import settings
from .integrations import (
    GoogleCalendarClient,
    InMemoryCalendar,
    NullNotifier,
    TwilioNotifier,
)
from .orchestrator import AppointmentAgent
from .transcribe import WhisperTranscriber

app = FastAPI(
    title="Voice Appointment Agent",
    description="Transcribe a call, understand the request, book the slot, confirm by SMS.",
    version="1.0.0",
)

_agent: AppointmentAgent | None = None


def get_agent() -> AppointmentAgent:
    """Assemble on first request, using real integrations only where configured."""
    global _agent
    if _agent is not None:
        return _agent

    calendar = (
        GoogleCalendarClient(
            calendar_id=settings.calendar_id,
            credentials_file=settings.credentials_file,
            token_file=settings.token_file,
            timezone=settings.timezone,
        )
        if Path(settings.credentials_file).exists()
        else InMemoryCalendar()
    )

    notifier = (
        TwilioNotifier(settings.twilio_sid, settings.twilio_token, settings.twilio_from)
        if all([settings.twilio_sid, settings.twilio_token, settings.twilio_from])
        else NullNotifier()
    )

    _agent = AppointmentAgent(
        llm=ClaudeClient(settings.api_key, settings.model),
        transcriber=WhisperTranscriber(settings.whisper_model),
        calendar=calendar,
        notifier=notifier,
        config=settings,
    )
    return _agent


class TranscriptRequest(BaseModel):
    transcript: str = Field(..., min_length=1)


class RecordingRequest(BaseModel):
    recording_url: str = Field(..., min_length=1)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model": settings.model}


@app.post("/call/transcript")
def handle_transcript(request: TranscriptRequest) -> dict:
    """For providers that transcribe upstream, or for testing without audio."""
    try:
        return get_agent().handle_transcript(request.transcript).as_dict()
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/call/recording")
def handle_recording(request: RecordingRequest) -> dict:
    """Download the provider's recording, transcribe it, then handle the call."""
    try:
        response = requests.get(request.recording_url, timeout=60)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"could not fetch recording: {exc}") from exc

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
        handle.write(response.content)
        audio_path = handle.name

    try:
        return get_agent().handle_audio(audio_path).as_dict()
    finally:
        Path(audio_path).unlink(missing_ok=True)
