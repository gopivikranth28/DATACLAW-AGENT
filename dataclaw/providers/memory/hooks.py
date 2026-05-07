"""Memory hooks — auto-ingest conversation turns into the memory provider."""

from __future__ import annotations

import logging
from typing import Any

from dataclaw.state import AgentState

logger = logging.getLogger(__name__)

# Minimum text length for a turn to be worth memorizing
_MIN_CONTENT_LEN = 20


class MemoryIngestHook:
    """Hook that feeds conversation turns into the memory provider.

    Register at ``postAgentMessageHook`` so each assistant response
    is automatically persisted as a memory.
    """

    def __init__(self, provider: Any) -> None:
        self._provider = provider

    async def __call__(self, state: AgentState) -> AgentState:
        messages = state.get("messages", [])
        if len(messages) < 2:
            return state

        # Find the last user + assistant pair
        user_text: str | None = None
        assistant_text: str | None = None

        for msg in reversed(messages):
            role = getattr(msg, "role", None)
            text = msg.text() if hasattr(msg, "text") else str(msg)

            if role == "assistant" and assistant_text is None:
                assistant_text = text.strip()
            elif role == "user" and assistant_text is not None and user_text is None:
                user_text = text.strip()
                break

        if not user_text or not assistant_text:
            return state

        # Skip short or tool-only exchanges
        if len(user_text) < _MIN_CONTENT_LEN and len(assistant_text) < _MIN_CONTENT_LEN:
            return state
        if assistant_text.startswith("[tool_"):
            return state

        # Build a concise summary for storage
        user_snippet = user_text[:200]
        assistant_snippet = assistant_text[:300]
        summary = f"Q: {user_snippet}\nA: {assistant_snippet}"

        session_id = state.get("session_id")
        try:
            await self._provider.save_memory(
                summary,
                metadata={
                    "session_id": session_id,
                    "auto": True,
                },
            )
        except Exception:
            logger.warning("Failed to auto-save memory", exc_info=True)

        return state
