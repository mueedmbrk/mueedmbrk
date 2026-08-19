"""The assistant: retrieve, ground, answer with citations — or decline.

The whole value of RAG in an internal tool is that answers stay tied to policy
rather than to model guesswork. Two mechanisms enforce that here:

1. **Refusal on empty retrieval.** If nothing clears the similarity threshold, the
   model is never called. It cannot hallucinate an answer it was not asked for, and
   the user gets an honest "that is not in the knowledge base".
2. **Numbered sources in, citations out.** Context is presented as ``[1] … [2] …``
   and the model is required to cite. A verifiable answer is worth more than a
   fluent one.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Protocol

from .vector_store import SearchResult, VectorStore

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You answer staff questions using ONLY the reference passages provided.

Rules:
- Every factual claim must come from the passages. Never use outside knowledge.
- Cite the passage number in square brackets after each claim, like this [1].
- If the passages do not contain the answer, say so plainly. Do not guess, and do not
  fill gaps with what seems likely.
- If the passages disagree with each other, say so and cite both.
- Be concise and direct. Staff want the answer, not a summary of the documents.

Reference passages:
{context}"""

NO_CONTEXT_REPLY = (
    "I couldn't find anything in the knowledge base that answers that. "
    "It may not be documented yet, or it may be worded differently — try rephrasing, "
    "or ask the team directly."
)


class LLMClient(Protocol):
    def complete(self, system: str, messages: list[dict]) -> str: ...


class ClaudeClient:
    def __init__(self, api_key: str, model: str = "claude-opus-5", max_tokens: int = 2048) -> None:
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY is not set")

        import anthropic

        self.model = model
        self.max_tokens = max_tokens
        self._client = anthropic.Anthropic(api_key=api_key)

    def complete(self, system: str, messages: list[dict]) -> str:
        with self._client.messages.stream(
            model=self.model, max_tokens=self.max_tokens, system=system, messages=messages
        ) as stream:
            response = stream.get_final_message()

        return "".join(b.text for b in response.content if b.type == "text").strip()


@dataclass
class Answer:
    """A grounded answer plus everything needed to verify it."""

    text: str
    sources: list[SearchResult] = field(default_factory=list)
    grounded: bool = True
    cited_indices: list[int] = field(default_factory=list)

    @property
    def has_citations(self) -> bool:
        return bool(self.cited_indices)

    @property
    def citations(self) -> list[str]:
        """Human-readable labels for the sources the answer actually cited."""
        return [
            self.sources[i - 1].chunk.citation
            for i in self.cited_indices
            if 1 <= i <= len(self.sources)
        ]

    def as_dict(self) -> dict:
        return {
            "answer": self.text,
            "grounded": self.grounded,
            "has_citations": self.has_citations,
            "citations": self.citations,
            "sources": [s.as_dict() for s in self.sources],
        }


def build_context(results: list[SearchResult]) -> str:
    """Render retrieved chunks as numbered passages the model can cite."""
    blocks = []
    for position, result in enumerate(results, start=1):
        label = result.chunk.title or result.chunk.source or result.chunk.document_id
        blocks.append(f"[{position}] Source: {label}\n{result.chunk.text}")
    return "\n\n".join(blocks)


def extract_citations(text: str, source_count: int) -> list[int]:
    """Find the [n] markers the model used, ignoring any that point nowhere."""
    found = {int(n) for n in re.findall(r"\[(\d{1,2})\]", text)}
    return sorted(n for n in found if 1 <= n <= source_count)


class KnowledgeAssistant:
    """Retrieval-augmented question answering over the indexed corpus."""

    def __init__(
        self,
        llm: LLMClient,
        store: VectorStore,
        top_k: int = 5,
        min_similarity: float = 0.35,
    ) -> None:
        self.llm = llm
        self.store = store
        self.top_k = top_k
        self.min_similarity = min_similarity

    def ask(self, question: str, top_k: int | None = None) -> Answer:
        if not question.strip():
            return Answer(text="Please ask a question.", grounded=False)

        results = self.store.search(
            question, top_k=top_k or self.top_k, min_score=self.min_similarity
        )

        if not results:
            # The model is never called — it cannot hallucinate what it never saw.
            logger.info("No passages above threshold for: %r", question)
            return Answer(text=NO_CONTEXT_REPLY, sources=[], grounded=False)

        system = SYSTEM_PROMPT.format(context=build_context(results))

        try:
            text = self.llm.complete(system, [{"role": "user", "content": question}])
        except Exception as exc:  # noqa: BLE001
            logger.error("Answer generation failed: %s", exc)
            return Answer(
                text="I'm unable to answer right now — please try again shortly.",
                sources=results,
                grounded=False,
            )

        if not text:
            return Answer(text=NO_CONTEXT_REPLY, sources=results, grounded=False)

        cited = extract_citations(text, len(results))
        if not cited:
            # Retrieval worked but the model did not attribute — surface that rather
            # than presenting an unverifiable answer as if it were sourced.
            logger.warning("Answer contained no citations for: %r", question)

        return Answer(text=text, sources=results, grounded=True, cited_indices=cited)
