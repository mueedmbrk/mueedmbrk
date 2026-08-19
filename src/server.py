"""FastAPI webhook layer — the entry point for web widgets, WhatsApp or n8n."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .chatbot import Chatbot
from .config import settings
from .llm import ClaudeClient

app = FastAPI(
    title="Business Automation Chatbot",
    description="FAQ-grounded conversational agent with lead capture and human handoff.",
    version="1.0.0",
)

_bot: Chatbot | None = None


def get_bot() -> Chatbot:
    """Built on first request so the app can start without credentials present."""
    global _bot
    if _bot is None:
        _bot = Chatbot(llm=ClaudeClient(settings))
    return _bot


class ChatRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model": settings.model}


@app.post("/chat")
def chat(request: ChatRequest) -> dict:
    try:
        reply = get_bot().respond(request.session_id, request.message)
    except ValueError as exc:  # missing API key
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {
        "reply": reply.text,
        "source": reply.source,
        "escalated": reply.escalated,
        "lead": reply.lead,
        "confidence": round(reply.confidence, 4),
    }


@app.post("/reset/{session_id}")
def reset(session_id: str) -> dict:
    get_bot().reset(session_id)
    return {"status": "reset", "session_id": session_id}
