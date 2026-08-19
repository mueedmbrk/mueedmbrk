"""Transformation and data quality.

The transform stage is where a pipeline earns its keep — and where it most often
fails silently. A dropped column or a date that parsed as NaT does not raise; it
just produces a report with quietly wrong numbers. So every step here records what
it changed, and the quality gate can fail the run outright.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Iterable

import pandas as pd

logger = logging.getLogger(__name__)


class DataQualityError(RuntimeError):
    """Raised when data fails a gate that should stop the run."""


@dataclass
class TransformLog:
    """A record of what the transform stage actually did to the data."""

    rows_in: int = 0
    rows_out: int = 0
    duplicates_removed: int = 0
    columns_renamed: dict[str, str] = field(default_factory=dict)
    coerced_columns: dict[str, str] = field(default_factory=dict)
    null_ratios: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def rows_dropped(self) -> int:
        return self.rows_in - self.rows_out

    def summary(self) -> str:
        return (
            f"{self.rows_in} rows in → {self.rows_out} out "
            f"({self.rows_dropped} dropped, {self.duplicates_removed} duplicates)"
        )


def normalise_column_name(name: str) -> str:
    """`Total Sales (USD)` → `total_sales_usd`, so downstream code can rely on the shape."""
    cleaned = re.sub(r"[^\w\s]", " ", str(name))
    cleaned = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", cleaned)
    return re.sub(r"\s+", "_", cleaned.strip()).lower()


def clean(
    frame: pd.DataFrame,
    date_columns: Iterable[str] = (),
    numeric_columns: Iterable[str] = (),
    drop_duplicates_on: Iterable[str] | None = None,
) -> tuple[pd.DataFrame, TransformLog]:
    """Standardise names, coerce types, and drop duplicates — recording every change."""
    log = TransformLog(rows_in=len(frame))
    result = frame.copy()

    renames = {c: normalise_column_name(c) for c in result.columns}
    log.columns_renamed = {k: v for k, v in renames.items() if k != v}
    result = result.rename(columns=renames)

    for column in (normalise_column_name(c) for c in date_columns):
        if column in result.columns:
            before = result[column].notna().sum()
            result[column] = pd.to_datetime(result[column], errors="coerce", format="mixed")
            after = result[column].notna().sum()
            log.coerced_columns[column] = "datetime"
            # Silent NaT is the classic way a report ends up with a missing month.
            if after < before:
                log.warnings.append(
                    f"{before - after} value(s) in '{column}' could not be parsed as dates"
                )

    for column in (normalise_column_name(c) for c in numeric_columns):
        if column in result.columns:
            before = result[column].notna().sum()
            # Strip currency symbols and thousands separators before coercing.
            # Tested as "not already numeric" rather than "dtype is object": pandas
            # now backs string columns with a dedicated `str` dtype, and an
            # `== object` check silently skips them, nulling every value.
            if not pd.api.types.is_numeric_dtype(result[column]):
                result[column] = result[column].astype(str).str.replace(
                    r"[^\d.\-]", "", regex=True
                )
            result[column] = pd.to_numeric(result[column], errors="coerce")
            after = result[column].notna().sum()
            log.coerced_columns[column] = "numeric"
            if after < before:
                log.warnings.append(
                    f"{before - after} value(s) in '{column}' could not be parsed as numbers"
                )

    if drop_duplicates_on is not None:
        subset = [normalise_column_name(c) for c in drop_duplicates_on] or None
        subset = [c for c in (subset or []) if c in result.columns] or None
        before = len(result)
        result = result.drop_duplicates(subset=subset, keep="last")
        log.duplicates_removed = before - len(result)

    result = result.reset_index(drop=True)
    log.rows_out = len(result)
    log.null_ratios = {
        column: round(float(result[column].isna().mean()), 4) for column in result.columns
    }

    logger.info("🧹 %s", log.summary())
    for warning in log.warnings:
        logger.warning("⚠️  %s", warning)

    return result, log


def check_quality(
    frame: pd.DataFrame,
    log: TransformLog,
    max_null_ratio: float = 0.20,
    min_rows: int = 1,
    required_columns: Iterable[str] = (),
) -> list[str]:
    """Run the quality gates. Raises ``DataQualityError`` when the run should not ship.

    Failing loudly is the whole point. A report built on data that lost half its
    rows is worse than no report — a missing email gets noticed, a wrong number
    gets acted on.
    """
    failures: list[str] = []

    if len(frame) < min_rows:
        failures.append(f"row count {len(frame)} is below the minimum of {min_rows}")

    missing = [c for c in (normalise_column_name(c) for c in required_columns)
               if c not in frame.columns]
    if missing:
        failures.append(f"required columns missing: {missing}")

    for column, ratio in log.null_ratios.items():
        if ratio > max_null_ratio:
            failures.append(
                f"column '{column}' is {ratio:.1%} null, above the {max_null_ratio:.0%} limit"
            )

    if failures:
        raise DataQualityError("; ".join(failures))

    return failures
