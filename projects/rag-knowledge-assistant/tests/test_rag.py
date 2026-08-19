"""Tests for chunking, retrieval, grounding and ingestion."""

import numpy as np
import pytest

from src.assistant import (
    NO_CONTEXT_REPLY,
    Answer,
    KnowledgeAssistant,
    build_context,
    extract_citations,
)
from src.chunking import chunk_text
from src.embeddings import HashingEmbeddings, cosine_similarity
from src.ingest import Ingestor
from src.vector_store import InMemoryVectorStore

POLICY = """Annual Leave Policy

All permanent staff are entitled to 25 days of paid annual leave per calendar year.
Leave must be requested at least two weeks in advance through the HR portal.

Unused leave may be carried over, up to a maximum of five days, and must be used
before the end of March in the following year.

Public holidays are additional to the annual leave entitlement.
"""

EXPENSES = """Expense Reimbursement Policy

Business expenses are reimbursed within 30 days of submission. Receipts are required
for any claim above twenty pounds.

Travel booked more than three weeks in advance qualifies for the advance booking rate.
Client entertainment requires approval from a director before the expense is incurred.
"""


# ------------------------------------------------------------------- chunking

def test_short_text_becomes_a_single_chunk():
    chunks = chunk_text("A short note.", document_id="note", chunk_size=800)
    assert len(chunks) == 1
    assert chunks[0].text == "A short note."


def test_long_text_is_split_into_overlapping_chunks():
    text = " ".join(f"Sentence number {i} about company policy." for i in range(200))
    chunks = chunk_text(text, document_id="long", chunk_size=400, overlap=100)

    assert len(chunks) > 1
    assert all(len(c.text) <= 500 for c in chunks)
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


def test_chunks_break_on_natural_boundaries():
    """A chunk that ends mid-word retrieves badly and reads worse when cited."""
    text = ". ".join(f"This is sentence number {i}" for i in range(60)) + "."
    chunks = chunk_text(text, document_id="doc", chunk_size=300, overlap=50)

    for chunk in chunks[:-1]:
        assert not chunk.text.endswith(("thi", "sente", "numbe"))


def test_overlap_preserves_facts_that_straddle_a_boundary():
    text = "A" * 300 + " THE CRITICAL FACT IS HERE " + "B" * 300
    chunks = chunk_text(text, document_id="doc", chunk_size=350, overlap=150)
    assert sum("CRITICAL FACT" in c.text for c in chunks) >= 1


def test_chunk_ids_are_deterministic():
    """Re-ingesting an unchanged document must reuse IDs, or the corpus duplicates."""
    first = chunk_text(POLICY, document_id="leave", chunk_size=200)
    second = chunk_text(POLICY, document_id="leave", chunk_size=200)
    assert [c.chunk_id for c in first] == [c.chunk_id for c in second]


def test_different_content_yields_different_ids():
    a = chunk_text("Original text here.", document_id="doc")[0]
    b = chunk_text("Amended text here.", document_id="doc")[0]
    assert a.chunk_id != b.chunk_id


def test_empty_text_yields_no_chunks():
    assert chunk_text("   \n\n  ", document_id="empty") == []


@pytest.mark.parametrize("size,overlap", [(0, 0), (100, 100), (100, 150), (100, -1)])
def test_invalid_chunk_parameters_are_rejected(size, overlap):
    with pytest.raises(ValueError):
        chunk_text("some text", document_id="d", chunk_size=size, overlap=overlap)


def test_chunk_exposes_a_readable_citation():
    chunk = chunk_text(POLICY, document_id="leave", title="Annual Leave Policy")[0]
    assert chunk.citation == "Annual Leave Policy (part 1)"


# ------------------------------------------------------------------ embedding

def test_hashing_embeddings_are_deterministic():
    embedder = HashingEmbeddings(dimensions=64)
    a = embedder.embed(["annual leave policy"])
    b = embedder.embed(["annual leave policy"])
    np.testing.assert_array_equal(a, b)


