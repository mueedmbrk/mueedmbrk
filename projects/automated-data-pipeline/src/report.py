"""Insight generation and report rendering."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class Insight:
    """One finding worth putting in front of a person."""

    label: str
    value: str
    detail: str = ""


@dataclass
class Report:
    title: str
    generated_at: datetime
    row_count: int
    insights: list[Insight] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    table_preview: str = ""

    def to_markdown(self) -> str:
        lines = [
            f"# 📊 {self.title}",
            "",
            f"*Generated {self.generated_at.strftime('%Y-%m-%d %H:%M UTC')} · "
            f"{self.row_count:,} rows*",
            "",
            "## 🔑 Key figures",
            "",
            "| Metric | Value | Detail |",
            "|---|---|---|",
        ]
        for insight in self.insights:
            lines.append(f"| {insight.label} | **{insight.value}** | {insight.detail} |")

        if self.warnings:
            lines += ["", "## ⚠️ Warnings", ""]
            lines += [f"- {w}" for w in self.warnings]

        if self.table_preview:
            lines += ["", "## 🔍 Sample rows", "", "```", self.table_preview, "```"]

        return "\n".join(lines)

    def to_html(self) -> str:
        rows = "\n".join(
            f"<tr><td>{i.label}</td><td class='v'>{i.value}</td><td>{i.detail}</td></tr>"
            for i in self.insights
        )
        warnings = (
            "<h2>⚠️ Warnings</h2><ul>"
            + "".join(f"<li>{w}</li>" for w in self.warnings)
            + "</ul>"
            if self.warnings
            else ""
        )
        return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{self.title}</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 2rem auto;
         max-width: 820px; color: #1a1a1a; }}
  h1 {{ margin-bottom: .25rem; }}
  .meta {{ color: #666; font-size: .9rem; margin-bottom: 2rem; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ text-align: left; padding: .6rem .8rem; border-bottom: 1px solid #e5e5e5; }}
  th {{ background: #fafafa; }}
  .v {{ font-weight: 600; }}
</style></head>
<body>
  <h1>📊 {self.title}</h1>
  <p class="meta">Generated {self.generated_at.strftime('%Y-%m-%d %H:%M UTC')} ·
     {self.row_count:,} rows</p>
  <table><thead><tr><th>Metric</th><th>Value</th><th>Detail</th></tr></thead>
  <tbody>{rows}</tbody></table>
  {warnings}
</body></html>"""

    def save(self, directory: str | Path, basename: str = "report") -> dict[str, str]:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        stamp = self.generated_at.strftime("%Y%m%d_%H%M%S")

        paths = {}
        for suffix, content in (("md", self.to_markdown()), ("html", self.to_html())):
            path = directory / f"{basename}_{stamp}.{suffix}"
            path.write_text(content, encoding="utf-8")
            paths[suffix] = str(path)

        logger.info("📄 Report written: %s", paths["html"])
        return paths


def build_report(
    frame: pd.DataFrame,
    title: str = "Automated Data Report",
    group_by: str | None = None,
    value_column: str | None = None,
    warnings: list[str] | None = None,
) -> Report:
    """Derive headline figures from the cleaned dataset.

    Insights are computed defensively: a column that is absent or entirely null is
    skipped rather than raising, so a report still lands when one field is missing.
    A partial report tells you something; a crashed job at 6am tells you nothing.
    """
    report = Report(
        title=title,
        generated_at=datetime.now(timezone.utc),
        row_count=len(frame),
        warnings=list(warnings or []),
    )

    report.insights.append(Insight("Total records", f"{len(frame):,}"))
    report.insights.append(Insight("Columns", str(len(frame.columns))))

    if value_column and value_column in frame.columns:
        series = pd.to_numeric(frame[value_column], errors="coerce").dropna()
        if not series.empty:
            report.insights += [
                Insight(f"Total {value_column}", f"{series.sum():,.2f}"),
                Insight(f"Average {value_column}", f"{series.mean():,.2f}",
                        f"median {series.median():,.2f}"),
                Insight(f"Highest {value_column}", f"{series.max():,.2f}"),
            ]

    if group_by and group_by in frame.columns:
        counts = frame[group_by].value_counts()
        if not counts.empty:
            leader = counts.index[0]
            share = counts.iloc[0] / len(frame)
            report.insights.append(
                Insight(f"Top {group_by}", str(leader),
                        f"{counts.iloc[0]:,} rows ({share:.1%} of total)")
            )
            report.insights.append(
                Insight(f"Distinct {group_by}", f"{frame[group_by].nunique():,}")
            )

        if value_column and value_column in frame.columns:
            totals = (
                frame.assign(_v=pd.to_numeric(frame[value_column], errors="coerce"))
                .groupby(group_by)["_v"].sum().sort_values(ascending=False)
            )
            if not totals.empty and pd.notna(totals.iloc[0]):
                report.insights.append(
                    Insight(f"Best {group_by} by {value_column}",
                            str(totals.index[0]), f"{totals.iloc[0]:,.2f}")
                )

    # Flag columns that are mostly empty — usually an upstream schema change.
    for column in frame.columns:
        null_ratio = frame[column].isna().mean()
        if null_ratio > 0.5:
            report.warnings.append(f"Column '{column}' is {null_ratio:.0%} empty")

    if not frame.empty:
        report.table_preview = frame.head(5).to_string(index=False, max_colwidth=24)

    return report
