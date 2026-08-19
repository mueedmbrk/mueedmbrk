"""Scheduling and the CLI entrypoint.

Deliberately dependency-free. A pipeline that needs Airflow to run once a day is
harder to hand over than one that runs under cron or systemd — and this scheduler
exists mainly for environments where neither is available.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Callable

from .config import settings
from .extract import CSVSource, Source
from .load import CSVSink, RunHistory, SQLiteSink
from .pipeline import Pipeline, PipelineResult, configure_logging

logger = logging.getLogger(__name__)


class Scheduler:
    """Runs a callable on a fixed interval until interrupted."""

    def __init__(self, job: Callable[[], PipelineResult], interval_minutes: float = 60) -> None:
        # Fractional minutes are allowed so the loop can be exercised in tests
        # without a real wall-clock wait.
        if interval_minutes <= 0:
            raise ValueError("interval must be greater than zero")
        self.job = job
        self.interval = timedelta(minutes=interval_minutes)
        self._stop = False

    def request_stop(self, *_: object) -> None:
        """Finish the current run, then exit — never abandon a job mid-write."""
        logger.info("🛑 Stop requested; finishing the current run first.")
        self._stop = True

    def run_forever(self, max_runs: int | None = None) -> list[PipelineResult]:
        signal.signal(signal.SIGINT, self.request_stop)
        signal.signal(signal.SIGTERM, self.request_stop)

        results: list[PipelineResult] = []
        while not self._stop:
            logger.info("⏰ Starting scheduled run at %s", datetime.now(timezone.utc).isoformat())
            results.append(self.job())

            if max_runs is not None and len(results) >= max_runs:
                break
            if self._stop:
                break

            next_run = datetime.now(timezone.utc) + self.interval
            logger.info("😴 Next run at %s", next_run.strftime("%Y-%m-%d %H:%M UTC"))
            self._sleep_until(next_run)

        return results

    def _sleep_until(self, target: datetime) -> None:
        """Sleep in short slices so a stop signal is honoured promptly."""
        while not self._stop and datetime.now(timezone.utc) < target:
            remaining = (target - datetime.now(timezone.utc)).total_seconds()
            time.sleep(max(0.0, min(5.0, remaining)))


def build_pipeline(args: argparse.Namespace) -> Pipeline:
    sources: list[Source] = [CSVSource(path) for path in args.csv]

    sinks = [CSVSink(settings.output_dir, prefix="clean")]
    if args.sqlite_table:
        sinks.append(SQLiteSink(settings.state_db, args.sqlite_table))

    return Pipeline(
        sources=sources,
        sinks=sinks,
        date_columns=args.date_column,
        numeric_columns=args.numeric_column,
        deduplicate_on=args.dedupe_on or None,
        required_columns=args.require_column,
        group_by=args.group_by,
        value_column=args.value_column,
        report_title=args.title,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Automated data pipeline and reporting")
    parser.add_argument("--csv", action="append", default=[], help="CSV source (repeatable)")
    parser.add_argument("--date-column", action="append", default=[])
    parser.add_argument("--numeric-column", action="append", default=[])
    parser.add_argument("--dedupe-on", action="append", default=[])
    parser.add_argument("--require-column", action="append", default=[])
    parser.add_argument("--group-by")
    parser.add_argument("--value-column")
    parser.add_argument("--title", default="Automated Data Report")
    parser.add_argument("--every", type=int, help="Run on a schedule, every N minutes")
    parser.add_argument("--history", action="store_true", help="Show recent runs and exit")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    configure_logging(args.verbose)

    if args.history:
        runs = RunHistory(settings.state_db).recent()
        print(runs.to_string(index=False) if not runs.empty else "No runs recorded yet.")
        return 0

    if not args.csv:
        parser.error("at least one --csv source is required")

    pipeline = build_pipeline(args)

    if args.every:
        results = Scheduler(pipeline.run, interval_minutes=args.every).run_forever()
        return 0 if all(r.succeeded for r in results) else 1

    result = pipeline.run()
    if result.succeeded:
        print(f"\n✅ {result.transform_log.summary()}")
        for name, path in result.artifacts.items():
            print(f"   {name}: {path}")
        return 0

    print(f"\n❌ Pipeline failed: {result.error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