def test_embeddings_are_unit_normalised():
    vectors = HashingEmbeddings(64).embed(["some text here", "other text"])
    np.testing.assert_allclose(np.linalg.norm(vectors, axis=1), 1.0, rtol=1e-5)


def test_empty_input_returns_an_empty_matrix():
    assert HashingEmbeddings(64).embed([]).shape == (0, 64)


def test_cosine_similarity_handles_zero_vectors():
    """A zero-norm row must score zero, not raise or return NaN."""
    scores = cosine_similarity(np.array([1.0, 0.0]), np.array([[0.0, 0.0], [1.0, 0.0]]))
    assert not np.isnan(scores).any()
    assert scores[1] == pytest.approx(1.0)


# ------------------------------------------------------------------ retrieval

@pytest.fixture
def store() -> InMemoryVectorStore:
    store = InMemoryVectorStore(HashingEmbeddings(dimensions=512))
    store.upsert(chunk_text(POLICY, document_id="leave", title="Annual Leave Policy"))
    store.upsert(chunk_text(EXPENSES, document_id="expenses", title="Expense Policy"))
    return store


def test_retrieval_finds_the_relevant_document(store):
    results = store.search("how many days of annual leave", top_k=1, min_score=0.0)
    assert results[0].chunk.document_id == "leave"


def test_retrieval_respects_the_score_threshold(store):
    assert store.search("quantum chromodynamics lattice gauge", top_k=5, min_score=0.9) == []


def test_retrieval_respects_top_k(store):
    assert len(store.search("policy", top_k=2, min_score=0.0)) <= 2


def test_empty_query_retrieves_nothing(store):
    assert store.search("   ", top_k=5, min_score=0.0) == []


def test_upsert_is_idempotent(store):
    before = store.count()
    store.upsert(chunk_text(POLICY, document_id="leave", title="Annual Leave Policy"))
    assert store.count() == before, "re-ingesting must not duplicate chunks"


def test_deleting_a_document_removes_its_chunks(store):
    removed = store.delete_document("leave")
    assert removed > 0
    assert all(r.chunk.document_id != "leave" for r in store.search("leave", 5, 0.0))


# ------------------------------------------------------------------- grounding

class FakeLLM:
    def __init__(self, reply: str = "Staff get 25 days [1].", fail: bool = False) -> None:
        self.reply = reply
        self.fail = fail
        self.calls: list[tuple[str, list[dict]]] = []

    def complete(self, system: str, messages: list[dict]) -> str:
        self.calls.append((system, messages))
        if self.fail:
            raise RuntimeError("upstream unavailable")
        return self.reply


def test_answer_is_grounded_and_cited(store):
    assistant = KnowledgeAssistant(FakeLLM(), store, min_similarity=0.0)
    answer = assistant.ask("How much annual leave do staff get?")

    assert answer.grounded is True
    assert answer.has_citations
    assert answer.citations[0].startswith("Annual Leave Policy")


def test_no_relevant_context_never_calls_the_model(store):
    """The strongest anti-hallucination guarantee: the model never sees the question."""
    llm = FakeLLM()
    assistant = KnowledgeAssistant(llm, store, min_similarity=0.99)

    answer = assistant.ask("What is the airspeed velocity of an unladen swallow?")

    assert answer.grounded is False
    assert answer.text == NO_CONTEXT_REPLY
    assert llm.calls == [], "the model must not be called without context"


def test_context_is_numbered_for_citation(store):
    llm = FakeLLM()
    KnowledgeAssistant(llm, store, top_k=2, min_similarity=0.0).ask("leave policy")

    system, _ = llm.calls[0]
    assert "[1]" in system
    assert "Never use outside knowledge" in system


def test_uncited_answer_is_flagged_but_returned(store):
    assistant = KnowledgeAssistant(FakeLLM("Staff get 25 days."), store, min_similarity=0.0)
    answer = assistant.ask("How much leave?")

    assert answer.grounded is True
    assert answer.has_citations is False


def test_model_failure_does_not_raise(store):
    assistant = KnowledgeAssistant(FakeLLM(fail=True), store, min_similarity=0.0)
    answer = assistant.ask("How much leave?")

    assert answer.grounded is False
    assert "unable to answer" in answer.text


