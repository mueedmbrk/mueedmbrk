"""External services: calendar, SMS and speech synthesis.

Each is behind a protocol with a no-op implementation, so the orchestrator runs
end-to-end in development and in tests without credentials for any of them.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol

import requests

from .scheduling import Slot

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ calendar

class CalendarClient(Protocol):
    def busy_slots(self, start: datetime, end: datetime) -> list[Slot]: ...
    def create_event(self, slot: Slot, summary: str, description: str = "") -> str: ...


class InMemoryCalendar:
    """A calendar that lives in a list. Used for development and the test suite."""

    def __init__(self, busy: list[Slot] | None = None) -> None:
        self._busy = list(busy or [])
        self.created: list[tuple[Slot, str]] = []

    def busy_slots(self, start: datetime, end: datetime) -> list[Slot]:
        return [s for s in self._busy if s.start < end and start < s.end]

    def create_event(self, slot: Slot, summary: str, description: str = "") -> str:
        self._busy.append(slot)
        self.created.append((slot, summary))
        return f"mem-{len(self.created)}"


class GoogleCalendarClient:
    """Google Calendar via the official client library."""

    SCOPES = ("https://www.googleapis.com/auth/calendar",)

    def __init__(
        self,
        calendar_id: str = "primary",
        credentials_file: str = "credentials.json",
        token_file: str = "token.json",
        timezone: str = "UTC",
    ) -> None:
        self.calendar_id = calendar_id
        self.credentials_file = credentials_file
        self.token_file = token_file
        self.timezone = timezone
        self._service = None

    def _get_service(self):
        if self._service is not None:
            return self._service

        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build

        creds = None
        if Path(self.token_file).exists():
            creds = Credentials.from_authorized_user_file(self.token_file, list(self.SCOPES))

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credentials_file, list(self.SCOPES)
                )
                creds = flow.run_local_server(port=0)
            Path(self.token_file).write_text(creds.to_json(), encoding="utf-8")

        self._service = build("calendar", "v3", credentials=creds)
        return self._service

    def busy_slots(self, start: datetime, end: datetime) -> list[Slot]:
        """Query free/busy rather than listing events.

        Free/busy returns exactly the blocked intervals — it already accounts for
        declined invitations and all-day events, which a raw event list does not.
        """
        response = (
            self._get_service()
            .freebusy()
            .query(
                body={
                    "timeMin": start.isoformat(),
                    "timeMax": end.isoformat(),
                    "timeZone": self.timezone,
                    "items": [{"id": self.calendar_id}],
                }
            )
            .execute()
        )

        periods = response["calendars"][self.calendar_id].get("busy", [])
        return [
            Slot(datetime.fromisoformat(p["start"]), datetime.fromisoformat(p["end"]))
            for p in periods
        ]

    def create_event(self, slot: Slot, summary: str, description: str = "") -> str:
        event = (
            self._get_service()
            .events()
            .insert(
                calendarId=self.calendar_id,
                body={
                    "summary": summary,
                    "description": description,
                    "start": {"dateTime": slot.start.isoformat(), "timeZone": self.timezone},
                    "end": {"dateTime": slot.end.isoformat(), "timeZone": self.timezone},
                },
            )
            .execute()
        )
        return str(event.get("id", ""))


# ----------------------------------------------------------------------- SMS

class Notifier(Protocol):
    def send(self, to: str, message: str) -> bool: ...


class NullNotifier:
    """Logs instead of sending. The default when Twilio is not configured."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send(self, to: str, message: str) -> bool:
        self.sent.append((to, message))
        logger.info("📱 [dry-run] SMS to %s: %s", to, message)
        return True


class TwilioNotifier:
    def __init__(self, account_sid: str, auth_token: str, from_number: str) -> None:
        self.from_number = from_number
        self._sid = account_sid
        self._token = auth_token
        self._client = None

    def send(self, to: str, message: str) -> bool:
        try:
            if self._client is None:
                from twilio.rest import Client

                self._client = Client(self._sid, self._token)
            self._client.messages.create(body=message, from_=self.from_number, to=to)
            return True
        except Exception as exc:  # noqa: BLE001 - a failed SMS must not undo the booking
            logger.error("SMS failed to %s: %s", to, exc)
            return False


# ------------------------------------------------------------------------ TTS

class ElevenLabsVoice:
    """Renders the agent's reply to speech."""

    API_URL = "https://api.elevenlabs.io/v1/text-to-speech"

    def __init__(self, api_key: str, voice_id: str, timeout: float = 30.0) -> None:
        self.api_key = api_key
        self.voice_id = voice_id
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.voice_id)

    def synthesise(self, text: str, output_path: str | Path) -> str | None:
        """Write spoken audio to ``output_path``; returns None when unavailable.

        A failure here degrades to text rather than dropping the call — the caller
        still gets an answer, just not in a synthesised voice.
        """
        if not self.configured:
            logger.info("🔇 ElevenLabs not configured; skipping speech synthesis")
            return None

        try:
            response = requests.post(
                f"{self.API_URL}/{self.voice_id}",
                headers={"xi-api-key": self.api_key, "Content-Type": "application/json"},
                json={
                    "text": text,
                    "model_id": "eleven_multilingual_v2",
                    "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.error("Speech synthesis failed: %s", exc)
            return None

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(response.content)
        return str(path)


def escalate(webhook_url: str, payload: dict) -> bool:
    """Hand the call to a human via webhook. Never raises into the call path."""
    if not webhook_url:
        return False
    try:
        response = requests.post(webhook_url, json=payload, timeout=5)
        response.raise_for_status()
        return True
    except requests.RequestException as exc:
        logger.error("Escalation webhook failed: %s", exc)
        return False
