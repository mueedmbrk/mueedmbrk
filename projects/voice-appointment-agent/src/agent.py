"""Turning a caller's words into a booking intent.

Natural time expressions ("next Tuesday afternoon", "tomorrow first thing") are
exactly what a language model is good at and what regex is bad at. But the model's
answer is never trusted directly — it is parsed into a concrete datetime, and that
datetime is then validated by the pure scheduling rules. The model proposes; the
rules decide.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

logger = logging.getLogger(__name__)

INTENT_SYSTEM = """You extract appointment booking details from a phone call transcript.

Return ONLY a JSON object, no other text, with these keys:
  "intent":      one of "book", "reschedule", "cancel", "enquiry", "unclear"
  "datetime":    the requested slot as "YYYY-MM-DDTHH:MM", or null if not stated
  "name":        the caller's name, or null
  "phone":       the caller's phone number, or null
  "reason":      why they are calling, in a few words, or null
  "confidence":  0.0 to 1.0, how sure you are of the datetime

The current date and time is {now} ({timezone}).
Resolve relative expressions ("tomorrow", "next Tuesday", "this afternoon") against it.
If the caller gives a time with no date, assume the next occurrence of that time.
If no specific time was requested, set "datetime" to null and "confidence" to 0.0.
Never invent a time the caller did not ask for."""

REPLY_SYSTEM = """You are a warm, efficient phone receptionist for {business_name}.

You are speaking aloud, so keep replies to one or two short sentences. Do not use
lists, markdown or symbols — everything you say will be read out by a voice system.
Confirm details back to the caller so they can correct mistakes.
Never promise a time that has not been confirmed as available."""


@dataclass
class BookingIntent:
    """What the caller wants, as extracted from the transcript."""

    intent: str = "unclear"
    requested_datetime: datetime | None = None
    name: str | None = None
    phone: str | None = None
    reason: str | None = None
    confidence: float = 0.0

    @property
    def is_actionable(self) -> bool:
        """Only act on a booking when the model is genuinely confident of the time.

        A low-confidence guess that books the wrong slot is far more damaging than
        asking the caller to repeat themselves.
        """
        return (
            self.intent == "book"
            and self.requested_datetime is not None
            and self.confidence >= 0.6
        )


class LLMClient(Protocol):
    def complete(self, system: str, messages: list[dict]) -> str: ...


class ClaudeClient:
    """Claude behind the same small protocol used everywhere else in this project."""

    def __init__(self, api_key: str, model: str = "claude-opus-5", max_tokens: int = 1024) -> None:
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY is not set")

        import anthropic

        self.model = model
        self.max_tokens = max_tokens
        self._client = anthropic.Anthropic(api_key=api_key)

    def complete(self, system: str, messages: list[dict]) -> str:
        with self._client.messages.stream(
            model=self.model, max_tokens=self.max_tokens, system=system, messages=messages
        ) as stream:
            response = stream.get_final_message()

        return "".join(b.text for b in response.content if b.type == "text").strip()


def _extract_json(raw: str) -> dict:
    """Pull the JSON object out of a reply, tolerating stray prose or code fences."""
    text = raw.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def parse_intent(
    llm: LLMClient, transcript: str, now: datetime, timezone_name: str = "UTC"
) -> BookingIntent:
    """Ask the model for structured booking details, defensively."""
    if not transcript.strip():
        return BookingIntent(intent="unclear")

    system = INTENT_SYSTEM.format(now=now.strftime("%Y-%m-%d %H:%M (%A)"), timezone=timezone_name)

    try:
        raw = llm.complete(system, [{"role": "user", "content": transcript}])
        data = _extract_json(raw)
    except Exception as exc:  # noqa: BLE001 - an unparseable reply must not drop the call
        logger.error("Intent parsing failed: %s", exc)
        return BookingIntent(intent="unclear")

    requested = None
    raw_datetime = data.get("datetime")
    if raw_datetime:
        try:
            requested = datetime.fromisoformat(str(raw_datetime))
            if now.tzinfo is not None and requested.tzinfo is None:
                requested = requested.replace(tzinfo=now.tzinfo)
        except ValueError:
            logger.warning("Model returned an unparseable datetime: %r", raw_datetime)

    try:
        confidence = float(data.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0

    return BookingIntent(
        intent=str(data.get("intent") or "unclear"),
        requested_datetime=requested,
        name=data.get("name"),
        phone=data.get("phone"),
        reason=data.get("reason"),
        confidence=max(0.0, min(1.0, confidence)),
    )


def compose_reply(llm: LLMClient, business_name: str, situation: str) -> str:
    """Write what the agent should say next, in a form safe to read aloud."""
    try:
        return llm.complete(
            REPLY_SYSTEM.format(business_name=business_name),
            [{"role": "user", "content": situation}],
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Reply generation failed: %s", exc)
        return "I'm sorry, I'm having trouble just now. Let me put you through to a colleague."


def describe_alternatives(slots: list) -> str:
    """Turn slot objects into something a person would actually say."""
    if not slots:
        return "no availability in the next few weeks"
    if len(slots) == 1:
        return slots[0].humanise()
    spoken = [slot.humanise() for slot in slots[:3]]
    return ", ".join(spoken[:-1]) + f", or {spoken[-1]}"
