"""LLM-based message compaction.

When the conversation exceeds max_messages logical user turns or the
estimated token count exceeds max_tokens, older turns are summarized into a
single system message while recent turns are kept verbatim.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from dataclaw.providers.llm.provider import LLMProvider, TextDeltaEvent
from dataclaw.schema import Message

logger = logging.getLogger(__name__)

_SUMMARY_PROMPT = (
    "Write a summary of the entire preceding conversation.\n\n"
    "PRESERVE in the summary:\n"
    "- Key facts, decisions, and conclusions\n"
    "- Approaches used or tested and their outcomes\n"
    "- Errors, failures, or guardrail blocks encountered\n"
    "- User preferences or constraints mentioned\n"
    "- Context the assistant needs to continue helping the user\n\n"
    "- Incomplete tasks or open questions that the assistant should remember\n"
    "Be brief but complete.\n"
    "Give context about the user's initial ask and any specific instructions they provided.\n"
)

# Rough estimate: ~4 characters per token (conservative for English text).
_CHARS_PER_TOKEN = 4


def _estimate_tokens(messages: list[Message]) -> int:
    """Estimate token count from message content length."""
    total_chars = 0
    for msg in messages:
        if isinstance(msg.content, str):
            total_chars += len(msg.content)
        elif isinstance(msg.content, list):
            for block in msg.content:
                if block.get("type") == "text":
                    total_chars += len(block.get("text", ""))
                elif block.get("type") == "tool_result":
                    total_chars += len(str(block.get("content", "")))
                elif block.get("type") == "tool_call":
                    total_chars += len(str(block.get("input", {})))
    return total_chars // _CHARS_PER_TOKEN


def _count_conversation_turns(messages: list[Message]) -> int:
    """Count user-initiated conversation turns.

    Tool-heavy agents can expand one user request into dozens of protocol
    blocks.  Those blocks are implementation detail, not separate
    conversation turns, and counting them made fresh sessions compact almost
    immediately.  A user message is the stable boundary shared by every LLM
    provider, so it is the unit used by the user-facing history limits.

    The fallback preserves useful behavior for synthetic/provider tests that
    contain no user messages at all.
    """
    user_turns = sum(1 for msg in messages if msg.role == "user")
    return user_turns if user_turns else len(messages)


def _recent_turn_split(
    messages: list[Message],
    keep_recent: int,
    *,
    leave_old_turn: bool = True,
) -> int | None:
    """Return a safe split index that keeps recent logical turns intact.

    The returned suffix always begins at a user boundary when user messages
    exist.  Consequently, an assistant ``tool_call`` message and its following
    ``tool_result`` message can never land on opposite sides of compaction.
    At least one older turn must remain available to compact.
    """
    if keep_recent <= 0 or len(messages) <= 1:
        return None

    user_indices = [idx for idx, msg in enumerate(messages) if msg.role == "user"]
    if user_indices:
        if len(user_indices) <= 1 or (
            not leave_old_turn and keep_recent >= len(user_indices)
        ):
            return None
        max_keep = len(user_indices) - 1 if leave_old_turn else len(user_indices)
        keep_turns = min(keep_recent, max_keep)
        if keep_turns <= 0:
            return None
        return user_indices[-keep_turns]

    # Defensive fallback for histories without user messages. Keep top-level
    # messages, but do not split a canonical tool-call/result pair.
    if not leave_old_turn and keep_recent >= len(messages):
        return None
    max_keep = len(messages) - 1 if leave_old_turn else len(messages)
    keep_messages = min(keep_recent, max_keep)
    if keep_messages <= 0:
        return None
    split_idx = len(messages) - keep_messages
    if (
        split_idx > 0
        and messages[split_idx].role == "tool_result"
        and messages[split_idx - 1].role == "tool_call"
    ):
        split_idx -= 1
    return split_idx if split_idx > 0 else None


class LLMSummarizingCompactor:
    """Compacts messages by summarizing older ones via the LLM."""

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

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

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

        # Check token threshold (0 disables)
        estimated_tokens = _estimate_tokens(messages) if max_tokens > 0 else 0
        over_token_limit = max_tokens > 0 and estimated_tokens > max_tokens

        if not over_message_limit and not over_token_limit:
            return messages

        split_idx = _recent_turn_split(messages, keep_recent)
        if split_idx is None:
            return messages

        old = messages[:split_idx]
        recent = messages[split_idx:]

        trigger = []
        if over_message_limit:
            trigger.append(f"turns={turn_count}/{max_messages}")
        if over_token_limit:
            trigger.append(f"tokens~{estimated_tokens}/{max_tokens}")

        logger.info(
            "Compaction triggered (%s): summarizing %d old messages, keeping %d recent",
            ", ".join(trigger),
            len(old),
            len(recent),
        )

        try:
            summary = await self._summarize(old)
        except Exception:
            logger.exception("Compaction summarization failed; returning original messages")
            return messages

        summary_msg = Message.system(f"[Conversation summary]\n{summary}")
        compacted = [summary_msg] + recent

        logger.info(
            "Compaction complete: %d messages → %d messages",
            msg_count,
            len(compacted),
        )

        return compacted

    async def _summarize(self, messages: list[Message]) -> str:
        """Use the LLM to summarize a block of messages."""
        formatted = []
        for msg in messages:
            formatted.append(f"{msg.role}: {_format_message_content(msg)}")

        summary_request = [
            Message.user(f"{_SUMMARY_PROMPT}\n\n" + "\n".join(formatted))
        ]

        chunks: list[str] = []
        async for event in self._llm.stream_turn(
            summary_request,
            system="You are a helpful summarizer.",
            tools=[],
            # Reasoning-class models (gpt-5, codex-mini, o3) otherwise emit
            # scratchpad-shaped output as the final answer. Use "low" because
            # it's accepted by both the standard OpenAI Responses API and the
            # ChatGPT backend (codex) — the standard API's "minimal" tier is
            # rejected by the codex backend. Ignored by providers that don't
            # support these knobs.
            reasoning_effort="low",
            text_verbosity="low",
        ):
            if isinstance(event, TextDeltaEvent):
                chunks.append(event.text)

        summary = "".join(chunks)

        # Loud warning if the summary smells like reasoning scratchpad —
        # short, fragment-heavy, or starts with directive verbs like
        # "Need". Doesn't reject (a bad summary is still better than no
        # summary), just surfaces regressions in logs.
        stripped = summary.strip()
        if len(stripped) < 80 or _looks_like_scratchpad(stripped):
            logger.warning(
                "Compaction summary may be low-quality (len=%d): %s",
                len(stripped),
                stripped[:200],
            )

        return summary


_SCRATCHPAD_HEAD_RE = re.compile(
    r"^\s*(need|let me|i'?ll|i will|first[, ]|step \d+|plan:?|outline:?)\b",
    re.IGNORECASE,
)


def _looks_like_scratchpad(text: str) -> bool:
    """Heuristic: detect reasoning-leak summaries from gpt-5-class models.

    Markers: opens with a directive verb ("Need ..."), or is dominated by
    very short fragments (< 5 words per "sentence"). Cheap to evaluate;
    returns False on normal prose.
    """
    if _SCRATCHPAD_HEAD_RE.match(text):
        return True
    sentences = [s for s in re.split(r"[.!?]\s+", text) if s.strip()]
    if len(sentences) < 3:
        return False
    short = sum(1 for s in sentences if len(s.split()) < 5)
    return short / len(sentences) > 0.5


def _format_message_content(msg: Message) -> str:
    """Format message content, preserving tool call/result structure."""
    if isinstance(msg.content, str):
        return msg.content

    parts = []
    for block in msg.content:
        btype = block.get("type")
        if btype == "text":
            parts.append(block["text"])
        elif btype == "tool_call":
            name = block.get("name", "?")
            tool_input = block.get("input", {})
            parts.append(f"[Tool call: {name}({tool_input})]")
        elif btype == "tool_result":
            call_id = block.get("call_id", "?")
            content = str(block.get("content", ""))
            is_error = block.get("is_error", False)
            status = "ERROR" if is_error else "OK"
            # Truncate very long results in the summary input
            if len(content) > 500:
                content = content[:500] + "...(truncated)"
            parts.append(f"[Tool result ({status}, {call_id}): {content}]")
    return " ".join(parts)
