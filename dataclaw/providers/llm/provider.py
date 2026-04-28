"""LLMProvider protocol and streaming event types.

The LLM provider abstracts all LLM backends behind a single protocol.
It streams BrokerEvents during a turn and builds tool result messages
in canonical format.
"""

from __future__ import annotations

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, AsyncIterator, Protocol, runtime_checkable, TYPE_CHECKING

if TYPE_CHECKING:
    from dataclaw.schema import Message


# ── Streaming event types ───────────────────────────────────────────────────

@dataclass
class TextDeltaEvent:
    """A chunk of streamed text from the LLM."""
    text: str


@dataclass
class ToolUseStartEvent:
    """The LLM has started a tool call (name and ID known, args still streaming)."""
    tool_name: str
    call_id: str


@dataclass
class PendingToolCall:
    """A fully-formed tool call ready for dispatch."""
    call_id: str
    tool_name: str
    tool_input: dict[str, Any]


@dataclass
class TurnCompleteEvent:
    """The LLM turn has finished streaming."""
    has_pending_tool_calls: bool = False
    skip_persist: bool = False  # True when an external system handles message persistence


BrokerEvent = TextDeltaEvent | ToolUseStartEvent | PendingToolCall | TurnCompleteEvent


# ── Provider protocol ───────────────────────────────────────────────────────

@runtime_checkable
class LLMProvider(Protocol):
    """Protocol for LLM backend implementations."""

    def stream_turn(
        self,
        messages: list[Message],
        *,
        system: str,
        tools: list[dict[str, Any]],
    ) -> AsyncIterator[BrokerEvent]:
        """Stream a single LLM turn, yielding BrokerEvents."""
        ...

    def build_tool_result_message(
        self,
        tool_calls: list[PendingToolCall],
        results: list[dict[str, Any]],
        errors: list[Exception | None],
    ) -> list[Message]:
        """Build Message objects to append after tool execution."""
        ...
