<h1 align="center">📄 Document Intelligence System</h1>

<p align="center">
  <b>🔍 Turns unstructured scans and PDFs into structured, queryable records — and knows when not to trust itself</b>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/Tesseract-OCR-5B9BD5?logo=tesseract&logoColor=white" alt="Tesseract">
  <img src="https://img.shields.io/badge/scikit--learn-1.4-F7931E?logo=scikitlearn&logoColor=white" alt="scikit-learn">
  <img src="https://img.shields.io/badge/tests-33%20passing-brightgreen?logo=pytest&logoColor=white" alt="33 tests">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License">
</p>

---

## 📖 Overview

Document automation fails in a specific way: it extracts a number, gets one digit
wrong, and nobody finds out until the accounts do not balance three weeks later.

This pipeline is designed around that risk. It classifies each document, pulls out
structured fields, and then **checks its own work** — if subtotal plus tax does not
equal the total, the record is flagged for human review instead of flowing silently
into the system. Every extracted value carries the surrounding text it came from, so
a reviewer can see exactly why the pipeline believed what it believed.

## ✨ Features

- ⚡ **Text layer first, OCR only when needed** — an order-of-magnitude speedup on digital PDFs, with *better* accuracy
- 🏷️ **Six document types** — invoice, receipt, contract, resume, letter, report
- 🤝 **Two-signal classification** — keyword evidence plus TF-IDF similarity, so unusual phrasing still classifies
- 🤷 **Honest `unknown`** — below the confidence floor it declines to guess rather than misrouting a contract
- 🧾 **Rich field extraction** — invoice/PO numbers, totals, tax, VAT and IBAN, emails, phones, currency, dates
- 📅 **Multi-format date parsing** — ISO, slash, and written formats, with day-first disambiguation stated explicitly
- ✅ **Arithmetic self-check** — subtotal + tax vs total catches misread digits automatically
- 🔎 **Provenance on every field** — the surrounding text is kept for human review
- 📊 **Quality score per document** — weighted deductions drive an automatic review queue
- 🛡️ **Batch-safe** — one unreadable file becomes a flagged record, never an aborted 500-document run
- 🧪 **33 tests** that need no Tesseract install

## 🏗️ How It Works

```
📄 PDF / PNG / TIFF
        │
        ▼
┌─────────────────────────────────────────┐
│  Text acquisition  ⚡                    │
│  ┌───────────────────────────────────┐  │
│  │ Embedded text layer? ─── yes ──▶ use it (exact, instant)
│  │        │ no (< 120 chars)          │  │
│  │        ▼                           │  │
│  │ Rasterise page → Tesseract OCR     │  │
│  └───────────────────────────────────┘  │
└──────────────────┬──────────────────────┘
                   ▼
      ┌────────────────────────┐
      │  Classification  🏷️    │  keywords (65%) + TF-IDF similarity (35%)
      └────────────┬───────────┘
                   ▼
      ┌────────────────────────┐
      │  Field extraction  🧾  │  numbers, dates, parties, amounts + provenance
      └────────────┬───────────┘
                   ▼
      ┌────────────────────────┐
      │  Validation  ✅        │  expected fields · totals reconcile · text volume
      └────────────┬───────────┘
                   ▼
        📋 Record + quality score
        ✅ auto-ingest   ⚠️ human review
```

### ⚡ Why the text layer comes first

Most PDFs reaching a business — invoices from accounting software, contracts from
e-signature tools — already carry a **perfect embedded text layer**. Running OCR on
those is slower *and* strictly less accurate: it re-derives characters from a
rendering of text that was already exact.

So each page is checked for usable embedded text, and only genuinely scanned pages
are rasterised. Page-level, not document-level — a signed contract with one scanned
signature page gets OCR on that page alone.

### ✅ The arithmetic self-check

The single highest-value validation in the whole pipeline:

```python
@property
def totals_reconcile(self) -> bool | None:
    """Does subtotal + tax equal the total?"""
```

If OCR reads `1,800.00` as `1,300.00`, no regex notices — but the arithmetic stops
adding up, and the record is flagged. A 1% tolerance absorbs legitimate rounding
without hiding a misread digit. Returns `None` when there is not enough data to judge,
which is deliberately distinct from `False`.

## 🐛 A Bug Worth Documenting

The test suite contains this regression:

```python
def test_subtotal_does_not_hijack_the_total():
    """Regression: "Sub-total" contains "total", and matched first without a boundary guard."""
```

The total pattern matched the `total` **inside `Sub-total`**, so a £1,800 invoice was
recorded as £1,500 — a silently wrong number of exactly the kind this project exists
to prevent. A `(?<![\w-])` lookbehind fixed it. Notably, the reconciliation check had
already flagged the document as inconsistent before the root cause was found.

## 🚀 Quick Start

### 📦 System dependencies

OCR needs two native binaries (only for scanned documents):

```bash
# Ubuntu / Debian
sudo apt-get install tesseract-ocr poppler-utils

# macOS
brew install tesseract poppler
```

### 🐍 Install and run

```bash
git clone https://github.com/mueedmbrk/document-intelligence-system.git
cd document-intelligence-system

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

# One document
python -m src.pipeline invoice.pdf

# A whole folder, exported as JSON
python -m src.pipeline ./documents --json results.json
```

