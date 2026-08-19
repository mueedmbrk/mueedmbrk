"""Pipeline configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    output_dir: Path = Path(os.getenv("OUTPUT_DIR", "outputs"))
    state_db: Path = Path(os.getenv("STATE_DB", "outputs/pipeline.db"))

    api_base_url: str = os.getenv("API_BASE_URL", "")
    api_token: str = os.getenv("API_TOKEN", "")
    request_timeout: int = int(os.getenv("REQUEST_TIMEOUT") or 30)
    max_retries: int = int(os.getenv("MAX_RETRIES") or 3)

    max_null_ratio: float = float(os.getenv("MAX_NULL_RATIO") or 0.20)
    min_rows: int = int(os.getenv("MIN_ROWS") or 1)

    report_webhook_url: str = os.getenv("REPORT_WEBHOOK_URL", "")


settings = Settings()
