"""Tests for classification, field extraction and pipeline validation.

Everything runs on text fixtures, so no Tesseract binary or Poppler install is
needed to verify the logic.
"""

from datetime import date

import pytest

from src.classify import DocumentClassifier, DocumentType
from src.fields import extract_fields, parse_dates
from src.ocr import DocumentText, PageText
from src.pipeline import DocumentPipeline

INVOICE = """
ACME SUPPLIES LTD
Invoice Number: INV-2026-0481
Purchase Order: PO-77321
Date: 15/01/2026
Due Date: 14 February 2026

Bill To:
Northwind Trading
accounts@northwind.example.com
+44 20 7946 0958

Description            Qty    Unit Price     Amount
Widget assembly         10        120.00    1,200.00
Installation             1        300.00      300.00

Sub-total:                                  1,500.00
VAT @ 20%:                                    300.00
Total Amount Due:  GBP 1,800.00

Payment Terms: Net 30
VAT Number: GB 123 4567 89
IBAN: GB29NWBK60161331926819
"""

RECEIPT = """
QUICKMART STORE 42
Receipt
Transaction: 88213
Date: 2026-03-04
2 x Coffee            7.00
1 x Sandwich          4.50
Total:               11.50
Cash                 20.00
Change Due            8.50
Thank you for your purchase
"""

CONTRACT = """
SERVICE AGREEMENT

This Agreement is made on 1 April 2026 between Alpha Ltd and Beta LLC.
The parties hereby agree to the following terms and conditions.

1. Confidentiality
2. Indemnity and liability
3. Termination

Governing Law: this agreement shall be governed by the laws of England.
IN WITNESS WHEREOF the parties have executed this agreement.
"""

RESUME = """
Curriculum Vitae
Sara Ahmed
sara.ahmed@example.com | +92 300 1234567

Professional Summary
Machine learning engineer with six years of experience.

Work Experience
Senior ML Engineer, DataCorp, 2022-2026

Education
BSc Computer Science

Skills
Python, TensorFlow, SQL

References available on request.
"""


# ---------------------------------------------------------------- classification

@pytest.fixture(scope="module")
def classifier() -> DocumentClassifier:
    return DocumentClassifier()


@pytest.mark.parametrize(
    "text,expected",
    [
        (INVOICE, DocumentType.INVOICE),
        (RECEIPT, DocumentType.RECEIPT),
        (CONTRACT, DocumentType.CONTRACT),
        (RESUME, DocumentType.RESUME),
    ],
)
def test_documents_are_classified_correctly(classifier, text, expected):
    assert classifier.classify(text).document_type is expected


def test_unrecognisable_text_is_unknown_not_guessed(classifier):
    """Below the confidence floor the type must be `unknown`, not a best guess."""
    result = classifier.classify("qwerty zxcvbn asdfgh lorem ipsum foo bar baz")
    assert result.document_type is DocumentType.UNKNOWN


def test_empty_text_is_unknown(classifier):
    assert classifier.classify("").document_type is DocumentType.UNKNOWN
    assert classifier.classify("   ").confidence == 0.0


def test_classification_reports_its_evidence(classifier):
    result = classifier.classify(INVOICE)
    assert "invoice" in result.matched_keywords
    assert result.scores["invoice"] > result.scores["resume"]


def test_keyword_matching_respects_word_boundaries(classifier):
    """'tax' must not fire inside 'taxonomy'."""
    result = classifier.classify("A taxonomy of biological classification systems.")
    assert "tax" not in result.matched_keywords


# ------------------------------------------------------------- field extraction

def test_invoice_number_is_extracted():
    assert extract_fields(INVOICE).get("invoice_number") == "INV-2026-0481"


def test_purchase_order_is_extracted():
    assert extract_fields(INVOICE).get("purchase_order") == "PO-77321"


def test_amounts_are_extracted_with_thousands_separators():
    amounts = extract_fields(INVOICE).amounts
    assert amounts["subtotal"] == 1500.00
    assert amounts["tax"] == 300.00
    assert amounts["total"] == 1800.00


def test_subtotal_does_not_hijack_the_total():
    """Regression: "Sub-total" contains "total", and matched first without a boundary guard."""
    amounts = extract_fields(INVOICE).amounts
    assert amounts["total"] == 1800.00, "the grand total must win over the sub-total"


def test_totals_reconcile_when_the_arithmetic_holds():
    assert extract_fields(INVOICE).totals_reconcile is True


def test_totals_fail_to_reconcile_on_a_misread_digit():
    """The classic OCR failure: 1,800 read as 1,300. The check must catch it."""
    broken = INVOICE.replace("Total Amount Due:  GBP 1,800.00", "Total Amount Due:  GBP 1,300.00")
    assert extract_fields(broken).totals_reconcile is False


