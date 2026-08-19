"""Structured field extraction.

Turning a wall of OCR text into queryable records. Every extractor returns the
matched value *and* the span it came from, so a human reviewing a low-confidence
record can see exactly which words produced it — the difference between a system
people trust and one they quietly stop using.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field as dataclass_field
from datetime import date, datetime

# Currency amounts, with or without a symbol and thousands separators.
AMOUNT = r"[-+]?\d{1,3}(?:[,\s]\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?"

PATTERNS: dict[str, re.Pattern] = {
    "invoice_number": re.compile(
        r"(?:invoice|inv|bill)\s*(?:number|no\.?|#|num)?\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-/]{2,20})",
        re.IGNORECASE,
    ),
    "purchase_order": re.compile(
        r"(?:purchase\s+order|p\.?o\.?)\s*(?:number|no\.?|#)?\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-/]{2,20})",
        re.IGNORECASE,
    ),
    "email": re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    "phone": re.compile(r"(?:\+?\d[\d\s().-]{7,}\d)"),
    "vat_number": re.compile(r"(?:vat|gst|tax)\s*(?:reg(?:istration)?)?\s*(?:no\.?|number|#)?\s*[:\-]?\s*([A-Z]{0,3}\s?\d[\d\s-]{5,15})", re.IGNORECASE),
    "iban": re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b"),
}

# The lookbehind is load-bearing: without it "Sub-total: 1,500.00" matches on the
# "total" inside "Sub-total" and the grand total is read as the subtotal.
TOTAL_PATTERN = re.compile(
    rf"(?<![\w-])(?:total\s*(?:amount)?\s*(?:due)?|amount\s+due|balance\s+due|grand\s+total)"
    rf"\s*[:\-]?\s*(?:[$£€]|USD|EUR|GBP|PKR|Rs\.?)?\s*({AMOUNT})",
    re.IGNORECASE,
)

SUBTOTAL_PATTERN = re.compile(
    rf"(?<![\w-])(?:sub\s*-?\s*total|net\s+amount)\s*[:\-]?\s*(?:[$£€]|USD|EUR|GBP|PKR|Rs\.?)?\s*({AMOUNT})",
    re.IGNORECASE,
)

TAX_PATTERN = re.compile(
    rf"(?<![\w-])(?:vat|tax|gst)(?!\w)\s*(?:@\s*\d+(?:\.\d+)?\s*%)?\s*[:\-]?\s*(?:[$£€]|USD|EUR|GBP|PKR|Rs\.?)?\s*({AMOUNT})",
    re.IGNORECASE,
)

CURRENCY_PATTERN = re.compile(r"\b(USD|EUR|GBP|PKR|AED|INR)\b|([$£€])")

DATE_PATTERNS: tuple[tuple[re.Pattern, tuple[str, ...]], ...] = (
    (re.compile(r"\b(\d{4}-\d{2}-\d{2})\b"), ("%Y-%m-%d",)),
    (re.compile(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{4})\b"), ("%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%m-%d-%Y")),
    (re.compile(r"\b(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})\b"), ("%d %B %Y", "%d %b %Y")),
    (re.compile(r"\b([A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4})\b"), ("%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y")),
)


@dataclass
class Field:
    """One extracted value and the text it came from."""

    name: str
    value: str
    context: str = ""

    def __str__(self) -> str:
        return self.value


@dataclass
class ExtractedFields:
    """Everything pulled from one document."""

    fields: dict[str, Field] = dataclass_field(default_factory=dict)
    emails: list[str] = dataclass_field(default_factory=list)
    phones: list[str] = dataclass_field(default_factory=list)
    dates: list[date] = dataclass_field(default_factory=list)
    amounts: dict[str, float] = dataclass_field(default_factory=dict)

    def get(self, name: str) -> str | None:
        found = self.fields.get(name)
        return found.value if found else None

    def as_dict(self) -> dict:
        return {
            **{name: f.value for name, f in self.fields.items()},
            "emails": self.emails,
            "phones": self.phones,
            "dates": [d.isoformat() for d in self.dates],
            **self.amounts,
        }

    @property
    def totals_reconcile(self) -> bool | None:
        """Does subtotal + tax equal the total?

        A cheap, high-value integrity check on OCR output: if the three numbers do
        not add up, a digit was almost certainly misread and the record needs a
        human. Returns ``None`` when there is not enough data to judge.
        """
        subtotal = self.amounts.get("subtotal")
        tax = self.amounts.get("tax")
        total = self.amounts.get("total")

        if subtotal is None or tax is None or total is None:
            return None
        # A 1% tolerance absorbs legitimate rounding without hiding a misread digit.
        return abs((subtotal + tax) - total) <= max(0.01, total * 0.01)


def _to_float(raw: str) -> float | None:
    cleaned = re.sub(r"[^\d.\-]", "", raw.replace(",", ""))
    try:
        return float(cleaned)
    except ValueError:
        return None


def _context(text: str, match: re.Match, window: int = 40) -> str:
    start = max(0, match.start() - window)
    end = min(len(text), match.end() + window)
    return " ".join(text[start:end].split())


def parse_dates(text: str) -> list[date]:
    """Find dates in any of the common written formats, de-duplicated and sorted.

    Ambiguous numeric dates (``03/04/2026``) are parsed day-first, matching UK,
    European and Pakistani convention. Documents from US sources need this flipped —
    which is exactly why the fallback order is explicit here rather than left to a
    guessing parser.
    """
    found: set[date] = set()

    for pattern, formats in DATE_PATTERNS:
        for match in pattern.finditer(text):
            raw = match.group(1).strip()
            for fmt in formats:
                try:
                    found.add(datetime.strptime(raw, fmt).date())
                    break
                except ValueError:
                    continue

    return sorted(found)


def extract_fields(text: str) -> ExtractedFields:
    """Pull every recognised field out of the document text."""
    result = ExtractedFields()
    if not text:
        return result

    for name, pattern in PATTERNS.items():
        if name in {"email", "phone"}:
            continue
        match = pattern.search(text)
        if match:
            value = (match.group(1) if match.groups() else match.group(0)).strip()
            result.fields[name] = Field(name, re.sub(r"\s+", " ", value), _context(text, match))

    result.emails = sorted(set(PATTERNS["email"].findall(text)))

    phones = []
    for match in PATTERNS["phone"].finditer(text):
        candidate = match.group(0).strip()
        digits = re.sub(r"\D", "", candidate)
        # Filter out invoice numbers and dates that look superficially like phones.
        if 9 <= len(digits) <= 15:
            phones.append(candidate)
    result.phones = sorted(set(phones))

    result.dates = parse_dates(text)

    for key, pattern in (
        ("total", TOTAL_PATTERN),
        ("subtotal", SUBTOTAL_PATTERN),
        ("tax", TAX_PATTERN),
    ):
        match = pattern.search(text)
        if match:
            value = _to_float(match.group(1))
            if value is not None:
                result.amounts[key] = value

    currency = CURRENCY_PATTERN.search(text)
    if currency:
        result.fields["currency"] = Field(
            "currency", currency.group(1) or currency.group(2), _context(text, currency)
        )

    return result
