"""Document type classification.

Two signals are combined, because neither is reliable alone:

* **Keyword evidence** — documents announce themselves. An invoice says "invoice",
  "amount due" and "VAT". This is precise but brittle against unusual wording.
* **TF-IDF similarity** — compares the document against a profile of each type,
  catching documents that never use the obvious word.

Below a confidence floor the type is reported as ``unknown`` rather than guessed.
A misrouted contract costs more than one flagged for human review.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


class DocumentType(str, Enum):
    INVOICE = "invoice"
    RECEIPT = "receipt"
    CONTRACT = "contract"
    RESUME = "resume"
    LETTER = "letter"
    REPORT = "report"
    UNKNOWN = "unknown"


# Strong keywords count double — they are close to definitional for their type.
TYPE_KEYWORDS: dict[DocumentType, dict[str, int]] = {
    DocumentType.INVOICE: {
        "invoice": 2, "invoice number": 2, "amount due": 2, "bill to": 2,
        "payment terms": 2, "vat": 1, "tax": 1, "subtotal": 1, "due date": 1,
        "purchase order": 1, "remit": 1,
    },
    DocumentType.RECEIPT: {
        "receipt": 2, "thank you for your purchase": 2, "change due": 2,
        "cash": 1, "card": 1, "total": 1, "transaction": 1, "merchant": 1, "till": 1,
    },
    DocumentType.CONTRACT: {
        "agreement": 2, "this agreement": 2, "hereby": 2, "the parties": 2,
        "terms and conditions": 2, "governing law": 2, "indemnity": 1,
        "confidentiality": 1, "termination": 1, "witness": 1, "clause": 1,
    },
    DocumentType.RESUME: {
        "curriculum vitae": 2, "resume": 2, "work experience": 2, "education": 1,
        "skills": 1, "references": 1, "employment history": 2, "objective": 1,
    },
    DocumentType.LETTER: {
        "dear": 2, "sincerely": 2, "yours faithfully": 2, "kind regards": 2,
        "re:": 1, "enclosed": 1,
    },
    DocumentType.REPORT: {
        "executive summary": 2, "methodology": 2, "findings": 2, "conclusion": 1,
        "appendix": 1, "table of contents": 1, "recommendations": 1,
    },
}

# Reference text per type for the similarity half of the vote.
TYPE_PROFILES: dict[DocumentType, str] = {
    DocumentType.INVOICE: (
        "invoice number date bill to ship to description quantity unit price amount "
        "subtotal vat tax total amount due payment terms bank details remit payment"
    ),
    DocumentType.RECEIPT: (
        "receipt merchant store date time item qty price total cash card change due "
        "thank you for your purchase transaction reference till operator"
    ),
    DocumentType.CONTRACT: (
        "this agreement is made between the parties hereby agree terms and conditions "
        "obligations confidentiality indemnity liability termination governing law "
        "signature witness clause effective date"
    ),
    DocumentType.RESUME: (
        "curriculum vitae name contact email phone professional summary work experience "
        "employment history education qualifications skills certifications references projects"
    ),
    DocumentType.LETTER: (
        "dear sir madam re reference our records writing regarding please find enclosed "
        "yours sincerely faithfully kind regards signature address date"
    ),
    DocumentType.REPORT: (
        "executive summary introduction background methodology data analysis results "
        "findings discussion conclusion recommendations appendix references figures tables"
    ),
}


@dataclass(frozen=True)
class Classification:
    document_type: DocumentType
    confidence: float
    scores: dict[str, float]
    matched_keywords: list[str]


class DocumentClassifier:
    """Scores a document against every known type and picks the strongest."""

    def __init__(self, threshold: float = 0.18) -> None:
        self.threshold = threshold
        self._types = list(TYPE_PROFILES)
        self._vectorizer = TfidfVectorizer(
            analyzer="word", ngram_range=(1, 2), sublinear_tf=True, stop_words="english"
        )
        self._matrix = self._vectorizer.fit_transform(
            [TYPE_PROFILES[t] for t in self._types]
        )

    def _keyword_scores(self, text: str) -> tuple[dict[DocumentType, float], list[str]]:
        lowered = text.lower()
        scores: dict[DocumentType, float] = {}
        matched: list[str] = []

        for doc_type, keywords in TYPE_KEYWORDS.items():
            hit_weight = 0
            for keyword, weight in keywords.items():
                # Word-boundary match so "tax" does not fire inside "taxonomy".
                if re.search(rf"(?<!\w){re.escape(keyword)}(?!\w)", lowered):
                    hit_weight += weight
                    matched.append(keyword)
            total = sum(keywords.values())
            scores[doc_type] = hit_weight / total if total else 0.0

        return scores, matched

    def _similarity_scores(self, text: str) -> dict[DocumentType, float]:
        if not text.strip():
            return {t: 0.0 for t in self._types}
        similarities = cosine_similarity(self._vectorizer.transform([text]), self._matrix)[0]
        return dict(zip(self._types, (float(s) for s in similarities)))

    def classify(self, text: str) -> Classification:
        """Combine both signals and return the winning type with its confidence."""
        if not text or not text.strip():
            return Classification(DocumentType.UNKNOWN, 0.0, {}, [])

        keyword_scores, matched = self._keyword_scores(text)
        similarity_scores = self._similarity_scores(text)

        # Keywords are weighted higher: they are near-definitional when present,
        # while similarity mostly rescues documents with unusual phrasing.
        combined = {
            doc_type: 0.65 * keyword_scores.get(doc_type, 0.0)
            + 0.35 * similarity_scores.get(doc_type, 0.0)
            for doc_type in self._types
        }

        best = max(combined, key=combined.get)
        confidence = combined[best]

        if confidence < self.threshold:
            best = DocumentType.UNKNOWN

        return Classification(
            document_type=best,
            confidence=round(confidence, 4),
            scores={t.value: round(s, 4) for t, s in combined.items()},
            matched_keywords=sorted(set(matched)),
        )
