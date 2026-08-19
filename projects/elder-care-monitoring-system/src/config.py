"""Runtime configuration, loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _env_float(name: str, default: float) -> float:
    return float(os.getenv(name) or default)


def _env_int(name: str, default: int) -> int:
    return int(os.getenv(name) or default)


@dataclass(frozen=True)
class Settings:
    """All tunable knobs in one place, so nothing is hard-coded in the detector."""

    camera_source: str = os.getenv("CAMERA_SOURCE", "0")
    fall_aspect_ratio: float = _env_float("FALL_ASPECT_RATIO", 1.25)
    fall_confirm_frames: int = _env_int("FALL_CONFIRM_FRAMES", 18)
    min_contour_area: int = _env_int("MIN_CONTOUR_AREA", 2500)
    drop_velocity: float = _env_float("DROP_VELOCITY", 0.045)

    alert_cooldown_seconds: int = _env_int("ALERT_COOLDOWN_SECONDS", 120)
    webhook_url: str = os.getenv("ALERT_WEBHOOK_URL", "")
    twilio_sid: str = os.getenv("TWILIO_ACCOUNT_SID", "")
    twilio_token: str = os.getenv("TWILIO_AUTH_TOKEN", "")
    twilio_from: str = os.getenv("TWILIO_FROM_NUMBER", "")
    carer_phone: str = os.getenv("CARER_PHONE_NUMBER", "")

    def resolved_source(self):
        """A bare digit means a webcam index; anything else is a path or RTSP URL."""
        return int(self.camera_source) if self.camera_source.isdigit() else self.camera_source


settings = Settings()