```
✅ invoice_0481.pdf                        invoice    quality 1.00
✅ receipt_march.pdf                       receipt    quality 1.00
⚠️  scan_blurry.pdf                        unknown    quality 0.40
     ↳ document type could not be determined
     ↳ missing total
⚠️  invoice_0482.pdf                       invoice    quality 0.70
     ↳ subtotal + tax does not equal total — check for a misread digit
```

### 🐍 As a library

```python
from src.pipeline import DocumentPipeline

pipeline = DocumentPipeline()
record = pipeline.process("invoice.pdf")

print(record.classification.document_type.value)   # "invoice"
print(record.fields.get("invoice_number"))         # "INV-2026-0481"
print(record.fields.amounts)                       # {'subtotal': 1500.0, 'tax': 300.0, 'total': 1800.0}
print(record.fields.totals_reconcile)              # True
print(record.quality_score, record.needs_review)   # 1.0 False

# Route the batch
for record in pipeline.process_directory("./inbox"):
    (review_queue if record.needs_review else ingest)(record.as_dict())
```

## 🧾 Extracted Fields

| Field | Example | Notes |
|---|---|---|
| `invoice_number` | `INV-2026-0481` | Handles `Invoice No.`, `Inv #`, `Bill Number` |
| `purchase_order` | `PO-77321` | `Purchase Order`, `P.O.`, `PO #` |
| `total` / `subtotal` / `tax` | `1800.00` | Thousands separators and currency symbols stripped |
| `currency` | `GBP` | Symbol or ISO code |
| `vat_number` | `GB 123 4567 89` | VAT / GST / tax registration |
| `iban` | `GB29NWBK60161331926819` | Bank details for payment automation |
| `emails` / `phones` | list | Phones length-filtered so invoice numbers do not match |
| `dates` | list of `date` | ISO, `15/01/2026`, `14 February 2026`, `February 14, 2026` |

📅 **On ambiguous dates:** `03/04/2026` is parsed **day-first** (3 April), matching UK,
European and Pakistani convention. This is explicit in the code rather than left to a
guessing parser — US-sourced documents need the fallback order flipped, and that
should be a visible decision.

## 📊 Quality Scoring

| Condition | Deduction |
|---|---|
| 🤷 Document type unknown | −0.40 |
| ❌ Totals do not reconcile | −0.30 |
| 🕳️ Each missing expected field | −0.10 |
| 📉 Under 50 characters extracted | −0.20 |

Weighted by how much each should worry a reviewer — an unrecognised document type is a
bigger problem than one absent field. Any issue at all sets `needs_review`.

## ⚙️ Configuration

| Variable | Default | Purpose |
|---|---|---|
| `TESSERACT_CMD` | — | Path to the binary if not on `PATH` |
| `OCR_LANGUAGE` | `eng` | Tesseract language pack |
| `OCR_DPI` | `300` | Rasterisation DPI — the accuracy/speed sweet spot |
| `MIN_TEXT_LAYER_CHARS` | `120` | Below this a page is treated as scanned |
| `CLASSIFIER_THRESHOLD` | `0.18` | Below this the type is reported as `unknown` |

## 🧪 Testing

```bash
pytest -v
```

33 tests across classification (including word-boundary handling), field extraction,
date parsing, reconciliation, quality scoring and batch resilience. Text extraction is
behind a protocol, so the suite runs on text fixtures with **no Tesseract or Poppler
install required**.

## 📁 Project Structure

```
document-intelligence-system/
├── src/
│   ├── config.py     ⚙️  Environment-backed settings
│   ├── ocr.py        ⚡  Text-layer-first acquisition with OCR fallback
│   ├── classify.py   🏷️  Keyword + TF-IDF document typing
│   ├── fields.py     🧾  Field patterns, date parsing, reconciliation
│   └── pipeline.py   🎛️  Orchestration, validation, quality scoring, CLI
├── tests/test_documents.py
├── .env.example
├── requirements.txt
└── README.md
```

## 🗺️ Roadmap

- [ ] 📐 Layout-aware extraction (LayoutLM / Donut) for complex tables
- [ ] 📊 Line-item table extraction, not just totals
- [ ] ✍️ Handwriting recognition for annotated forms
- [ ] 🌍 Multi-language OCR with automatic language detection
- [ ] 🖥️ Review UI for the flagged queue
- [ ] 🔄 Active learning from reviewer corrections

## 📄 License

Released under the [MIT License](LICENSE).

## 👤 Author

**Mueed Mubarak** — AI Automation Engineer · Machine Learning Developer

[![Portfolio](https://img.shields.io/badge/Portfolio-mueedmbrk.github.io-22d3ee)](https://mueedmbrk.github.io/mueedmbrk/)
[![LinkedIn](https://img.shields.io/badge/LinkedIn-mueed--mubarak-0A66C2?logo=linkedin&logoColor=white)](https://www.linkedin.com/in/mueed-mubarak/)
[![Email](https://img.shields.io/badge/Email-mueedmbrk%40gmail.com-EA4335?logo=gmail&logoColor=white)](mailto:mueedmbrk@gmail.com)

<p align="center">⭐ If this project is useful to you, a star is very welcome!</p>
