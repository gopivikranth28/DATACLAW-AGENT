"""Simple drop-old-messages compaction.

When the conversation exceeds max_messages logical user turns or the
estimated token count exceeds max_tokens, older turns are silently dropped,
keeping only the most recent keep_recent turns.

This is a lightweight alternative to LLM-based summarization — no extra
LLM calls, but context from older messages is lost entirely.
"""

from __future__ import annotations

import logging

from dataclaw.providers.compaction.implementations.llm_summarizer import (
    _count_conversation_turns,
    _estimate_tokens,
    _recent_turn_split,
)
from dataclaw.schema import Message

logger = logging.getLogger(__name__)


class DropOldCompactor:
    """Compacts messages by dropping older ones and keeping only the most recent."""

    @classmethod
    def config_schema(cls) -> list:
        from dataclaw.providers.config_field import ConfigField
        return [
            ConfigField(name="max_messages", field_type="int", label="Start After",
                        description="Compact when conversation exceeds this many complete user turns", default=30),
            ConfigField(name="keep_recent", field_type="int", label="Keep Unchanged",
                        description="Number of recent complete user turns to preserve", default=8),
            ConfigField(name="max_tokens", field_type="int", label="Token Threshold",
                        description="Estimated token budget (0 disables token-based trigger)", default=100000),
        ]

    def will_compact(self, messages: list[Message], *, max_messages: int = 30, max_tokens: int = 0) -> bool:
        if max_messages > 0 and _count_conversation_turns(messages) > max_messages:
            return True
        if max_tokens > 0 and _estimate_tokens(messages) > max_tokens:
            return True
        return False

    async def compact(
        self,
        messages: list[Message],
        *,
        max_messages: int = 30,
        keep_recent: int = 8,
        max_tokens: int = 0,
    ) -> list[Message]:
        msg_count = len(messages)
        turn_count = _count_conversation_turns(messages)

        over_message_limit = max_messages > 0 and turn_count > max_messages

        estimated_tokens = _estimate_tokens(messages) if max_tokens > 0 else 0
        over_token_limit = max_tokens > 0 and estimated_tokens > max_tokens

        if not over_message_limit and not over_token_limit:
            return messages

        split_idx = _recent_turn_split(
            messages, keep_recent, leave_old_turn=False
        )
        if split_idx is None:
            return messages

        dropped = split_idx

        trigger = []
        if over_message_limit:
            trigger.append(f"turns={turn_count}/{max_messages}")
        if over_token_limit:
            trigger.append(f"tokens~{estimated_tokens}/{max_tokens}")

        logger.info(
            "Drop-old compaction triggered (%s): dropping %d messages, keeping %d recent",
            ", ".join(trigger),
            dropped,
            msg_count - split_idx,
        )

        return messages[split_idx:]
