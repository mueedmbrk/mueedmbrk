<h1 align="center">📊 Automated Data Pipeline & Reporting</h1>

<p align="center">
  <b>⚙️ Scheduled ETL with real quality gates — reports that arrive without anyone touching a spreadsheet</b>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/pandas-3.0-150458?logo=pandas&logoColor=white" alt="pandas">
  <img src="https://img.shields.io/badge/SQLite-state-003B57?logo=sqlite&logoColor=white" alt="SQLite">
  <img src="https://img.shields.io/badge/tests-28%20passing-brightgreen?logo=pytest&logoColor=white" alt="28 tests">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License">
</p>

---

## 📖 Overview

The dangerous failure mode for a reporting pipeline is not crashing. It is
**succeeding with wrong numbers** — a column that silently coerced to null, a date
that became `NaT`, an upstream schema change that dropped half the rows. Nobody
notices, and decisions get made on the output.

This pipeline is built around that problem. Every transformation records what it
changed, quality gates fail the run rather than shipping a bad report, and every
run — successful or not — is written to a history table you can inspect the next
morning without re-running anything.

## ✨ Features

- 🔌 **Pluggable sources** — CSV, REST API and SQL, all returning the same shape
- 🔁 **Retries that discriminate** — transient 5xx/429 retried with backoff; a 401 or 404 fails immediately
- 🧹 **Recorded transformations** — every rename, coercion and dropped row is logged, not silent
- 🚦 **Quality gates that stop the run** — row-count floors, required columns and per-column null ceilings
- ⚠️ **Coercion warnings** — values that failed to parse as dates or numbers are surfaced, never swallowed
- 🔄 **Idempotent loads** — re-running a day does not duplicate rows
- 🗂️ **Run history in SQLite** — status, duration, row counts and the failure reason for every run
- 📄 **Markdown + HTML reports** — headline figures, group leaders and data warnings
- ⏰ **Dependency-free scheduler** — runs under cron, systemd or its own loop, with graceful shutdown
- 🧪 **28 unit tests** including a pandas 3.0 dtype regression

## 🏗️ Pipeline Stages

```
┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌───────────┐   ┌──────────┐
│  EXTRACT  📥 │──▶│ TRANSFORM 🧹 │──▶│ VALIDATE  🚦 │──▶│  LOAD  💾 │──▶│ REPORT 📄│
└──────────────┘   └──────────────┘   └──────────────┘   └───────────┘   └──────────┘
   CSV / API           normalise          row floors        CSV file       Markdown
   / SQL               coerce types       required cols     SQLite         HTML
   + retries           dedupe             null ceilings     idempotent     insights
   + source tag        + change log       ❌ fails the run                 + warnings
                                                │
                                                ▼
                                    🗂️ Run recorded either way
```

**Validation sits before load, not after.** A bad dataset never reaches the sink or
the report — but the run is still recorded, with the reason, so the failure is
diagnosable in the morning.

## 🚦 Quality Gates

| Gate | Config | Fails when |
|---|---|---|
| 📉 Row floor | `MIN_ROWS` | The run produced fewer rows than expected — usually a broken upstream |
| 🧱 Required columns | `required_columns` | A column the report depends on is absent |
| 🕳️ Null ceiling | `MAX_NULL_RATIO` | Any column exceeds the tolerated null ratio |

A breach raises `DataQualityError` and the run is marked failed. This is deliberate:
**a report built on half the data is worse than no report.** A missing email gets
noticed; a wrong number gets acted on.

## 🐛 A Bug Worth Documenting

The test suite contains this regression:

```python
def test_currency_strings_survive_the_string_dtype_backend():
    """Regression: a `dtype == object` check misses pandas' `str`-backed columns."""
```

pandas 3.0 backs string columns with a dedicated `str` dtype. The idiomatic
`if column.dtype == object` guard — used everywhere to detect text columns — is now
`False` for them. The currency-stripping step was skipped, `pd.to_numeric("$1,200.50")`
returned `NaN`, and **every revenue value silently became null**.

The quality gate caught it (`100% null, above the 30% limit`), which is exactly the
job it exists to do. The fix tests `not is_numeric_dtype(...)` instead, which is
agnostic to the dtype backend.

## 🚀 Quick Start

```bash
# 1️⃣ Clone and enter
git clone https://github.com/mueedmbrk/automated-data-pipeline.git
cd automated-data-pipeline

# 2️⃣ Environment and dependencies
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 3️⃣ Configure
cp .env.example .env

# 4️⃣ Run against the bundled sample
python -m src.scheduler \
  --csv examples/sample_sales.csv \
  --numeric-column "Total Sales (USD)" \
  --date-column "Order Date" \
  --dedupe-on "Order ID" \
  --group-by region \
  --value-column total_sales_usd \
  --title "Weekly Sales Report"
```