def test_reconciliation_is_none_without_enough_data():
    assert extract_fields("Total: 50.00").totals_reconcile is None


def test_email_and_phone_are_extracted():
    fields = extract_fields(INVOICE)
    assert "accounts@northwind.example.com" in fields.emails
    assert any("7946" in phone for phone in fields.phones)


def test_iban_and_vat_are_extracted():
    fields = extract_fields(INVOICE)
    assert fields.get("iban") == "GB29NWBK60161331926819"
    assert fields.get("vat_number") is not None


def test_currency_is_detected():
    assert extract_fields(INVOICE).get("currency") == "GBP"


def test_empty_text_yields_empty_fields():
    fields = extract_fields("")
    assert fields.as_dict()["emails"] == []
    assert fields.amounts == {}


# ------------------------------------------------------------------ date parsing

@pytest.mark.parametrize(
    "text,expected",
    [
        ("Date: 2026-01-15", date(2026, 1, 15)),
        ("Date: 15/01/2026", date(2026, 1, 15)),
        ("Date: 14 February 2026", date(2026, 2, 14)),
        ("Date: February 14, 2026", date(2026, 2, 14)),
        ("Date: 3 Mar 2026", date(2026, 3, 3)),
    ],
)
def test_date_formats_are_parsed(text, expected):
    assert expected in parse_dates(text)


def test_ambiguous_numeric_dates_are_read_day_first():
    """03/04/2026 is 3 April under UK/EU/PK convention, not 4 March."""
    assert date(2026, 4, 3) in parse_dates("Invoice date 03/04/2026")


def test_dates_are_deduplicated_and_sorted():
    dates = parse_dates("2026-01-15 and again 2026-01-15 plus 2026-01-10")
    assert dates == [date(2026, 1, 10), date(2026, 1, 15)]


def test_nonsense_dates_are_ignored():
    assert parse_dates("order 99/99/9999 reference") == []


# --------------------------------------------------------------------- pipeline

class FakeExtractor:
    """Returns canned text so the pipeline can be tested without OCR installed."""

    def __init__(self, text: str, ocr_pages: int = 0) -> None:
        self.text = text
        self.ocr_pages = ocr_pages

    def extract(self, path) -> DocumentText:
        source = "ocr" if self.ocr_pages else "text_layer"
        return DocumentText(str(path), [PageText(1, self.text, source)])


def test_pipeline_produces_a_complete_record():
    pipeline = DocumentPipeline(extractor=FakeExtractor(INVOICE))
    record = pipeline.process("invoice.pdf")

    assert record.classification.document_type is DocumentType.INVOICE
    assert record.fields.get("invoice_number") == "INV-2026-0481"
    assert record.needs_review is False
    assert record.quality_score == 1.0


def test_missing_expected_fields_route_to_review():
    """An invoice with no invoice number or total is not safe to ingest silently."""
    pipeline = DocumentPipeline(extractor=FakeExtractor("Invoice\nBill To: someone\nVAT"))
    record = pipeline.process("thin.pdf")

    assert record.needs_review is True
    assert any("missing" in issue for issue in record.issues)
    assert record.quality_score < 1.0


def test_failed_reconciliation_lowers_quality_and_flags_review():
    broken = INVOICE.replace("Total Amount Due:  GBP 1,800.00", "Total Amount Due:  GBP 1,300.00")
    record = DocumentPipeline(extractor=FakeExtractor(broken)).process("bad.pdf")

    assert record.needs_review is True
    assert any("misread digit" in issue for issue in record.issues)
    assert record.quality_score <= 0.7


def test_unreadable_scan_is_flagged():
    record = DocumentPipeline(extractor=FakeExtractor("xz")).process("blank.pdf")
    assert any("very little text" in issue for issue in record.issues)


def test_record_serialises_to_json_safe_dict():
    record = DocumentPipeline(extractor=FakeExtractor(RECEIPT)).process("receipt.pdf")
    data = record.as_dict()

    assert data["document_type"] == "receipt"
    assert isinstance(data["fields"]["dates"], list)
    assert all(isinstance(d, str) for d in data["fields"]["dates"])


def test_directory_processing_survives_one_bad_file(tmp_path):
    (tmp_path / "good.txt").write_text(RECEIPT, encoding="utf-8")
    (tmp_path / "ignored.zip").write_text("not a document", encoding="utf-8")

    from src.ocr import HybridExtractor

    pipeline = DocumentPipeline(extractor=HybridExtractor())
    records = pipeline.process_directory(tmp_path)

    assert len(records) == 1, "unsupported file types are skipped, not processed"
    assert records[0].classification.document_type is DocumentType.RECEIPT
