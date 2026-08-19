"""FAQ retrieval.

Most inbound questions to a business are the same twenty questions. Answering those
from a curated FAQ rather than a language model is faster, free, and — the part that
matters commercially — gives the *same* answer every time. Pricing and refund policy
must not be paraphrased differently on each request.

Retrieval is TF-IDF over character n-grams, which handles the typos and shorthand
real customers type ("wat r ur prices") far better than word-level matching.

Before indexing, question boilerplate is stripped. This matters more than it sounds:
with the raw text indexed, "What are your prices?" scores highest against "What are
your business hours?" — the shared prefix contributes more n-grams than the one word
that carries the meaning. Removing it lets the distinctive words decide.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# Question scaffolding that appears in nearly every enquiry and so discriminates
# between nothing. Kept deliberately small — words like "long", "much" and "offer"
# stay in, because they are exactly what separates one FAQ from another.
QUESTION_FILLER = frozenset(
    {"do", "does", "did", "can", "could", "would", "will", "please", "tell", "hi", "hello", "hey"}
)
STOP_WORDS = frozenset(ENGLISH_STOP_WORDS) | QUESTION_FILLER


def normalise(text: str) -> str:
    """Lowercase, drop punctuation, and strip boilerplate so content words dominate.

    Falls back to the unfiltered words when a message is nothing but stop words,
    so a query never normalises to the empty string and silently matches nothing.
    """
    words = re.findall(r"[a-z0-9]+", text.lower())
    kept = [w for w in words if w not in STOP_WORDS]
    return " ".join(kept or words)


@dataclass(frozen=True)
class FAQEntry:
    question: str
    answer: str
    tags: tuple[str, ...] = ()

    def searchable_text(self) -> str:
        """Tags are folded into the indexed text so synonyms match without duplicate entries."""
        return normalise(" ".join([self.question, *self.tags]))


@dataclass(frozen=True)
class FAQMatch:
    entry: FAQEntry
    score: float


DEFAULT_FAQS: tuple[FAQEntry, ...] = (
    FAQEntry(
        "What services do you offer?",
        "We build AI automation systems: conversational agents, workflow automation, "
        "document processing pipelines and custom machine learning models.",
        ("services", "offerings", "what do you do", "products"),
    ),
    FAQEntry(
        "How much does a project cost?",
        "Projects are scoped individually. Automation workflows typically start around "
        "$1,500, and larger custom ML builds are quoted after a free discovery call.",
        ("pricing", "price", "cost", "rates", "budget", "how much"),
    ),
    FAQEntry(
        "How long does a project take?",
        "A focused automation workflow usually ships in 2-3 weeks. Larger platform "
        "builds run 6-12 weeks depending on integrations.",
        ("timeline", "how long", "duration", "delivery", "eta"),
    ),
    FAQEntry(
        "Do you offer ongoing support?",
        "Yes. Every build includes 30 days of post-launch support, and monthly "
        "maintenance retainers are available.",
        ("support", "maintenance", "sla", "after launch", "warranty"),
    ),
    FAQEntry(
        "What are your business hours?",
        "We are available Monday to Friday, 9am to 6pm. Messages outside those hours "
        "are answered the next working day.",
        ("hours", "open", "availability", "timing", "when are you open"),
    ),
    FAQEntry(
        "Can you integrate with our existing tools?",
        "Yes. We routinely integrate with CRMs, Google Workspace, Slack, Twilio, "
        "Supabase and any service with a REST API or webhook.",
        ("integration", "api", "connect", "crm", "tools", "compatible"),
    ),
    FAQEntry(
        "How do we get started?",
        "Book a free 30-minute discovery call. We map the workflow, agree scope, and "
        "send a fixed-price proposal within two working days.",
        ("get started", "begin", "onboarding", "next steps", "sign up"),
    ),
    FAQEntry(
        "Do you sign NDAs and handle data securely?",
        "Yes. We sign NDAs before discovery, and all client data is processed under a "
        "documented data-handling agreement.",
        ("nda", "security", "privacy", "confidential", "gdpr", "data protection"),
    ),
)


class FAQRetriever:
    """Ranks FAQ entries against an incoming message by cosine similarity."""

    def __init__(self, entries: Sequence[FAQEntry] = DEFAULT_FAQS) -> None:
        if not entries:
            raise ValueError("FAQRetriever needs at least one entry")

        self.entries = list(entries)
        # Character n-grams survive typos and shorthand; word tokens do not.
        self._vectorizer = TfidfVectorizer(
            analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True, lowercase=True
        )
        self._matrix = self._vectorizer.fit_transform(
            [entry.searchable_text() for entry in self.entries]
        )

    def search(self, message: str, top_k: int = 3) -> list[FAQMatch]:
        """Return the closest FAQ entries, best first."""
        if not message.strip():
            return []

        # The query gets the same normalisation as the index, or the two are not comparable.
        scores = cosine_similarity(
            self._vectorizer.transform([normalise(message)]), self._matrix
        )[0]
        ranked = scores.argsort()[::-1][:top_k]
        return [FAQMatch(entry=self.entries[i], score=float(scores[i])) for i in ranked]

    def best_match(self, message: str, threshold: float) -> FAQMatch | None:
        """The top match, but only when it clears ``threshold``.

        Below the threshold we deliberately return nothing rather than a weak answer —
        a confidently wrong pricing reply is worse than handing the turn to the model.
        """
        matches = self.search(message, top_k=1)
        if matches and matches[0].score >= threshold:
            return matches[0]
        return None

    @classmethod
    def from_json(cls, path: str | Path) -> "FAQRetriever":
        """Load FAQs from a JSON file so non-developers can maintain them."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        entries = [
            FAQEntry(
                question=item["question"],
                answer=item["answer"],
                tags=tuple(item.get("tags", [])),
            )
            for item in data
        ]
        return cls(entries)
