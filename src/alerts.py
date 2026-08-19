"""Alert delivery.

A fall is only useful if somebody hears about it. Channels are pluggable so the
same event can go to a console during development and to SMS in production, and
a cooldown stops one incident from turning into a pager storm.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import Iterable, Optional

import requests

logger = logging.getLogger(__name__)


class AlertChannel(ABC):
    """One way of telling a human that something happened."""

    @abstractmethod
    def send(self, message: str) -> bool:
        """Deliver ``message``; return True when it was accepted downstream."""


class ConsoleChannel(AlertChannel):
    """Prints to the log. Always available, useful for development and as a fallback."""

    def send(self, message: str) -> bool:
        logger.warning("ALERT: %s", message)
        return True


class WebhookChannel(AlertChannel):
    """POSTs the alert as JSON — the hook into n8n, Slack or a care-home dashboard."""

    def __init__(self, url: str, timeout: float = 5.0) -> None:
        self.url = url
        self.timeout = timeout

    def send(self, message: str) -> bool:
        try:
            response = requests.post(
                self.url,
                json={"event": "fall_detected", "message": message, "ts": time.time()},
                timeout=self.timeout,
            )
            response.raise_for_status()
            return True
        except requests.RequestException as exc:
            logger.error("Webhook alert failed: %s", exc)
            return False


class SMSChannel(AlertChannel):
    """Sends an SMS via Twilio — the channel that reaches a carer who is not at a screen."""

    def __init__(self, account_sid: str, auth_token: str, from_number: str, to_number: str) -> None:
        self.from_number = from_number
        self.to_number = to_number
        self._sid = account_sid
        self._token = auth_token
        self._client = None

    def _get_client(self):
        # Imported lazily so the package stays optional for console-only deployments.
        if self._client is None:
            from twilio.rest import Client

            self._client = Client(self._sid, self._token)
        return self._client

    def send(self, message: str) -> bool:
        try:
            self._get_client().messages.create(
                body=message, from_=self.from_number, to=self.to_number
            )
            return True
        except Exception as exc:  # noqa: BLE001 - any Twilio failure must not kill the monitor
            logger.error("SMS alert failed: %s", exc)
            return False


class AlertDispatcher:
    """Fans one alert out to every channel, with a per-incident cooldown.

    Delivery is best-effort by design: if SMS is down, the webhook and console
    still fire. A monitor that crashes because Twilio had a bad minute is worse
    than one that logs the failure and keeps watching.
    """

    def __init__(self, channels: Iterable[AlertChannel], cooldown_seconds: int = 120) -> None:
        self.channels = list(channels)
        self.cooldown_seconds = cooldown_seconds
        self._last_sent: Optional[float] = None

    def _in_cooldown(self, now: float) -> bool:
        return self._last_sent is not None and (now - self._last_sent) < self.cooldown_seconds

    def dispatch(self, message: str, now: Optional[float] = None) -> bool:
        """Send to all channels. Returns False when suppressed or every channel failed."""
        now = time.time() if now is None else now
        if self._in_cooldown(now):
            logger.info("Alert suppressed by cooldown: %s", message)
            return False

        self._last_sent = now
        results = [channel.send(message) for channel in self.channels]
        if not any(results):
            logger.error("Every alert channel failed for: %s", message)
        return any(results)


def build_dispatcher(settings) -> AlertDispatcher:
    """Assemble the channel list from configuration, skipping anything unconfigured."""
    channels: list[AlertChannel] = [ConsoleChannel()]

    if settings.webhook_url:
        channels.append(WebhookChannel(settings.webhook_url))

    if all([settings.twilio_sid, settings.twilio_token, settings.twilio_from, settings.carer_phone]):
        channels.append(
            SMSChannel(
                settings.twilio_sid,
                settings.twilio_token,
                settings.twilio_from,
                settings.carer_phone,
            )
        )

    return AlertDispatcher(channels, cooldown_seconds=settings.alert_cooldown_seconds)
