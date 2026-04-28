"""LLM-based message compaction.

When the conversation exceeds max_messages, older messages are
summarized into a single system message while recent messages
are kept verbatim.
"""

from __future__ import annotations

from typing import Any

from dataclaw.providers.llm.provider import LLMProvider, TextDeltaEvent
from dataclaw.schema import Message

_SUMMARY_PROMPT = (
    "Summarize the following conversation concisely, preserving key facts, "
    "decisions, tool results, and any context the assistant needs to continue "
    "helping the user. Be brief but complete."
)


class LLMSummarizingCompactor:
    """Compacts messages by summarizing older ones via the LLM."""

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def compact(
        self,
        messages: list[Message],
        *,
        max_messages: int = 30,
        keep_recent: int = 8,
    ) -> list[Message]:
        if len(messages) <= max_messages:
            return messages

        old = messages[: len(messages) - keep_recent]
        recent = messages[len(messages) - keep_recent :]

        summary = await self._summarize(old)
        summary_msg = Message.user(f"[Conversation summary]\n{summary}")
        return [summary_msg] + recent

    async def _summarize(self, messages: list[Message]) -> str:
        """Use the LLM to summarize a block of messages."""
        formatted = []
        for msg in messages:
            formatted.append(f"{msg.role}: {msg.text()}")

        summary_request = [
            Message.user(f"{_SUMMARY_PROMPT}\n\n" + "\n".join(formatted))
        ]

        chunks: list[str] = []
        async for event in self._llm.stream_turn(
            summary_request, system="You are a helpful summarizer.", tools=[]
        ):
            if isinstance(event, TextDeltaEvent):
                chunks.append(event.text)

        return "".join(chunks)
