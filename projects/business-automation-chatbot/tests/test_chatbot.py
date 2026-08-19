"""Tests for routing, lead capture and escalation — no network required."""

import pytest

from src.chatbot import Chatbot
from src.config import Settings
from src.conversation import Conversation
from src.handoff import HandoffReason, evaluate
from src.knowledge import FAQRetriever


class FakeLLM:
    """Stands in for Claude. Records what it was asked, returns a canned reply."""

    def __init__(self, reply: str = "Let me look into that for you.", fail: bool = False) -> None:
        self.reply = reply
        self.fail = fail
        self.calls: list[tuple[str, list[dict]]] = []

    def complete(self, system: str, messages: list[dict]) -> str:
        self.calls.append((system, messages))
        if self.fail:
            raise RuntimeError("upstream unavailable")
        return self.reply


@pytest.fixture
def config() -> Settings:
    return Settings(
        api_key="test", business_name="Acme", faq_confidence_threshold=0.35, handoff_webhook_url=""
    )


@pytest.fixture
def bot(config) -> Chatbot:
    return Chatbot(llm=FakeLLM(), config=config)


# ---------------------------------------------------------------- FAQ retrieval

def test_faq_matches_a_direct_question():
    match = FAQRetriever().best_match("What are your prices?", threshold=0.3)
    assert match is not None
    assert "1,500" in match.entry.answer


def test_boilerplate_does_not_hijack_the_match():
    """"What are your prices?" must not match "What are your business hours?".

    Both share the same four-word prefix. Without boilerplate stripping the prefix
    contributes more character n-grams than "prices" does, and the wrong entry wins.
    """
    match = FAQRetriever().best_match("What are your prices?", threshold=0.3)
    assert "cost" in match.entry.question.lower()


def test_faq_survives_typos_and_shorthand():
    """Character n-grams are chosen precisely so real customer typing still matches."""
    match = FAQRetriever().best_match("wat r ur pricing", threshold=0.25)
    assert match is not None
    assert "cost" in match.entry.question.lower()


def test_faq_declines_unrelated_questions():
    assert FAQRetriever().best_match("what is the weather in Oslo", threshold=0.55) is None


def test_empty_message_matches_nothing():
    assert FAQRetriever().search("   ") == []


def test_retriever_rejects_empty_entry_list():
    with pytest.raises(ValueError):
        FAQRetriever([])


# ------------------------------------------------------------------- routing

def test_confident_faq_answers_without_calling_the_model(config):
    llm = FakeLLM()
    bot = Chatbot(llm=llm, config=config)

    reply = bot.respond("s1", "What services do you offer?")

    assert reply.source == "faq"
    assert llm.calls == [], "a confident FAQ hit must not cost a model call"


def test_unknown_question_falls_through_to_the_model(config):
    llm = FakeLLM(reply="I'll check with the team.")
    bot = Chatbot(llm=llm, config=config)

    reply = bot.respond("s1", "Can you migrate our Fortran payroll system to Rust?")

    assert reply.source == "llm"
    assert reply.text == "I'll check with the team."
    assert len(llm.calls) == 1


def test_model_prompt_is_grounded_in_faq_context(config):
    llm = FakeLLM()
    bot = Chatbot(llm=llm, config=config)
    bot.respond("s1", "Something completely unrelated to our FAQ list")

    system, _ = llm.calls[0]
    assert "Reference information:" in system
    assert "Never invent prices" in system


def test_model_failure_degrades_to_a_handoff(config):
    bot = Chatbot(llm=FakeLLM(fail=True), config=config)
    reply = bot.respond("s1", "An unusual question the FAQ cannot answer at all")

    assert reply.source == "fallback"
    assert reply.escalated is True


# ------------------------------------------------------------------ escalation

def test_explicit_request_for_a_human_is_honoured_immediately(bot):
    reply = bot.respond("s1", "I want to speak to a human please")
    assert reply.escalated is True
    assert reply.source == "handoff"


def test_frustration_triggers_escalation(bot):
    reply = bot.respond("s1", "this is useless, you are not helping")
    assert reply.escalated is True


def test_sensitive_topic_goes_straight_to_a_person(bot):
    reply = bot.respond("s1", "I need a refund for last month")
    assert reply.escalated is True


def test_explicit_request_outranks_a_matching_faq(bot):
    """Asking for a human while also asking a FAQ question must still escalate."""
    reply = bot.respond("s1", "What are your prices? Actually let me talk to a human")
    assert reply.source == "handoff"


def test_repeated_unanswerable_questions_escalate(config):
    bot = Chatbot(llm=FakeLLM(), config=config)
    for i in range(3):
        reply = bot.respond("s1", f"obscure unmatched question number {i} zzzz")
        assert reply.escalated is False

    reply = bot.respond("s1", "another obscure unmatched question yyyy")
    assert reply.escalated is True


def test_normal_conversation_does_not_escalate(bot):
    reply = bot.respond("s1", "What are your business hours?")
    assert reply.escalated is False


# ---------------------------------------------------------------- lead capture

def test_email_is_extracted_from_free_text():
    convo = Conversation(session_id="s1")
    convo.add("user", "sure, reach me at sara.khan@example.com tomorrow")
    assert convo.lead.email == "sara.khan@example.com"


def test_phone_and_budget_are_extracted():
    convo = Conversation(session_id="s1")
    convo.add("user", "call me on +92 300 1234567, budget is around $5,000")
    assert convo.lead.phone is not None
    assert convo.lead.budget == "$5,000"


def test_lead_is_qualified_only_with_contact_and_interest():
    convo = Conversation(session_id="s1")
    convo.add("user", "hello@example.com")
    assert convo.lead.is_qualified is False
    assert convo.lead.missing_fields() == ["interest"]

    convo.set_interest("How much does a project cost?")
    assert convo.lead.is_qualified is True


def test_qualified_lead_is_handed_to_a_specialist(config):
    bot = Chatbot(llm=FakeLLM(), config=config)
    bot.respond("s1", "How much does a project cost?")          # sets interest
    reply = bot.respond("s1", "great, my email is buyer@corp.com")

    assert reply.escalated is True
    assert reply.lead["qualified"] is True
    assert reply.lead["email"] == "buyer@corp.com"


def test_evaluate_reports_the_reason():
    convo = Conversation(session_id="s1")
    decision = evaluate(convo, "get me a real person", faq_confident=False)
    assert decision.reason is HandoffReason.EXPLICIT_REQUEST


# ------------------------------------------------------------------- sessions

def test_sessions_are_isolated(bot):
    bot.respond("alice", "my email is alice@example.com")
    bot.respond("bob", "hello there")

    assert bot.conversation("alice").lead.email == "alice@example.com"
    assert bot.conversation("bob").lead.email is None


def test_history_is_trimmed_to_the_configured_window():
    convo = Conversation(session_id="s1", max_turns=3)
    for i in range(20):
        convo.add("user", f"message {i}")
        convo.add("assistant", f"reply {i}")

    assert len(convo.messages) == 6
    assert convo.messages[-1].content == "reply 19"


def test_reset_clears_a_session(bot):
    bot.respond("s1", "my email is x@y.com")
    bot.reset("s1")
    assert bot.conversation("s1").lead.email is None
