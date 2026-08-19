"""Conversation state and lead qualification."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Literal

Role = Literal["user", "assistant"]

EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_PATTERN = re.compile(r"(?:\+?\d[\d\s().-]{7,}\d)")
BUDGET_PATTERN = re.compile(
    r"(?:[$£€]\s?\d[\d,]*(?:\.\d+)?\s?[kKmM]?)|(?:\b\d[\d,]*\s?(?:k|K|thousand|million)\b)"
)


@dataclass
class Message:
    role: Role
    content: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class Lead:
    """Details collected from the conversation, for the CRM handoff."""

    email: str | None = None
    phone: str | None = None
    budget: str | None = None
    interest: str | None = None

    @property
    def is_qualified(self) -> bool:
        """Qualified means reachable and intent-bearing — a contact route plus a stated need."""
        return bool((self.email or self.phone) and self.interest)

    def missing_fields(self) -> list[str]:
        missing = []
        if not (self.email or self.phone):
            missing.append("contact")
        if not self.interest:
            missing.append("interest")
        return missing

    def as_dict(self) -> dict:
        return {
            "email": self.email,
            "phone": self.phone,
            "budget": self.budget,
            "interest": self.interest,
            "qualified": self.is_qualified,
        }


@dataclass
class Conversation:
    """One customer's session: history, extracted lead details and escalation state."""

    session_id: str
    messages: list[Message] = field(default_factory=list)
    lead: Lead = field(default_factory=Lead)
    escalated: bool = False
    max_turns: int = 12

    def add(self, role: Role, content: str) -> Message:
        message = Message(role=role, content=content)
        self.messages.append(message)
        if role == "user":
            self.extract_lead_details(content)
        self._trim()
        return message

    def _trim(self) -> None:
        """Keep the history bounded so long sessions do not grow cost without bound.

        The oldest turns are dropped rather than summarised: for a support chat the
        recent turns carry the intent, and extracted lead details are already stored
        separately on ``self.lead``, so nothing that matters commercially is lost.
        """
        limit = self.max_turns * 2  # a "turn" is one user message plus one reply
        if len(self.messages) > limit:
            self.messages = self.messages[-limit:]

    def extract_lead_details(self, text: str) -> None:
        """Pull contact details out of free text as the customer volunteers them."""
        if not self.lead.email:
            match = EMAIL_PATTERN.search(text)
            if match:
                self.lead.email = match.group(0)

        if not self.lead.phone:
            match = PHONE_PATTERN.search(text)
            if match:
                # Reject anything that is really an email fragment or a long number run.
                candidate = match.group(0).strip()
                digits = re.sub(r"\D", "", candidate)
                if 8 <= len(digits) <= 15 and "@" not in text[: match.start()][-3:]:
                    self.lead.phone = candidate

        if not self.lead.budget:
            match = BUDGET_PATTERN.search(text)
            if match:
                self.lead.budget = match.group(0).strip()

    def set_interest(self, interest: str) -> None:
        if interest and not self.lead.interest:
            self.lead.interest = interest

    def history_for_llm(self) -> list[dict]:
        """History in the shape the Messages API expects."""
        return [{"role": m.role, "content": m.content} for m in self.messages]

    @property
    def user_message_count(self) -> int:
        return sum(1 for m in self.messages if m.role == "user")