```
🧹 11 rows in → 10 out (1 dropped, 1 duplicates)
💾 Wrote 10 rows to outputs/clean_20260819_143022.csv
📄 Report written: outputs/report_20260819_143022.html
✅ 11 rows in → 10 out (1 dropped, 1 duplicates)
```

### ⏰ Scheduling

```bash
python -m src.scheduler --csv data.csv --every 60     # every hour, in-process
python -m src.scheduler --history                     # inspect recent runs
```

Or hand it to cron and skip the built-in loop entirely:

```cron
0 6 * * *  cd /srv/pipeline && .venv/bin/python -m src.scheduler --csv data.csv
```

The in-process scheduler handles `SIGINT`/`SIGTERM` by **finishing the current run
before exiting**, so a deploy never leaves a half-written output.

### 🐍 As a library

```python
from src.extract import APISource, CSVSource
from src.load import CSVSink, SQLiteSink
from src.pipeline import Pipeline

pipeline = Pipeline(
    sources=[
        CSVSource("data/orders.csv"),
        APISource("https://api.example.com/v1/orders", token="...", records_path="data.items"),
    ],
    sinks=[CSVSink("outputs"), SQLiteSink("warehouse.db", "orders")],
    numeric_columns=["Total Sales (USD)"],
    date_columns=["Order Date"],
    deduplicate_on=["Order ID"],
    required_columns=["region", "total_sales_usd"],
    group_by="region",
    value_column="total_sales_usd",
)

result = pipeline.run()
print(result.status, result.rows_out, result.artifacts)
```

## ⚙️ Configuration

| Variable | Default | Purpose |
|---|---|---|
| `OUTPUT_DIR` | `outputs` | Where CSVs and reports are written |
| `STATE_DB` | `outputs/pipeline.db` | Run history and SQLite sink |
| `API_BASE_URL` / `API_TOKEN` | — | REST source credentials |
| `REQUEST_TIMEOUT` | `30` | Per-request timeout in seconds |
| `MAX_RETRIES` | `3` | Attempts for retryable API failures |
| `MAX_NULL_RATIO` | `0.20` | Per-column null tolerance |
| `MIN_ROWS` | `1` | Minimum rows for a run to be considered valid |

## 🗂️ Run History

Every run lands in `pipeline_runs`:

| Column | Meaning |
|---|---|
| `status` | `success` or `failed` |
| `rows_in` / `rows_out` | Volume before and after transformation |
| `duration_s` | Wall-clock seconds |
| `error` | Why it failed, when it did |
| `details` | JSON of the artifacts produced |

```bash
python -m src.scheduler --history
```

## 🧪 Testing

```bash
pytest -v
```

28 tests covering column normalisation, currency and date coercion, deduplication,
every quality gate, report rendering, idempotent loading, failure recording and the
scheduler loop. The full suite runs in well under a second — no network, no sleeping.

## 📁 Project Structure

```
automated-data-pipeline/
├── src/
│   ├── config.py      ⚙️  Environment-backed settings
│   ├── extract.py     📥  CSV / API / SQL sources with retry policy
│   ├── transform.py   🧹  Cleaning, coercion and the quality gates
│   ├── load.py        💾  CSV / SQLite sinks and run history
│   ├── report.py      📄  Insight generation, Markdown + HTML rendering
│   ├── pipeline.py    🎛️  Stage orchestration and failure capture
│   └── scheduler.py   ⏰  Scheduling loop and CLI
├── examples/sample_sales.csv
├── tests/test_pipeline.py
├── .env.example
├── requirements.txt
└── README.md
```

## 🗺️ Roadmap

- [ ] 📧 Email delivery of the rendered report
- [ ] 📈 Trend charts embedded in the HTML output
- [ ] 🔀 Incremental extraction via watermark columns
- [ ] 🧭 Great Expectations integration for richer assertions
- [ ] ☁️ S3 / GCS sinks
- [ ] 🔔 Slack alert on a failed run

## 📄 License

Released under the [MIT License](LICENSE).

## 👤 Author

**Mueed Mubarak** — AI Automation Engineer · Data Engineering

[![Portfolio](https://img.shields.io/badge/Portfolio-mueedmbrk.github.io-22d3ee)](https://mueedmbrk.github.io/mueedmbrk/)
[![LinkedIn](https://img.shields.io/badge/LinkedIn-mueed--mubarak-0A66C2?logo=linkedin&logoColor=white)](https://www.linkedin.com/in/mueed-mubarak/)
[![Email](https://img.shields.io/badge/Email-mueedmbrk%40gmail.com-EA4335?logo=gmail&logoColor=white)](mailto:mueedmbrk@gmail.com)

<p align="center">⭐ If this project is useful to you, a star is very welcome!</p>
