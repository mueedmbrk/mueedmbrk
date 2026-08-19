"""Speech to text via Whisper."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)


@dataclass
class Transcript:
    text: str
    language: str = "en"
    duration_seconds: float = 0.0

    @property
    def is_usable(self) -> bool:
        """Very short transcripts are usually silence, hold music or a dropped call."""
        return len(self.text.strip()) >= 3


class Transcriber(Protocol):
    def transcribe(self, audio_path: str | Path) -> Transcript: ...


class WhisperTranscriber:
    """Local Whisper. The model is loaded once and reused across calls."""

    def __init__(self, model_name: str = "base") -> None:
        self.model_name = model_name
        self._model = None

    def _load(self):
        if self._model is None:
            import whisper

            logger.info("🎙️  Loading Whisper model '%s'", self.model_name)
            self._model = whisper.load_model(self.model_name)
        return self._model

    def transcribe(self, audio_path: str | Path) -> Transcript:
        path = Path(audio_path)
        if not path.exists():
            raise FileNotFoundError(f"audio file not found: {path}")

        result = self._load().transcribe(str(path), fp16=False)
        return Transcript(
            text=str(result.get("text", "")).strip(),
            language=str(result.get("language", "en")),
            duration_seconds=float(result.get("duration", 0.0) or 0.0),
        )