def test_blank_question_is_rejected(store):
    assert KnowledgeAssistant(FakeLLM(), store).ask("   ").grounded is False


@pytest.mark.parametrize(
    "text,count,expected",
    [
        ("Answer [1] and [2].", 3, [1, 2]),
        ("Repeated [1] cite [1].", 2, [1]),
        ("Out of range [9].", 2, []),
        ("No citations at all.", 2, []),
    ],
)
def test_citation_extraction(text, count, expected):
    assert extract_citations(text, count) == expected


def test_answer_serialises_for_an_api(store):
    answer = KnowledgeAssistant(FakeLLM(), store, min_similarity=0.0).ask("leave?")
    data = answer.as_dict()

    assert set(data) == {"answer", "grounded", "has_citations", "citations", "sources"}
    assert all("score" in s for s in data["sources"])


def test_build_context_labels_each_passage(store):
    results = store.search("leave", top_k=2, min_score=0.0)
    context = build_context(results)
    assert context.startswith("[1] Source:")


# ------------------------------------------------------------------ ingestion

def test_directory_ingestion_indexes_supported_files(tmp_path):
    (tmp_path / "leave.md").write_text(POLICY, encoding="utf-8")
    (tmp_path / "expenses.txt").write_text(EXPENSES, encoding="utf-8")
    (tmp_path / "logo.png").write_bytes(b"\x89PNG")

    store = InMemoryVectorStore(HashingEmbeddings(128))
    report = Ingestor(store, chunk_size=200).ingest_directory(tmp_path)

    assert report.documents_processed == 2
    assert report.chunks_written > 0
    assert store.count() > 0


def test_unchanged_documents_are_skipped_on_reingest(tmp_path):
    """Re-indexing an unchanged corpus must cost nothing — that is what makes it
    reasonable to run on every file change."""
    (tmp_path / "leave.md").write_text(POLICY, encoding="utf-8")
    ingestor = Ingestor(InMemoryVectorStore(HashingEmbeddings(128)), chunk_size=200)

    ingestor.ingest_directory(tmp_path)
    second = ingestor.ingest_directory(tmp_path)

    assert second.documents_processed == 0
    assert second.documents_skipped == 1


def test_edited_document_is_reindexed(tmp_path):
    path = tmp_path / "leave.md"
    path.write_text(POLICY, encoding="utf-8")
    ingestor = Ingestor(InMemoryVectorStore(HashingEmbeddings(128)), chunk_size=200)
    ingestor.ingest_directory(tmp_path)

    path.write_text(POLICY.replace("25 days", "30 days"), encoding="utf-8")
    report = ingestor.ingest_directory(tmp_path)

    assert report.documents_processed == 1


def test_shortened_document_leaves_no_orphan_chunks(tmp_path):
    """An edit that shortens a document must not leave stale chunks in retrieval."""
    path = tmp_path / "policy.md"
    path.write_text(POLICY + EXPENSES + POLICY, encoding="utf-8")

    store = InMemoryVectorStore(HashingEmbeddings(128))
    ingestor = Ingestor(store, chunk_size=200)
    ingestor.ingest_directory(tmp_path)
    before = store.count()

    path.write_text("Annual leave is now 30 days.", encoding="utf-8")
    ingestor.ingest_directory(tmp_path)

    assert store.count() < before


def test_force_reindexes_everything(tmp_path):
    (tmp_path / "leave.md").write_text(POLICY, encoding="utf-8")
    ingestor = Ingestor(InMemoryVectorStore(HashingEmbeddings(128)), chunk_size=200)
    ingestor.ingest_directory(tmp_path)

    report = ingestor.ingest_directory(tmp_path, force=True)
    assert report.documents_processed == 1


def test_missing_directory_is_reported_clearly(tmp_path):
    ingestor = Ingestor(InMemoryVectorStore(HashingEmbeddings(64)))
    with pytest.raises(NotADirectoryError):
        ingestor.ingest_directory(tmp_path / "nope")
