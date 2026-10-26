"""LLMProvider protocol and streaming event types.

The LLM provider abstracts all LLM backends behind a single protocol.
It streams BrokerEvents during a turn and builds tool result messages
in canonical format.
"""

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


@dataclass
class UsageEvent:
    """Token accounting for one LLM turn, emitted before TurnCompleteEvent.

    ``input_tokens`` is the provider-reported prompt size including cached
    tokens; ``cached_input_tokens`` and ``reasoning_tokens`` are the subsets
    served from the prompt cache and spent on hidden reasoning (0 when the
    provider does not report them).  Consumers may ignore this event.
    """
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    reasoning_tokens: int = 0


@dataclass
class ErrorEvent:
    """The provider reported a terminal failure for this turn.

    Yielded instead of TurnCompleteEvent (e.g. Responses ``response.failed``
    or a truncated ``response.incomplete``).  Providers raise
    ``LLMStreamError`` right after yielding it, so a consumer that does not
    recognise the event still stops instead of treating the turn as a
    silent, empty success.
    """
    message: str
    code: str | None = None


class LLMStreamError(RuntimeError):
    """Raised by a provider after it yields an ErrorEvent."""

    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


class StructuredOutputError(RuntimeError):
    """The model's reply could not be read as an object matching the schema."""


BrokerEvent = (
    TextDeltaEvent
    | ToolUseStartEvent
    | PendingToolCall
    | UsageEvent
    | ErrorEvent
    | TurnCompleteEvent
)


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


@runtime_checkable
class StructuredOutputProvider(Protocol):
    """Optional LLMProvider capability: one non-streaming, schema-shaped reply.

    Not part of LLMProvider so existing providers stay valid. Callers use
    ``dataclaw.providers.llm.structured.structured_output(llm, ...)``, which
    uses this method when a provider has it and a forced-tool-call fallback
    otherwise.
    """

    async def structured_output(
        self,
        messages: list[Message],
        schema: dict[str, Any],
        *,
        system: str = "",
        name: str = "response",
        strict: bool = False,
    ) -> dict[str, Any]:
        """Answer ``messages`` with a JSON object conforming to ``schema``.

        Args:
            messages: Conversation to answer (canonical Messages).
            schema: JSON Schema of the reply; its root must be an object.
            system: System prompt for this call.
            name: Schema / tool name (``^[A-Za-z0-9_-]+$``).
            strict: Ask for strict schema enforcement where the API offers
                it (OpenAI). The schema must then meet that API's strict
                subset (every property required, no additional properties).

        Raises:
            StructuredOutputError: The reply was not a JSON object or is
                missing a required top-level property.
            LLMStreamError: The provider reported a failed response.
        """
        ...
