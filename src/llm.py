"""Claude client wrapper.

Kept behind a small protocol so the orchestrator can be tested without network
access, and so a provider or model change touches exactly one file.
"""

from __future__ import annotations

import logging
from typing import Protocol

from .config import Settings

logger = logging.getLogger(__name__)

SYSTEM_TEMPLATE = """You are the customer assistant for {business_name}.

Your job is to answer questions about the business, understand what the customer
needs, and collect their contact details so the team can follow up.

Rules:
- Be concise and professional. Two or three sentences is usually right.
- Only state facts given in the reference information below. If you do not know
  something, say so and offer to have a colleague follow up.
- Never invent prices, timelines, guarantees or policies.
- If the customer seems ready to proceed, ask for their email or phone number.
- Business hours are {business_hours}. Support email is {support_email}.

Reference information:
{context}"""


class LLMClient(Protocol):
    """The surface the chatbot needs — implemented by Claude and by test fakes."""

    def complete(self, system: str, messages: list[dict]) -> str: ...


class ClaudeClient:
    """Talks to the Claude Messages API."""

    def __init__(self, settings: Settings) -> None:
        if not settings.api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY is not set. Add it to .env before starting the bot."
            )
        # Imported here rather than at module scope so the orchestrator stays
        # importable — and testable against a fake client — without the SDK present.
        import anthropic

        self.settings = settings
        self._client = anthropic.Anthropic(api_key=settings.api_key)

    def complete(self, system: str, messages: list[dict]) -> str:
        """Send the conversation and return the assistant's text.

        Streaming is used because it keeps long replies well inside the SDK's HTTP
        timeout; ``get_final_message`` gives back the assembled response so callers
        do not have to handle individual events.
        """
        with self._client.messages.stream(
            model=self.settings.model,
            max_tokens=self.settings.max_tokens,
            system=system,
            messages=messages,
        ) as stream:
            response = stream.get_final_message()

        return "".join(
            block.text for block in response.content if block.type == "text"
        ).strip()


def build_system_prompt(settings: Settings, context: str) -> str:
    return SYSTEM_TEMPLATE.format(
        business_name=settings.business_name,
        business_hours=settings.business_hours,
        support_email=settings.support_email,
        context=context or "(no additional reference information)",
    )
