"""End-to-end call handling: audio in, booking out."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from .agent import BookingIntent, LLMClient, compose_reply, describe_alternatives, parse_intent
from .config import Settings, settings as default_settings
from .integrations import CalendarClient, InMemoryCalendar, Notifier, NullNotifier, escalate
from .scheduling import BookingResult, BookingRules, BookingStatus, Scheduler, Slot
from .transcribe import Transcriber, Transcript

logger = logging.getLogger(__name__)


@dataclass
class CallOutcome:
    """Everything that happened on one call."""

    transcript: str = ""
    intent: BookingIntent = field(default_factory=BookingIntent)
    booking: BookingResult | None = None
    reply: str = ""
    event_id: str | None = None
    sms_sent: bool = False
    escalated: bool = False

    @property
    def booked(self) -> bool:
        return self.booking is not None and self.booking.confirmed

    def as_dict(self) -> dict:
        return {
            "transcript": self.transcript,
            "intent": self.intent.intent,
            "confidence": self.intent.confidence,
            "caller_name": self.intent.name,
            "caller_phone": self.intent.phone,
            "booked": self.booked,
            "slot": self.booking.slot.as_dict() if self.booked and self.booking.slot else None,
            "status": self.booking.status.value if self.booking else None,
            "reply": self.reply,
            "event_id": self.event_id,
            "sms_sent": self.sms_sent,
            "escalated": self.escalated,
        }


class AppointmentAgent:
    """Wires transcription, intent parsing, scheduling and confirmation together."""

    def __init__(
        self,
        llm: LLMClient,
        transcriber: Transcriber | None = None,
        calendar: CalendarClient | None = None,
        notifier: Notifier | None = None,
        config: Settings | None = None,
        business_name: str = "our clinic",
    ) -> None:
        self.config = config or default_settings
        self.llm = llm
        self.transcriber = transcriber
        self.calendar = calendar or InMemoryCalendar()
        self.notifier = notifier or NullNotifier()
        self.business_name = business_name
        self.scheduler = Scheduler(
            BookingRules(
                opening_hour=self.config.opening_hour,
                closing_hour=self.config.closing_hour,
                slot_minutes=self.config.slot_minutes,
                buffer_minutes=self.config.buffer_minutes,
                max_days_ahead=self.config.max_days_ahead,
                working_days=self.config.working_days,
            )
        )

    # ------------------------------------------------------------------ entry

    def handle_audio(self, audio_path: str | Path, now: datetime | None = None) -> CallOutcome:
        if self.transcriber is None:
            raise ValueError("no transcriber configured")

        transcript: Transcript = self.transcriber.transcribe(audio_path)
        if not transcript.is_usable:
            # Silence or a dropped call — do not send it to the model.
            return self._escalate_outcome(
                CallOutcome(transcript=transcript.text),
                "I couldn't hear anything on the line. Let me pass you to a colleague.",
            )

        return self.handle_transcript(transcript.text, now=now)

    def handle_transcript(self, text: str, now: datetime | None = None) -> CallOutcome:
        now = now or datetime.now()
        outcome = CallOutcome(transcript=text)

        outcome.intent = parse_intent(self.llm, text, now, self.config.timezone)

        if outcome.intent.intent in {"cancel", "reschedule"}:
            return self._escalate_outcome(
                outcome,
                "I'll put you through to a colleague who can change your existing appointment.",
            )

        if not outcome.intent.is_actionable:
            return self._clarify(outcome, now)

        return self._attempt_booking(outcome, now)

    # -------------------------------------------------------------- internals

    def _busy(self, now: datetime) -> list[Slot]:
        window_end = now + timedelta(days=self.config.max_days_ahead + 1)
        return self.calendar.busy_slots(now, window_end)

    def _attempt_booking(self, outcome: CallOutcome, now: datetime) -> CallOutcome:
        start = outcome.intent.requested_datetime
        assert start is not None  # guaranteed by is_actionable
        requested = Slot(start, start + timedelta(minutes=self.config.slot_minutes))

        busy = self._busy(now)
        result = self.scheduler.book(requested, busy, now)
        outcome.booking = result

        if not result.confirmed:
            alternatives = describe_alternatives(result.alternatives)
            outcome.reply = compose_reply(
                self.llm,
                self.business_name,
                f"The caller asked for {requested.humanise()}, but {result.message} "
                f"Offer these instead: {alternatives}. Ask which suits them.",
            )
            return outcome

        # Write to the calendar first. If that fails there is no appointment, and
        # telling the caller otherwise is the worst possible outcome.
        summary = f"Appointment — {outcome.intent.name or 'caller'}"
        try:
            outcome.event_id = self.calendar.create_event(
                requested, summary, outcome.intent.reason or ""
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Calendar write failed: %s", exc)
            outcome.booking = BookingResult(
                BookingStatus.SLOT_TAKEN, message="the booking could not be saved"
            )
            return self._escalate_outcome(
                outcome,
                "I'm having trouble saving that booking. Let me put you through to a colleague.",
            )

        outcome.reply = compose_reply(
            self.llm,
            self.business_name,
            f"Confirm to the caller that their appointment is booked for "
            f"{requested.humanise()}. Thank them and say they'll get a text confirmation.",
        )

        if outcome.intent.phone:
            outcome.sms_sent = self.notifier.send(
                outcome.intent.phone,
                f"Your appointment with {self.business_name} is confirmed for "
                f"{requested.humanise()}.",
            )

        return outcome

    def _clarify(self, outcome: CallOutcome, now: datetime) -> CallOutcome:
        """Ask again rather than guess. A wrong booking is worse than a second question."""
        upcoming = self.scheduler.next_available(now, self._busy(now), count=3)
        outcome.reply = compose_reply(
            self.llm,
            self.business_name,
            "The caller has not clearly stated a date and time. Ask them politely when "
            f"they would like to come in, and mention we have {describe_alternatives(upcoming)}.",
        )
        return outcome

    def _escalate_outcome(self, outcome: CallOutcome, reply: str) -> CallOutcome:
        outcome.reply = reply
        outcome.escalated = True
        escalate(self.config.escalation_webhook_url, outcome.as_dict())
        return outcome
