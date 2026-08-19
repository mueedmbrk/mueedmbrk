"""Orchestration: extract → transform → validate → load → report."""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable

import pandas as pd

from .config import Settings, settings as default_settings
from .extract import ExtractionError, Source, extract_all
from .load import RunHistory, Sink
from .report import Report, build_report
from .transform import DataQualityError, TransformLog, check_quality, clean

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """The outcome of one run — everything needed to explain what happened."""

    status: str                      # "success" | "failed"
    rows_in: int = 0
    rows_out: int = 0
    duration_seconds: float = 0.0
    error: str = ""
    artifacts: dict[str, str] = field(default_factory=dict)
    report: Report | None = None
    transform_log: TransformLog | None = None

    @property
    def succeeded(self) -> bool:
        return self.status == "success"


@dataclass
class Pipeline:
    """A configured extract-transform-load-report run.

    Failures are captured and recorded rather than raised. A scheduled job that
    crashes leaves no trace of *why*; one that records a failed run with the reason
    can be diagnosed the next morning without re-running anything.
    """

    sources: list[Source]
    sinks: list[Sink] = field(default_factory=list)
    date_columns: Iterable[str] = ()
    numeric_columns: Iterable[str] = ()
    deduplicate_on: Iterable[str] | None = None
    required_columns: Iterable[str] = ()
    group_by: str | None = None
    value_column: str | None = None
    report_title: str = "Automated Data Report"
    config: Settings = field(default_factory=lambda: default_settings)

    def run(self) -> PipelineResult:
        started = datetime.now(timezone.utc)
        history = RunHistory(self.config.state_db)
        rows_in = rows_out = 0
        result: PipelineResult

        try:
            raw = extract_all(self.sources)
            rows_in = len(raw)

            cleaned, log = clean(
                raw,
                date_columns=self.date_columns,
                numeric_columns=self.numeric_columns,
                drop_duplicates_on=self.deduplicate_on,
            )
            rows_out = len(cleaned)

            check_quality(
                cleaned,
                log,
                max_null_ratio=self.config.max_null_ratio,
                min_rows=self.config.min_rows,
                required_columns=self.required_columns,
            )

            artifacts = {f"sink_{i}": sink.load(cleaned) for i, sink in enumerate(self.sinks)}

            report = build_report(
                cleaned,
                title=self.report_title,
                group_by=self.group_by,
                value_column=self.value_column,
                warnings=log.warnings,
            )
            artifacts.update(report.save(self.config.output_dir))

            result = PipelineResult(
                status="success",
                rows_in=rows_in,
                rows_out=rows_out,
                artifacts=artifacts,
                report=report,
                transform_log=log,
            )
            logger.info("✅ Pipeline succeeded — %s", log.summary())

        except (ExtractionError, DataQualityError, ValueError) as exc:
            logger.error("❌ Pipeline failed: %s", exc)
            result = PipelineResult(
                status="failed", rows_in=rows_in, rows_out=rows_out, error=str(exc)
            )
        except Exception as exc:  # noqa: BLE001 - unexpected failures must still be recorded
            logger.exception("💥 Pipeline crashed")
            result = PipelineResult(
                status="failed",
                rows_in=rows_in,
                rows_out=rows_out,
                error=f"{type(exc).__name__}: {exc}",
            )

        finished = datetime.now(timezone.utc)
        result.duration_seconds = (finished - started).total_seconds()
        history.record(
            started_at=started,
            finished_at=finished,
            status=result.status,
            rows_in=result.rows_in,
            rows_out=result.rows_out,
            error=result.error,
            details=result.artifacts,
        )
        return result


def configure_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
        stream=sys.stdout,
    )
