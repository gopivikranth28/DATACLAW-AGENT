"""OpenAI Responses API provider.

Uses the openai SDK's ``client.responses.create()`` directly, which
supports both the standard OpenAI API and the ChatGPT backend API
(``chatgpt.com/backend-api/codex``) used by Codex OAuth credentials.

This bypasses LangChain entirely — the Responses API is a different
endpoint from chat completions and needs its own message translation.
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

from openai import AsyncOpenAI

from dataclaw.providers.llm.provider import (
    BrokerEvent,
    PendingToolCall,
    TextDeltaEvent,
    ToolUseStartEvent,
    TurnCompleteEvent,
)
from dataclaw.schema import Message

logger = logging.getLogger(__name__)


class OpenAIResponsesLLM:
    """LLMProvider backed by the OpenAI Responses API."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        default_headers: dict[str, str] | None = None,
    ) -> None:
        self._model = model
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            default_headers=default_headers or {},
        )
        self._last_tool_calls: list[dict[str, Any]] = []
        self.prompt_cache_key: str | None = None

    async def stream_turn(
        self,
        messages: list[Message],
        *,
        system: str,
        tools: list[dict[str, Any]],
        system_dynamic: str = "",
        reasoning_effort: str | None = None,
        text_verbosity: str | None = None,
        **_extra: Any,
    ) -> AsyncIterator[BrokerEvent]:
        # Build input with cache-friendly ordering:
        # 1. Conversation history (stable prefix, grows monotonically)
        # 2. Dynamic system context (memories, skills — changes per turn)
        # 3. Latest user message
        # 4. Current-turn tool results
        input_items = _build_input_ordered(messages, system_dynamic)
        api_tools = _build_tools(tools) if tools else []

        # Diagnostic: surface fan-out so we can see which message is inflating
        # the input. Logs at INFO when items >= 3x messages or items > 200.
        n_msgs = len(messages)
        n_items = len(input_items)
        if n_msgs and (n_items >= n_msgs * 3 or n_items > 200):
            per_msg_counts: list[tuple[int, str, int]] = []
            for idx, msg in enumerate(messages):
                produced = len(_build_input([msg]))
                per_msg_counts.append((idx, msg.role, produced))
            top = sorted(per_msg_counts, key=lambda x: -x[2])[:5]
            logger.info(
                "OpenAIResponses input fan-out: messages=%d input_items=%d. "
                "Top-emitting messages: %s",
                n_msgs, n_items,
                [f"#{i}({r}):{c}items" for i, r, c in top],
            )

        kwargs: dict[str, Any] = {
            "model": self._model,
            "input": input_items,
            "stream": True,
            "store": False,
        }
        if self.prompt_cache_key:
            kwargs["prompt_cache_key"] = self.prompt_cache_key
        # Static system prompt goes in instructions (stable, cached separately)
        if system:
            kwargs["instructions"] = system
        if api_tools:
            kwargs["tools"] = api_tools
        # Reasoning / verbosity controls — used by the compactor to keep
        # gpt-5-class reasoning models from emitting scratchpad output as
        # the final answer. Not set by default for normal chat turns.
        if reasoning_effort:
            kwargs["reasoning"] = {"effort": reasoning_effort}
        if text_verbosity:
            kwargs["text"] = {"verbosity": text_verbosity}

        self._last_tool_calls = []
        pending_calls: dict[str, dict[str, Any]] = {}
        seen_call_ids: set[str] = set()
        reasoning_chunks: list[str] = []

        stream = await self._client.responses.create(**kwargs)

        async for event in stream:
            event_type = event.type

            # Text deltas
            if event_type == "response.output_text.delta":
                yield TextDeltaEvent(text=event.delta)

            # Reasoning text — diagnostic only. Reasoning models (gpt-5,
            # o3, codex-mini) emit these alongside or instead of normal
            # output_text deltas. Capturing them lets us see in logs
            # whether bad final-output text came from reasoning leakage.
            elif event_type in (
                "response.reasoning_summary_text.delta",
                "response.reasoning.delta",
            ):
                delta = getattr(event, "delta", "") or ""
                if delta:
                    reasoning_chunks.append(delta)

            # Tool call argument deltas — track start
            elif event_type == "response.function_call_arguments.delta":
                call_id = event.item_id
                if call_id not in seen_call_ids:
                    seen_call_ids.add(call_id)
                if call_id not in pending_calls:
                    pending_calls[call_id] = {"id": call_id, "name": "", "args": ""}
                pending_calls[call_id]["args"] += event.delta

            # Output item done — capture completed tool calls and text
            elif event_type == "response.output_item.done":
                item = event.item
                if item.type == "function_call":
                    call_id = item.id
                    name = item.name
                    raw_args = item.arguments
                    try:
                        args = json.loads(raw_args) if raw_args else {}
                    except json.JSONDecodeError:
                        args = {}

                    # Emit tool start if we haven't yet
                    if call_id not in seen_call_ids:
                        seen_call_ids.add(call_id)
                    yield ToolUseStartEvent(tool_name=name, call_id=call_id)

                    self._last_tool_calls.append({
                        "id": call_id,
                        "name": name,
                        "args": args,
                    })

            # Response completed
            elif event_type == "response.completed":
                break

        if reasoning_chunks:
            joined = "".join(reasoning_chunks)
            logger.debug(
                "OpenAIResponses reasoning trace (%d chars): %s",
                len(joined),
                joined[:500],
            )

        # Yield pending tool calls
        for tc in self._last_tool_calls:
            yield PendingToolCall(
                call_id=tc["id"],
                tool_name=tc["name"],
                tool_input=tc["args"],
            )

        yield TurnCompleteEvent(has_pending_tool_calls=bool(self._last_tool_calls))

    def build_tool_result_message(
        self,
        tool_calls: list[PendingToolCall],
        results: list[dict[str, Any]],
        errors: list[Exception | None],
    ) -> list[Message]:
        assistant_content: list[dict[str, Any]] = []
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
            Message.tool_call(assistant_content),
            Message.tool_result(tool_results),
        ]


