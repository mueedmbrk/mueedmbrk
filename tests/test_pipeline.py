"""Tests for transformation, quality gates, reporting and orchestration."""

import pandas as pd
import pytest

from src.config import Settings
from src.extract import CSVSource, ExtractionError, extract_all
from src.load import CSVSink, RunHistory, SQLiteSink
from src.pipeline import Pipeline
from src.report import build_report
from src.scheduler import Scheduler
from src.transform import (
    DataQualityError,
    check_quality,
    clean,
    normalise_column_name,
)


@pytest.fixture
def messy_csv(tmp_path):
    path = tmp_path / "sales.csv"
    path.write_text(
        "Order ID,Customer Name,Total Sales (USD),Order Date,Region\n"
        "1,Alice,$1200.50,2026-01-15,North\n"
        "2,Bob,\"$2,300.00\",2026-01-16,South\n"
        "3,Carol,$850.25,2026-01-17,North\n"
        "3,Carol,$850.25,2026-01-17,North\n"
        "4,Dan,$4100.00,not-a-date,East\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def config(tmp_path) -> Settings:
    return Settings(
        output_dir=tmp_path / "out",
        state_db=tmp_path / "out" / "pipeline.db",
        max_null_ratio=0.30,
        min_rows=1,
    )


# ------------------------------------------------------------------ naming

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Total Sales (USD)", "total_sales_usd"),
        ("Order ID", "order_id"),
        ("  spaced  out  ", "spaced_out"),
        ("customerName", "customer_name"),
        ("already_clean", "already_clean"),
    ],
)
def test_column_names_are_normalised(raw, expected):
    assert normalise_column_name(raw) == expected


# --------------------------------------------------------------- transform

def test_clean_coerces_currency_and_dates(messy_csv):
    frame = CSVSource(messy_csv).extract()
    result, log = clean(
        frame,
        date_columns=["Order Date"],
        numeric_columns=["Total Sales (USD)"],
        drop_duplicates_on=["Order ID"],
    )

    assert "total_sales_usd" in result.columns
    assert result["total_sales_usd"].sum() == pytest.approx(1200.50 + 2300.00 + 850.25 + 4100.00)
    assert pd.api.types.is_datetime64_any_dtype(result["order_date"])


def test_duplicates_are_removed_and_counted(messy_csv):
    frame = CSVSource(messy_csv).extract()
    _, log = clean(frame, drop_duplicates_on=["Order ID"])
    assert log.duplicates_removed == 1
    assert log.rows_out == 4


def test_unparseable_dates_are_warned_not_swallowed(messy_csv):
    """A date that silently becomes NaT is how a report loses a whole month."""
    frame = CSVSource(messy_csv).extract()
    _, log = clean(frame, date_columns=["Order Date"])
    assert any("could not be parsed as dates" in w for w in log.warnings)


def test_transform_log_reports_rows_dropped(messy_csv):
    frame = CSVSource(messy_csv).extract()
    _, log = clean(frame, drop_duplicates_on=["Order ID"])
    assert log.rows_in == 5 and log.rows_out == 4
    assert log.rows_dropped == 1
    assert "5 rows in → 4 out" in log.summary()


# ----------------------------------------------------------- quality gates

def test_quality_gate_passes_clean_data(messy_csv):
    frame = CSVSource(messy_csv).extract()
    result, log = clean(frame, numeric_columns=["Total Sales (USD)"])
    assert check_quality(result, log, max_null_ratio=0.5, min_rows=1) == []


def test_quality_gate_rejects_too_few_rows():
    frame = pd.DataFrame({"a": [1]})
    _, log = clean(frame)
    with pytest.raises(DataQualityError, match="below the minimum"):
        check_quality(frame, log, min_rows=10)


def test_quality_gate_rejects_missing_required_column():
    frame = pd.DataFrame({"a": [1, 2]})
    _, log = clean(frame)
    with pytest.raises(DataQualityError, match="required columns missing"):
        check_quality(frame, log, required_columns=["revenue"])


def test_quality_gate_rejects_excess_nulls():
    frame = pd.DataFrame({"a": [1, None, None, None]})
    _, log = clean(frame)
    with pytest.raises(DataQualityError, match="null"):
        check_quality(frame, log, max_null_ratio=0.10)


# --------------------------------------------------------------- reporting

def test_report_contains_headline_figures():
    frame = pd.DataFrame(
        {"region": ["North", "South", "North"], "revenue": [100.0, 250.0, 150.0]}
    )
    report = build_report(frame, group_by="region", value_column="revenue")
    labels = {i.label: i.value for i in report.insights}

    assert labels["Total records"] == "3"
    assert labels["Total revenue"] == "500.00"
    assert labels["Top region"] == "North"


