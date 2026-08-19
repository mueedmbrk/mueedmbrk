"""Text acquisition.

The important decision in this module is *not* running OCR when you do not have to.
Most PDFs that arrive at a business — invoices from accounting software, contracts
from e-signature tools — already carry a perfect embedded text layer. Running OCR on
those is slower and strictly less accurate: it re-derives characters from a rendering
of text that was already exact.

So the pipeline reads the text layer first and only rasterises pages that come back
effectively empty. On a typical mixed batch this cuts processing time by an order of
magnitude and improves accuracy at the same time.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)


class ExtractionBackendError(RuntimeError):
    """Raised when no text could be obtained from a document."""


@dataclass
class PageText:
    page_number: int
    text: str
    source: str  # "text_layer" | "ocr"

    @property
    def char_count(self) -> int:
        return len(self.text.strip())


@dataclass
class DocumentText:
    """The full text of a document plus how each page was obtained."""

    path: str
    pages: list[PageText]

    @property
    def text(self) -> str:
        return "\n\n".join(page.text for page in self.pages)

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def ocr_page_count(self) -> int:
        return sum(1 for page in self.pages if page.source == "ocr")

    @property
    def used_ocr(self) -> bool:
        return self.ocr_page_count > 0


class TextExtractor(Protocol):
    """The surface the pipeline needs — real or fake."""

    def extract(self, path: str | Path) -> DocumentText: ...


class HybridExtractor:
    """Reads the PDF text layer, falling back to OCR only for pages that need it."""

    def __init__(
        self,
        min_text_layer_chars: int = 120,
        language: str = "eng",
        dpi: int = 300,
        tesseract_cmd: str = "",
    ) -> None:
        self.min_text_layer_chars = min_text_layer_chars
        self.language = language
        self.dpi = dpi
        self.tesseract_cmd = tesseract_cmd

    def extract(self, path: str | Path) -> DocumentText:
        path = Path(path)
        if not path.exists():
            raise ExtractionBackendError(f"document not found: {path}")

        if path.suffix.lower() == ".pdf":
            return self._extract_pdf(path)
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}:
            return DocumentText(str(path), [self._ocr_image(path, page_number=1)])
        if path.suffix.lower() in {".txt", ".md"}:
            return DocumentText(
                str(path),
                [PageText(1, path.read_text(encoding="utf-8", errors="replace"), "text_layer")],
            )

        raise ExtractionBackendError(f"unsupported file type: {path.suffix}")

    def _extract_pdf(self, path: Path) -> DocumentText:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        pages: list[PageText] = []
        needs_ocr: list[int] = []

        for index, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            if len(text) >= self.min_text_layer_chars:
                pages.append(PageText(index, text, "text_layer"))
            else:
                # Placeholder, replaced below if OCR succeeds.
                pages.append(PageText(index, text, "text_layer"))
                needs_ocr.append(index)

        if needs_ocr:
            logger.info("🔍 OCR needed for %d of %d pages in %s",
                        len(needs_ocr), len(pages), path.name)
            for page_number in needs_ocr:
                try:
                    pages[page_number - 1] = self._ocr_pdf_page(path, page_number)
                except Exception as exc:  # noqa: BLE001
                    # One unreadable page must not discard the rest of the document.
                    logger.error("OCR failed for page %d of %s: %s", page_number, path.name, exc)

        if not any(page.char_count for page in pages):
            raise ExtractionBackendError(f"no text could be extracted from {path}")

        return DocumentText(str(path), pages)

    def _configure_tesseract(self):
        import pytesseract

        if self.tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = self.tesseract_cmd
        return pytesseract

    def _ocr_pdf_page(self, path: Path, page_number: int) -> PageText:
        from pdf2image import convert_from_path

        pytesseract = self._configure_tesseract()
        images = convert_from_path(
            str(path), dpi=self.dpi, first_page=page_number, last_page=page_number
        )
        if not images:
            raise ExtractionBackendError(f"could not rasterise page {page_number}")

        text = pytesseract.image_to_string(images[0], lang=self.language)
        return PageText(page_number, text.strip(), "ocr")

    def _ocr_image(self, path: Path, page_number: int) -> PageText:
        from PIL import Image

        pytesseract = self._configure_tesseract()
        text = pytesseract.image_to_string(Image.open(path), lang=self.language)
        return PageText(page_number, text.strip(), "ocr")
