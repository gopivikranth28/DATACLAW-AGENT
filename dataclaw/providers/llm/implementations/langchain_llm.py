"""LangChain-based LLM provider.

Wraps any LangChain BaseChatModel (Anthropic, OpenAI, Gemini, etc.)
and translates between Dataclaw's Message class and LangChain message
objects at this boundary only.
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from dataclaw.providers.llm.provider import (
    BrokerEvent,
    PendingToolCall,
    TextDeltaEvent,
    ToolUseStartEvent,
    TurnCompleteEvent,
)
from dataclaw.schema import Message

logger = logging.getLogger(__name__)


class LangChainLLM:
    """LLM provider backed by a LangChain BaseChatModel."""

    def __init__(self, model: BaseChatModel) -> None:
        self._model = model
        self._last_ai_message: AIMessage | None = None

    async def stream_turn(
        self,
        messages: list[Message],
        *,
        system: str,
        tools: list[dict[str, Any]],
    ) -> AsyncIterator[BrokerEvent]:
        lc_tools = _to_lc_tools(tools)
        bound = self._model.bind_tools(lc_tools) if lc_tools else self._model

        lc_messages: list[BaseMessage] = [SystemMessage(content=system)]
        lc_messages.extend(_to_lc_messages(messages))

        accumulated: AIMessage | None = None
        seen_tool_indices: set[int] = set()

        async for chunk in bound.astream(lc_messages):
            accumulated = chunk if accumulated is None else accumulated + chunk

            # Text deltas
            if isinstance(chunk.content, str) and chunk.content:
                yield TextDeltaEvent(text=chunk.content)
            elif isinstance(chunk.content, list):
                for block in chunk.content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block.get("text", "")
                        if text:
                            yield TextDeltaEvent(text=text)

            # Tool call starts
            for tc_chunk in getattr(chunk, "tool_call_chunks", None) or []:
                idx = tc_chunk.get("index", 0)
                if idx not in seen_tool_indices and tc_chunk.get("name"):
                    seen_tool_indices.add(idx)
                    yield ToolUseStartEvent(
                        tool_name=tc_chunk["name"],
                        call_id=tc_chunk.get("id", ""),
                    )

        self._last_ai_message = accumulated

        tool_calls = getattr(accumulated, "tool_calls", []) if accumulated else []
        for tc in tool_calls:
            args = tc.get("args", {})
            yield PendingToolCall(
                call_id=tc["id"],
                tool_name=tc["name"],
                tool_input=args if isinstance(args, dict) else {},
            )

        yield TurnCompleteEvent(has_pending_tool_calls=bool(tool_calls))

    def build_tool_result_message(
        self,
        tool_calls: list[PendingToolCall],
        results: list[dict[str, Any]],
        errors: list[Exception | None],
    ) -> list[Message]:
        """Build Message objects to append after tool execution."""
        assistant_content: list[dict[str, Any]] = []
        if self._last_ai_message:
            if isinstance(self._last_ai_message.content, str) and self._last_ai_message.content:
                assistant_content.append({"type": "text", "text": self._last_ai_message.content})
            elif isinstance(self._last_ai_message.content, list):
                for block in self._last_ai_message.content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        assistant_content.append(block)

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


# ── Helpers ──────────────────────────────────────────────────────────────────


def _to_lc_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert canonical tool definitions to LangChain tool format."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("parameters", {"type": "object", "properties": {}}),
            },
        }
        for t in tools
    ]


def _to_lc_messages(messages: list[Message]) -> list[BaseMessage]:
    """Convert Dataclaw Message objects to LangChain message objects.

    This is the only place LangChain types are created from our Messages.
    """
    result: list[BaseMessage] = []
    for msg in messages:
        role = msg.role
        content = msg.content

        if role == "user":
            if isinstance(content, str):
                result.append(HumanMessage(content=content))
            elif isinstance(content, list):
                for block in content:
                    if block.get("type") == "tool_result":
                        result.append(
                            ToolMessage(
                                content=block.get("content", ""),
                                tool_call_id=block["call_id"],
                            )
                        )
                    else:
                        text = block.get("text", "")
                        if text:
                            result.append(HumanMessage(content=text))

        elif role == "assistant":
            if isinstance(content, str):
                result.append(AIMessage(content=content))
            elif isinstance(content, list):
                text_parts: list[str] = []
                lc_tool_calls: list[dict[str, Any]] = []
                for block in content:
                    btype = block.get("type")
                    if btype == "text":
                        text_parts.append(block.get("text", ""))
                    elif btype == "tool_call":
                        lc_tool_calls.append({
                            "id": block["id"],
                            "name": block["name"],
                            "args": block.get("input", {}),
                            "type": "tool_call",
                        })
                result.append(
                    AIMessage(
                        content="".join(text_parts),
                        tool_calls=lc_tool_calls,
                    )
                )

    return result
