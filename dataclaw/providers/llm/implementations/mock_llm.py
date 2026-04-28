"""Mock LLM provider for development and testing.

Returns realistic-looking responses without calling any API.
Simulates streaming with character-by-character deltas and
recognizes simple tool-calling patterns.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, AsyncIterator

from dataclaw.providers.llm.provider import (
    BrokerEvent,
    PendingToolCall,
    TextDeltaEvent,
    ToolUseStartEvent,
    TurnCompleteEvent,
)
from dataclaw.schema import Message

# Canned responses keyed by simple keyword matching
_RESPONSES = [
    (["hello", "hi", "hey"], "Hello! I'm Dataclaw, your local data science assistant. How can I help you today?"),
    (["help", "what can"], "I can help you with:\n\n- **Data analysis** — profiling, querying, and exploring datasets\n- **Code generation** — Python, SQL, and DuckDB queries\n- **Model building** — scikit-learn, XGBoost, and more\n- **Visualization** — charts, plots, and dashboards\n\nWhat would you like to work on?"),
    (["test", "ping"], "Pong! Everything is working. The mock LLM backend is active — set `llm.backend` to `anthropic`, `openai`, or `gemini` in your config to use a real model."),
]

_DEFAULT_RESPONSE = (
    "I'm running in **mock mode** — no real LLM is connected. "
    "Here's what I received:\n\n"
    "> {query}\n\n"
    "To connect a real model, go to **Config** and set your LLM backend and API key."
)

# Simulated delay per character (seconds)
_CHAR_DELAY = 0.008


class MockLLM:
    """Mock LLM that returns canned responses with simulated streaming."""

    def __init__(self) -> None:
        self._last_text: str = ""

    async def stream_turn(
        self,
        messages: list[Message],
        *,
        system: str,
        tools: list[dict[str, Any]],
    ) -> AsyncIterator[BrokerEvent]:
        # Extract the last user message
        query = ""
        for msg in reversed(messages):
            if msg.role == "user" and isinstance(msg.content, str):
                query = msg.content
                break

        # Check if this is a tool result turn (continue after tool call)
        for msg in reversed(messages):
            if msg.role == "user" and isinstance(msg.content, list):
                for block in msg.content:
                    if block.get("type") == "tool_result":
                        response = f"Got the tool result. Here's what I found:\n\n```json\n{block.get('content', '{}')}\n```\n\nIs there anything else you'd like me to do?"
                        async for event in self._stream_text(response):
                            yield event
                        return

        # Check for tool-calling keywords when tools are available
        if tools and any(kw in query.lower() for kw in ["search", "look up", "find", "query", "run"]):
            tool = tools[0]  # Pick the first available tool
            call_id = f"call_{uuid.uuid4().hex[:8]}"

            # Emit some thinking text first (don't complete — tool call follows)
            thinking = f"Let me use the **{tool['name']}** tool to help with that.\n\n"
            async for event in self._stream_text(thinking, complete=False):
                yield event

            yield ToolUseStartEvent(tool_name=tool["name"], call_id=call_id)
            yield PendingToolCall(
                call_id=call_id,
                tool_name=tool["name"],
                tool_input={"query": query},
            )
            yield TurnCompleteEvent(has_pending_tool_calls=True)
            return

        # Match a canned response
        response = self._match_response(query)
        async for event in self._stream_text(response):
            yield event

    async def _stream_text(self, text: str, *, complete: bool = True) -> AsyncIterator[BrokerEvent]:
        """Stream text character by character with simulated delay.

        Args:
            complete: If True, yield TurnCompleteEvent at the end.
                      Set False when more events (tool calls) will follow.
        """
        self._last_text = text
        chunk_size = 3
        for i in range(0, len(text), chunk_size):
            chunk = text[i:i + chunk_size]
            yield TextDeltaEvent(text=chunk)
            await asyncio.sleep(_CHAR_DELAY * chunk_size)
        if complete:
            yield TurnCompleteEvent(has_pending_tool_calls=False)

    def _match_response(self, query: str) -> str:
        """Find a canned response or use the default."""
        lower = query.lower()
        for keywords, response in _RESPONSES:
            if any(kw in lower for kw in keywords):
                return response
        return _DEFAULT_RESPONSE.format(query=query[:200])

    def build_tool_result_message(
        self,
        tool_calls: list[PendingToolCall],
        results: list[dict[str, Any]],
        errors: list[Exception | None],
    ) -> list[Message]:
        assistant_content: list[dict[str, Any]] = []
        if self._last_text:
            assistant_content.append({"type": "text", "text": self._last_text})

        for tc in tool_calls:
            assistant_content.append({
                "type": "tool_call",
                "id": tc.call_id,
                "name": tc.tool_name,
                "input": tc.tool_input,
            })

        tool_results: list[dict[str, Any]] = []
        for tc, result, err in zip(tool_calls, results, errors):
            tool_results.append({
                "type": "tool_result",
                "call_id": tc.call_id,
                "content": json.dumps({"error": str(err)}) if err else json.dumps(result, default=str),
                "is_error": err is not None,
            })

        return [
            Message(role="assistant", content=assistant_content),
            Message(role="user", content=tool_results),
        ]
