"""Extraction: getting raw data out of files, APIs and databases.

Every source returns a DataFrame, so the transform stage never needs to know where
the data came from. Network sources retry with exponential backoff, because the
single most common cause of a failed overnight run is one transient 503.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import pandas as pd
import requests

logger = logging.getLogger(__name__)


class ExtractionError(RuntimeError):
    """Raised when a source cannot be read after all retries."""


class Source(ABC):
    """One place data comes from."""

    @abstractmethod
    def extract(self) -> pd.DataFrame: ...

    @property
    def name(self) -> str:
        return type(self).__name__


class CSVSource(Source):
    def __init__(self, path: str | Path, **read_options: Any) -> None:
        self.path = Path(path)
        self.read_options = read_options

    def extract(self) -> pd.DataFrame:
        if not self.path.exists():
            raise ExtractionError(f"CSV source not found: {self.path}")
        logger.info("📂 Reading %s", self.path)
        return pd.read_csv(self.path, **self.read_options)


class APISource(Source):
    """Reads JSON from a REST endpoint, with retries on transient failures."""

    # Retrying a 404 or a 401 is pointless — only these are worth a second attempt.
    RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})

    def __init__(
        self,
        url: str,
        token: str = "",
        records_path: str | None = None,
        timeout: int = 30,
        max_retries: int = 3,
        backoff_base: float = 2.0,
    ) -> None:
        self.url = url
        self.token = token
        self.records_path = records_path
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_base = backoff_base

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _fetch(self) -> Any:
        last_error: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                response = requests.get(
                    self.url, headers=self._headers(), timeout=self.timeout
                )
                if response.status_code in self.RETRYABLE_STATUS:
                    raise requests.HTTPError(
                        f"retryable status {response.status_code}", response=response
                    )
                response.raise_for_status()
                return response.json()
            except requests.RequestException as exc:
                last_error = exc
                status = getattr(getattr(exc, "response", None), "status_code", None)
                if status is not None and status not in self.RETRYABLE_STATUS:
                    break  # a client error will fail identically next time
                if attempt < self.max_retries:
                    delay = self.backoff_base ** (attempt - 1)
                    logger.warning(
                        "⚠️  %s attempt %d/%d failed (%s) — retrying in %.0fs",
                        self.url, attempt, self.max_retries, exc, delay,
                    )
                    time.sleep(delay)

        raise ExtractionError(f"API source failed: {self.url} ({last_error})")

    def extract(self) -> pd.DataFrame:
        payload = self._fetch()

        # Unwrap a nested envelope like {"data": {"items": [...]}} when told where to look.
        if self.records_path:
            for key in self.records_path.split("."):
                payload = payload[key]

        if isinstance(payload, dict):
            payload = [payload]

        return pd.json_normalize(payload)


class SQLSource(Source):
    def __init__(self, database: str | Path, query: str) -> None:
        self.database = str(database)
        self.query = query

    def extract(self) -> pd.DataFrame:
        logger.info("🗄️  Querying %s", self.database)
        with sqlite3.connect(self.database) as connection:
            return pd.read_sql_query(self.query, connection)


def extract_all(sources: list[Source]) -> pd.DataFrame:
    """Read every source and stack the results.

    A source column is added so a row can always be traced back to where it came
    from — indispensable when a downstream number looks wrong.
    """
    if not sources:
        raise ValueError("at least one source is required")

    frames = []
    for source in sources:
        frame = source.extract()
        frame["_source"] = source.name
        frames.append(frame)
        logger.info("✅ %s produced %d rows", source.name, len(frame))

    return pd.concat(frames, ignore_index=True, sort=False)
