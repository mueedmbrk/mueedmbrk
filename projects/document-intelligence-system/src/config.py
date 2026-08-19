"""Configuration for the document pipeline."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    tesseract_cmd: str = os.getenv("TESSERACT_CMD", "")
    ocr_language: str = os.getenv("OCR_LANGUAGE", "eng")
    ocr_dpi: int = int(os.getenv("OCR_DPI") or 300)

    min_text_layer_chars: int = int(os.getenv("MIN_TEXT_LAYER_CHARS") or 120)
    classifier_threshold: float = float(os.getenv("CLASSIFIER_THRESHOLD") or 0.18)


settings = Settings()