def test_report_survives_a_missing_value_column():
    """A partial report is more useful than a crashed 6am job."""
    frame = pd.DataFrame({"region": ["North", "South"]})
    report = build_report(frame, group_by="region", value_column="absent_column")
    assert report.row_count == 2


def test_report_flags_mostly_empty_columns():
    frame = pd.DataFrame({"a": [1, 2, 3, 4], "b": [None, None, None, 1]})
    report = build_report(frame)
    assert any("'b' is 75% empty" in w for w in report.warnings)


def test_report_renders_both_formats(tmp_path):
    frame = pd.DataFrame({"region": ["North"], "revenue": [10.0]})
    report = build_report(frame, group_by="region", value_column="revenue")

    assert "# 📊" in report.to_markdown()
    assert "<!doctype html>" in report.to_html()

    paths = report.save(tmp_path)
    assert set(paths) == {"md", "html"}


# ------------------------------------------------------------ orchestration

def test_full_pipeline_run_succeeds(messy_csv, config):
    pipeline = Pipeline(
        sources=[CSVSource(messy_csv)],
        sinks=[CSVSink(config.output_dir, prefix="clean")],
        date_columns=["Order Date"],
        numeric_columns=["Total Sales (USD)"],
        deduplicate_on=["Order ID"],
        group_by="region",
        value_column="total_sales_usd",
        config=config,
    )
    result = pipeline.run()

    assert result.succeeded, result.error
    assert result.rows_in == 5 and result.rows_out == 4
    assert "html" in result.artifacts


def test_pipeline_records_failure_instead_of_crashing(tmp_path, config):
    """A failed scheduled run must leave a diagnosable trace, not just a stack trace."""
    pipeline = Pipeline(sources=[CSVSource(tmp_path / "missing.csv")], config=config)
    result = pipeline.run()

    assert result.succeeded is False
    assert "not found" in result.error

    history = RunHistory(config.state_db).recent()
    assert history.iloc[0]["status"] == "failed"


def test_quality_failure_stops_the_run(messy_csv, config):
    pipeline = Pipeline(
        sources=[CSVSource(messy_csv)],
        required_columns=["nonexistent_column"],
        config=config,
    )
    result = pipeline.run()
    assert result.succeeded is False
    assert "required columns missing" in result.error


def test_run_history_accumulates(messy_csv, config):
    pipeline = Pipeline(sources=[CSVSource(messy_csv)], config=config)
    pipeline.run()
    pipeline.run()
    assert len(RunHistory(config.state_db).recent()) == 2


def test_extract_all_tags_the_source(messy_csv):
    frame = extract_all([CSVSource(messy_csv)])
    assert set(frame["_source"]) == {"CSVSource"}


def test_extract_all_requires_a_source():
    with pytest.raises(ValueError):
        extract_all([])


def test_missing_csv_raises_extraction_error(tmp_path):
    with pytest.raises(ExtractionError):
        CSVSource(tmp_path / "nope.csv").extract()


def test_sqlite_sink_is_idempotent(tmp_path):
    frame = pd.DataFrame({"a": [1, 2, 3]})
    sink = SQLiteSink(tmp_path / "db.sqlite", "records", if_exists="replace")
    sink.load(frame)
    sink.load(frame)

    import sqlite3

    with sqlite3.connect(tmp_path / "db.sqlite") as connection:
        count = connection.execute("SELECT COUNT(*) FROM records").fetchone()[0]
    assert count == 3, "re-running must not duplicate rows"


# --------------------------------------------------------------- scheduling

def test_scheduler_runs_the_configured_number_of_times():
    calls = []

    def job():
        calls.append(1)
        from src.pipeline import PipelineResult

        return PipelineResult(status="success")

    Scheduler(job, interval_minutes=0.001).run_forever(max_runs=2)
    assert len(calls) == 2


def test_scheduler_rejects_a_non_positive_interval():
    with pytest.raises(ValueError):
        Scheduler(lambda: None, interval_minutes=0)


def test_currency_strings_survive_the_string_dtype_backend():
    """Regression: a `dtype == object` check misses pandas' `str`-backed columns."""
    frame = pd.DataFrame({"amount": ["$1,200.50", "$850.25"]})
    result, _ = clean(frame, numeric_columns=["amount"])
    assert result["amount"].sum() == pytest.approx(2050.75)
