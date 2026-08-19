"""Escalation: deciding when a human needs to take over.

A bot that will not let go is worse than no bot at all. These rules are intentionally
eager — the cost of handing a conversation to a human unnecessarily is small; the cost
of trapping a frustrated customer in a loop is a lost customer.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

import requests

from .conversation import Conversation

logger = logging.getLogger(__name__)


class HandoffReason(str, Enum):
    EXPLICIT_REQUEST = "explicit_request"
    FRUSTRATION = "frustration"
    REPEATED_CONFUSION = "repeated_confusion"
    QUALIFIED_LEAD = "qualified_lead"
    SENSITIVE_TOPIC = "sensitive_topic"


EXPLICIT_PHRASES = (
    "speak to a human", "talk to a human", "real person", "speak to someone",
    "talk to someone", "customer service", "agent please", "human agent",
    "representative", "put me through", "call me back",
)

FRUSTRATION_PHRASES = (
    "this is useless", "not helping", "useless bot", "waste of time",
    "ridiculous", "frustrated", "annoyed", "terrible service", "fed up",
    "stop repeating", "i already said",
)

SENSITIVE_PHRASES = (
    "refund", "chargeback", "cancel my contract", "legal", "lawyer",
    "complaint", "gdpr", "data breach", "sue",
)


@dataclass(frozen=True)
class HandoffDecision:
    should_handoff: bool
    reason: HandoffReason | None = None
    message: str = ""


def _contains(text: str, phrases: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(phrase in lowered for phrase in phrases)


def evaluate(conversation: Conversation, message: str, faq_confident: bool) -> HandoffDecision:
    """Decide whether this turn should go to a human.

    Order matters — an explicit request is honoured immediately and is never
    overridden by a "we can still help you here" path.
    """
    if _contains(message, EXPLICIT_PHRASES):
        return HandoffDecision(
            True,
            HandoffReason.EXPLICIT_REQUEST,
            "Of course — I'm connecting you with a member of the team now.",
        )

    if _contains(message, FRUSTRATION_PHRASES):
        return HandoffDecision(
            True,
            HandoffReason.FRUSTRATION,
            "I'm sorry this has been frustrating. Let me bring in a colleague who can help properly.",
        )

    if _contains(message, SENSITIVE_PHRASES):
        return HandoffDecision(
            True,
            HandoffReason.SENSITIVE_TOPIC,
            "That's something our team should handle directly — I'm passing you to them now.",
        )

    # Several exchanges deep with no confident answer means the bot is not converging.
    if conversation.user_message_count >= 4 and not faq_confident:
        return HandoffDecision(
            True,
            HandoffReason.REPEATED_CONFUSION,
            "I want to make sure you get an accurate answer — let me connect you with the team.",
        )

    if conversation.lead.is_qualified:
        return HandoffDecision(
            True,
            HandoffReason.QUALIFIED_LEAD,
            "Thanks — I have everything I need. A specialist will follow up shortly.",
        )

    return HandoffDecision(False)


def notify(webhook_url: str, conversation: Conversation, decision: HandoffDecision) -> bool:
    """POST the handoff to the CRM or n8n workflow. Never raises into the chat path."""
    if not webhook_url or not decision.should_handoff:
        return False

    payload = {
        "session_id": conversation.session_id,
        "reason": decision.reason.value if decision.reason else None,
        "lead": conversation.lead.as_dict(),
        "transcript": [
            {"role": m.role, "content": m.content} for m in conversation.messages
        ],
    }

    try:
        response = requests.post(webhook_url, json=payload, timeout=5)
        response.raise_for_status()
        return True
    except requests.RequestException as exc:
        # A failed CRM webhook must never break the customer's conversation.
        logger.error("Handoff webhook failed for %s: %s", conversation.session_id, exc)
        return False
