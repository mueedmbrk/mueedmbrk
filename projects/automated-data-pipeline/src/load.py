"""Loading: writing results out, and remembering what previous runs did."""

from __future__ import annotations

import json
import logging
import sqlite3
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


class Sink(ABC):
    @abstractmethod
    def load(self, frame: pd.DataFrame) -> str: ...


class CSVSink(Sink):
    """Writes a timestamped CSV, keeping history rather than overwriting it."""

    def __init__(self, directory: str | Path, prefix: str = "dataset") -> None:
        self.directory = Path(directory)
        self.prefix = prefix

    def load(self, frame: pd.DataFrame) -> str:
        self.directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        path = self.directory / f"{self.prefix}_{stamp}.csv"
        frame.to_csv(path, index=False)
        logger.info("💾 Wrote %d rows to %s", len(frame), path)
        return str(path)


class SQLiteSink(Sink):
    """Upserts into SQLite — the mode that makes a re-run safe.

    ``replace`` gives idempotency: running the same day twice leaves one copy of the
    data, not two. ``append`` is available when history is genuinely wanted.
    """

    def __init__(self, database: str | Path, table: str, if_exists: str = "replace") -> None:
        self.database = Path(database)
        self.table = table
        self.if_exists = if_exists

    def load(self, frame: pd.DataFrame) -> str:
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database) as connection:
            frame.to_sql(self.table, connection, if_exists=self.if_exists, index=False)
        logger.info("💾 Wrote %d rows to %s:%s", len(frame), self.database, self.table)
        return f"{self.database}:{self.table}"


class RunHistory:
    """Persists one row per pipeline run, so failures and trends are visible later."""

    def __init__(self, database: str | Path) -> None:
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_table()

    def _ensure_table(self) -> None:
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS pipeline_runs (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at   TEXT NOT NULL,
                    finished_at  TEXT,
                    status       TEXT NOT NULL,
                    rows_in      INTEGER,
                    rows_out     INTEGER,
                    duration_s   REAL,
                    error        TEXT,
                    details      TEXT
                )
                """
            )

    def record(
        self,
        started_at: datetime,
        finished_at: datetime,
        status: str,
        rows_in: int,
        rows_out: int,
        error: str = "",
        details: dict | None = None,
    ) -> int:
        with sqlite3.connect(self.database) as connection:
            cursor = connection.execute(
                """
                INSERT INTO pipeline_runs
                    (started_at, finished_at, status, rows_in, rows_out, duration_s, error, details)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    started_at.isoformat(),
                    finished_at.isoformat(),
                    status,
                    rows_in,
                    rows_out,
                    (finished_at - started_at).total_seconds(),
                    error,
                    json.dumps(details or {}, default=str),
                ),
            )
            return int(cursor.lastrowid)

    def recent(self, limit: int = 10) -> pd.DataFrame:
        with sqlite3.connect(self.database) as connection:
            return pd.read_sql_query(
                "SELECT * FROM pipeline_runs ORDER BY id DESC LIMIT ?", connection, params=(limit,)
            )