# ── Helpers ──────────────────────────────────────────────────────────────────


def _fc_id(raw_id: str) -> str:
    """Ensure a tool call ID has the ``fc_`` prefix the Responses API requires."""
    if raw_id.startswith("fc_"):
        return raw_id
    return f"fc_{raw_id}"


def _build_input(messages: list[Message]) -> list[dict[str, Any]]:
    """Convert DataClaw messages to Responses API input format."""
    items: list[dict[str, Any]] = []
    for msg in messages:
        role = msg.role
        content = msg.content

        if role == "system":
            # Compaction emits Message.system(summary). Surface it as a
            # `developer` input item so the summarized context actually
            # reaches the model. (The static system prompt itself is sent
            # via `instructions=` separately.)
            if isinstance(content, str) and content:
                items.append({"role": "developer", "content": content})
            elif isinstance(content, list):
                text = "".join(
                    b.get("text", "") for b in content if b.get("type") == "text"
                )
                if text:
                    items.append({"role": "developer", "content": text})

        elif role == "user":
            if isinstance(content, str):
                items.append({"role": "user", "content": content})
            elif isinstance(content, list):
                for block in content:
                    if block.get("type") == "tool_result":
                        items.append({
                            "type": "function_call_output",
                            "call_id": _fc_id(block["call_id"]),
                            "output": block.get("content", ""),
                        })
                    elif block.get("type") == "text" and block.get("text"):
                        items.append({"role": "user", "content": block["text"]})

        elif role == "assistant":
            if isinstance(content, str) and content:
                items.append({"role": "assistant", "content": content})
            elif isinstance(content, list):
                text_parts = []
                for block in content:
                    if block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                    elif block.get("type") == "tool_call":
                        # Emit text before tool call
                        if text_parts:
                            items.append({"role": "assistant", "content": "".join(text_parts)})
                            text_parts = []
                        fc_id = _fc_id(block["id"])
                        items.append({
                            "type": "function_call",
                            "id": fc_id,
                            "name": block["name"],
                            "arguments": json.dumps(block.get("input", {})),
                            "call_id": fc_id,
                        })
                if text_parts:
                    items.append({"role": "assistant", "content": "".join(text_parts)})

        elif role == "tool_call":
            if isinstance(content, list):
                text_parts = []
                for block in content:
                    if block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                    elif block.get("type") == "tool_call":
                        if text_parts:
                            items.append({"role": "assistant", "content": "".join(text_parts)})
                            text_parts = []
                        fc_id = _fc_id(block["id"])
                        items.append({
                            "type": "function_call",
                            "id": fc_id,
                            "name": block["name"],
                            "arguments": json.dumps(block.get("input", {})),
                            "call_id": fc_id,
                        })
                if text_parts:
                    items.append({"role": "assistant", "content": "".join(text_parts)})

        elif role == "tool_result":
            if isinstance(content, list):
                for block in content:
                    if block.get("type") == "tool_result":
                        items.append({
                            "type": "function_call_output",
                            "call_id": _fc_id(block["call_id"]),
                            "output": block.get("content", ""),
                        })

    return items


def _build_input_ordered(
    messages: list[Message],
    system_dynamic: str = "",
) -> list[dict[str, Any]]:
    """Build input array with cache-friendly ordering.

    Order:
    1. Conversation history (all but trailing user msg + current-turn tool results)
    2. Dynamic system context (memories, skills) as a developer message
    3. Latest user message
    4. Current-turn tool results (tool_call + tool_result from the current turn)

    This keeps the prefix (instructions + history) stable across turns so
    the Responses API prompt cache can match.
    """
    all_items = _build_input(messages)

    # Split: find the last user message and any tool results after it
    # (tool results from the current agent loop turn)
    last_user_idx = -1
    for i, item in enumerate(all_items):
        if item.get("role") == "user":
            last_user_idx = i

    if last_user_idx < 0:
        # No user message found — just return everything with dynamic prepended
        result = []
        if system_dynamic:
            result.append({"role": "developer", "content": system_dynamic})
        result.extend(all_items)
        return result

    # Everything before the last user message is stable history
    history = all_items[:last_user_idx]
    # The last user message
    last_user_msg = all_items[last_user_idx]
    # Anything after the last user message (current-turn tool results)
    trailing = all_items[last_user_idx + 1:]

    result = list(history)
    if system_dynamic:
        result.append({"role": "developer", "content": system_dynamic})
    result.append(last_user_msg)
    result.extend(trailing)
    return result


def _build_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert DataClaw tool definitions to Responses API function tools."""
    return [
        {
            "type": "function",
            "name": t["name"],
            "description": t.get("description", ""),
            "parameters": t.get("parameters", {"type": "object", "properties": {}}),
        }
        for t in tools
    ]
