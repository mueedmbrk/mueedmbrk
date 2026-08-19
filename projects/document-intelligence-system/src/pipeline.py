"""Orchestration: document in, structured record out."""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .classify import Classification, DocumentClassifier, DocumentType
from .config import Settings, settings as default_settings
from .fields import ExtractedFields, extract_fields
from .ocr import DocumentText, ExtractionBackendError, HybridExtractor, TextExtractor

logger = logging.getLogger(__name__)

SUPPORTED_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".txt", ".md"}

# Fields we expect to find, per document type. Absence lowers the quality score
# and routes the record to review rather than into the system silently.
EXPECTED_FIELDS: dict[DocumentType, tuple[str, ...]] = {
    DocumentType.INVOICE: ("invoice_number", "total", "dates"),
    DocumentType.RECEIPT: ("total", "dates"),
    DocumentType.CONTRACT: ("dates",),
    DocumentType.RESUME: ("emails",),
    DocumentType.LETTER: ("dates",),
    DocumentType.REPORT: (),
    DocumentType.UNKNOWN: (),
}


@dataclass
class DocumentRecord:
    """One processed document: what it is, what is in it, and whether to trust it."""

    path: str
    classification: Classification
    fields: ExtractedFields
    page_count: int = 0
    ocr_pages: int = 0
    character_count: int = 0
    issues: list[str] = field(default_factory=list)

    @property
    def needs_review(self) -> bool:
        return bool(self.issues)

    @property
    def quality_score(self) -> float:
        """A 0-1 confidence in the whole record, not just the classification.

        Deductions are weighted by how much they should worry a reviewer: an
        unrecognised document type is a bigger problem than one missing field.
        """
        score = 1.0
        if self.classification.document_type is DocumentType.UNKNOWN:
            score -= 0.40
        if self.fields.totals_reconcile is False:
            score -= 0.30
        score -= 0.10 * len([i for i in self.issues if i.startswith("missing")])
        if self.character_count < 50:
            score -= 0.20
        return round(max(0.0, min(1.0, score)), 3)

    def as_dict(self) -> dict:
        return {
            "path": self.path,
            "document_type": self.classification.document_type.value,
            "type_confidence": self.classification.confidence,
            "page_count": self.page_count,
            "ocr_pages": self.ocr_pages,
            "character_count": self.character_count,
            "fields": self.fields.as_dict(),
            "totals_reconcile": self.fields.totals_reconcile,
            "quality_score": self.quality_score,
            "needs_review": self.needs_review,
            "issues": self.issues,
        }


class DocumentPipeline:
    """Extract text → classify → pull fields → validate."""

    def __init__(
        self,
        extractor: TextExtractor | None = None,
        classifier: DocumentClassifier | None = None,
        config: Settings | None = None,
    ) -> None:
        self.config = config or default_settings
        self.extractor = extractor or HybridExtractor(
            min_text_layer_chars=self.config.min_text_layer_chars,
            language=self.config.ocr_language,
            dpi=self.config.ocr_dpi,
            tesseract_cmd=self.config.tesseract_cmd,
        )
        self.classifier = classifier or DocumentClassifier(
            threshold=self.config.classifier_threshold
        )

    def process(self, path: str | Path) -> DocumentRecord:
        document: DocumentText = self.extractor.extract(path)
        return self.process_text(document.text, str(path), document)

    def process_text(
        self, text: str, path: str = "<memory>", document: DocumentText | None = None
    ) -> DocumentRecord:
        """Classify and extract from text that has already been obtained."""
        classification = self.classifier.classify(text)
        fields = extract_fields(text)

        record = DocumentRecord(
            path=path,
            classification=classification,
            fields=fields,
            page_count=document.page_count if document else 1,
            ocr_pages=document.ocr_page_count if document else 0,
            character_count=len(text.strip()),
        )
        record.issues = self._validate(record)
        return record

    def _validate(self, record: DocumentRecord) -> list[str]:
        issues: list[str] = []
        data = record.fields.as_dict()

        for name in EXPECTED_FIELDS.get(record.classification.document_type, ()):
            value = data.get(name)
            if not value:
                issues.append(f"missing {name}")

        if record.classification.document_type is DocumentType.UNKNOWN:
            issues.append("document type could not be determined")

        if record.fields.totals_reconcile is False:
            issues.append("subtotal + tax does not equal total — check for a misread digit")

        if record.character_count < 50:
            issues.append("very little text extracted — the scan may be unreadable")

        return issues

    def process_directory(self, directory: str | Path) -> list[DocumentRecord]:
        """Process every supported document in a folder.

        One unreadable file must not abort a 500-document batch, so failures become
        records flagged for review instead of exceptions.
        """
        directory = Path(directory)
        records: list[DocumentRecord] = []

        for path in sorted(directory.iterdir()):
            if not path.is_file() or path.suffix.lower() not in SUPPORTED_SUFFIXES:
                continue
            try:
                records.append(self.process(path))
            except (ExtractionBackendError, OSError) as exc:
                logger.error("❌ %s: %s", path.name, exc)
                records.append(
                    DocumentRecord(
                        path=str(path),
                        classification=Classification(DocumentType.UNKNOWN, 0.0, {}, []),
                        fields=ExtractedFields(),
                        issues=[f"extraction failed: {exc}"],
                    )
                )

        return records


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Document intelligence pipeline")
    parser.add_argument("path", help="A document or a directory of documents")
    parser.add_argument("--json", help="Write results to this JSON file")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO, format="%(message)s"
    )

    pipeline = DocumentPipeline()
    target = Path(args.path)

    try:
        records = (
            pipeline.process_directory(target) if target.is_dir() else [pipeline.process(target)]
        )
    except ExtractionBackendError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1

    for record in records:
        icon = "⚠️ " if record.needs_review else "✅"
        print(
            f"{icon} {Path(record.path).name:40} "
            f"{record.classification.document_type.value:10} "
            f"quality {record.quality_score:.2f}"
        )
        for issue in record.issues:
            print(f"     ↳ {issue}")

    if args.json:
        Path(args.json).write_text(
            json.dumps([r.as_dict() for r in records], indent=2, default=str), encoding="utf-8"
        )
        print(f"\n💾 Wrote {len(records)} record(s) to {args.json}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
