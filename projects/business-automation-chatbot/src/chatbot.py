"""The orchestrator: FAQ first, model second, human when it matters."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .config import Settings, settings as default_settings
from .conversation import Conversation
from .handoff import HandoffDecision, evaluate, notify
from .knowledge import FAQRetriever
from .llm import LLMClient, build_system_prompt

logger = logging.getLogger(__name__)

FALLBACK_REPLY = (
    "I'm having trouble answering that right now. Let me pass you to a colleague "
    "who can help."
)


@dataclass
class Reply:
    """One assistant response plus the metadata a caller may want to act on."""

    text: str
    source: str  # "faq" | "llm" | "handoff" | "fallback"
    escalated: bool
    lead: dict
    confidence: float = 0.0


class Chatbot:
    """Routes each message through the cheapest path that can answer it well.

    The order is deliberate:

    1. **Handoff check** — an explicit request for a human is honoured before anything
       else, so the bot never talks over someone asking to leave.
    2. **FAQ** — a confident match answers deterministically, at no model cost.
    3. **Model** — everything else, grounded with the closest FAQ entries as context.
    """

    def __init__(
        self,
        llm: LLMClient,
        retriever: FAQRetriever | None = None,
        config: Settings | None = None,
    ) -> None:
        self.llm = llm
        self.retriever = retriever or FAQRetriever()
        self.config = config or default_settings
        self._sessions: dict[str, Conversation] = {}

    def conversation(self, session_id: str) -> Conversation:
        if session_id not in self._sessions:
            self._sessions[session_id] = Conversation(
                session_id=session_id, max_turns=self.config.max_history_turns
            )
        return self._sessions[session_id]

    def reset(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def respond(self, session_id: str, message: str) -> Reply:
        convo = self.conversation(session_id)
        convo.add("user", message)

        best = self.retriever.best_match(message, self.config.faq_confidence_threshold)
        if best is not None:
            convo.set_interest(best.entry.question)

        decision = evaluate(convo, message, faq_confident=best is not None)
        if decision.should_handoff:
            return self._handoff(convo, decision)

        if best is not None:
            convo.add("assistant", best.entry.answer)
            return Reply(
                text=best.entry.answer,
                source="faq",
                escalated=False,
                lead=convo.lead.as_dict(),
                confidence=best.score,
            )

        return self._ask_model(convo, message)

    def _handoff(self, convo: Conversation, decision: HandoffDecision) -> Reply:
        convo.escalated = True
        convo.add("assistant", decision.message)
        notify(self.config.handoff_webhook_url, convo, decision)
        return Reply(
            text=decision.message,
            source="handoff",
            escalated=True,
            lead=convo.lead.as_dict(),
        )

    def _ask_model(self, convo: Conversation, message: str) -> Reply:
        # Ground the model in the nearest FAQ entries so it answers from our facts
        # rather than from whatever it happens to believe about the business.
        context = "\n\n".join(
            f"Q: {m.entry.question}\nA: {m.entry.answer}"
            for m in self.retriever.search(message, top_k=3)
        )
        system = build_system_prompt(self.config, context)

        try:
            text = self.llm.complete(system, convo.history_for_llm())
        except Exception as exc:  # noqa: BLE001 - the customer must still get a reply
            logger.error("LLM call failed for %s: %s", convo.session_id, exc)
            convo.escalated = True
            convo.add("assistant", FALLBACK_REPLY)
            return Reply(
                text=FALLBACK_REPLY,
                source="fallback",
                escalated=True,
                lead=convo.lead.as_dict(),
            )

        if not text:
            text = FALLBACK_REPLY

        convo.add("assistant", text)
        return Reply(text=text, source="llm", escalated=False, lead=convo.lead.as_dict())
