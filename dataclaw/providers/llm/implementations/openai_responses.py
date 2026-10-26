"""OpenAI Responses API provider.

Uses the openai SDK's ``client.responses.create()`` directly, which
supports both the standard OpenAI API and the ChatGPT backend API
(``chatgpt.com/backend-api/codex``) used by Codex OAuth credentials.

This bypasses LangChain entirely — the Responses API is a different
endpoint from chat completions and needs its own message translation.

Requests are stateless (``store=False``; the ChatGPT backend requires it),
so everything the model needs on the next request of a tool loop is sent
back explicitly: function calls by their ``call_id`` and the turn's
reasoning items via their ``encrypted_content``.
"""

from __future__ import annotations

import json
import logging
from collections import OrderedDict
from contextvars import ContextVar
from typing import Any, AsyncIterator

from openai import AsyncOpenAI

from dataclaw.providers.llm.capabilities import (
    OPENAI,
    resolve_reasoning_effort,
    supports_reasoning_effort,
    supports_text_verbosity,
)
from dataclaw.providers.llm.provider import (
    BrokerEvent,
    ErrorEvent,
    LLMStreamError,
    PendingToolCall,
    TextDeltaEvent,
    ToolUseStartEvent,
    TurnCompleteEvent,
    UsageEvent,
)
from dataclaw.schema import Message

logger = logging.getLogger(__name__)

# Tag for Message.provider_state written and replayed by this provider.
PROVIDER_TAG = "openai_responses"

# Upper bound on remembered tool-call turns; see OpenAIResponsesLLM._turns.
_TURN_STATE_LIMIT = 256


class OpenAIResponsesLLM:
    """LLMProvider backed by the OpenAI Responses API."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        default_headers: dict[str, str] | None = None,
        *,
        default_reasoning_effort: str | None = None,
        compat: bool = False,
    ) -> None:
        """
        Args:
            default_reasoning_effort: Effort used on turns that don't set one
                (the backend's configured ``reasoning_effort``).
            compat: The endpoint is a third-party Responses implementation
                (Open Responses). OpenAI-specific extras (prompt_cache_key,
                text verbosity) are not sent, and reasoning effort only when
                the model catalog vouches for it.
        """
        self._model = model
        self._default_reasoning_effort = default_reasoning_effort or None
        self._compat = compat
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            default_headers=default_headers or {},
        )
        # A provider instance is shared by concurrent runs.  The cache key is
        # request state, so keep it task-local instead of allowing one thread
        # to overwrite another thread's value between request construction and
        # dispatch.
        self._prompt_cache_key: ContextVar[str | None] = ContextVar(
            f"openai_prompt_cache_key_{id(self)}", default=None
        )
        # Reasoning items of turns that ended in tool calls, keyed by call_id
        # (unique across runs, unlike "the last turn" on a shared instance).
        # Consumed by build_tool_result_message.
        self._turns: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()

    @property
    def prompt_cache_key(self) -> str | None:
        return self._prompt_cache_key.get()

    @prompt_cache_key.setter
    def prompt_cache_key(self, value: str | None) -> None:
        self._prompt_cache_key.set(value)

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

        kwargs = self._request_kwargs(
            input_items,
            system,
            api_tools,
            reasoning_effort or self._default_reasoning_effort,
            text_verbosity,
        )

        completed_tool_calls: list[dict[str, Any]] = []
        started_call_ids: set[str] = set()
        reasoning_items: list[dict[str, Any]] = []
        reasoning_chunks: list[str] = []
        completed = False

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

            # A function call item has started — name and call_id are known
            # before the arguments stream in.
            elif event_type == "response.output_item.added":
                item = event.item
                if item.type == "function_call":
                    call_id = _call_id(item)
                    if call_id not in started_call_ids:
                        started_call_ids.add(call_id)
                        yield ToolUseStartEvent(tool_name=item.name, call_id=call_id)

            # Output item done — capture completed tool calls and reasoning
            elif event_type == "response.output_item.done":
                item = event.item
                if item.type == "function_call":
                    # ``call_id`` pairs the call with its function_call_output;
                    # ``id`` is the output item's own id (fc_...), a different
                    # value.
                    call_id = _call_id(item)
                    raw_args = item.arguments
                    try:
                        args = json.loads(raw_args) if raw_args else {}
                    except json.JSONDecodeError:
                        args = {}

                    if call_id not in started_call_ids:
                        started_call_ids.add(call_id)
                        yield ToolUseStartEvent(tool_name=item.name, call_id=call_id)

                    completed_tool_calls.append({
                        "id": call_id,
                        "name": item.name,
                        "args": args,
                    })
                elif item.type == "reasoning":
                    replay = _reasoning_replay_item(item)
                    if replay is not None:
                        reasoning_items.append(replay)

            # Terminal events
            elif event_type == "response.completed":
                completed = True
                usage = _usage_event(getattr(event.response, "usage", None))
                if usage is not None:
                    yield usage
                break

            elif event_type in ("response.failed", "response.incomplete", "error"):
                if event_type != "error":
                    usage = _usage_event(getattr(event.response, "usage", None))
                    if usage is not None:
                        yield usage
                message, code = _describe_failure(event)
                logger.warning("OpenAIResponses turn failed (%s): %s", code, message)
                yield ErrorEvent(message=message, code=code)
                raise LLMStreamError(message, code=code)

        if not completed:
            message = "Responses stream ended before response.completed"
            logger.warning("OpenAIResponses: %s", message)
            yield ErrorEvent(message=message, code="stream_incomplete")
            raise LLMStreamError(message, code="stream_incomplete")

        if reasoning_chunks:
            joined = "".join(reasoning_chunks)
            logger.debug(
                "OpenAIResponses reasoning trace (%d chars): %s",
                len(joined),
                joined[:500],
            )

        if completed_tool_calls:
            for tc in completed_tool_calls:
                self._turns[tc["id"]] = reasoning_items
            while len(self._turns) > _TURN_STATE_LIMIT:
                self._turns.popitem(last=False)

        # Yield pending tool calls
        for tc in completed_tool_calls:
            yield PendingToolCall(
                call_id=tc["id"],
                tool_name=tc["name"],
                tool_input=tc["args"],
            )

        yield TurnCompleteEvent(has_pending_tool_calls=bool(completed_tool_calls))

    def _request_kwargs(
        self,
        input_items: list[dict[str, Any]],
        system: str,
        api_tools: list[dict[str, Any]],
        reasoning_effort: str | None,
        text_verbosity: str | None,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "input": input_items,
            "stream": True,
            "store": False,
        }
        if self.prompt_cache_key and not self._compat:
            kwargs["prompt_cache_key"] = self.prompt_cache_key
        # Static system prompt goes in instructions (stable, cached separately)
        if system:
            kwargs["instructions"] = system
        if api_tools:
            kwargs["tools"] = api_tools
        reasoning_model = supports_reasoning_effort(OPENAI, self._model, catalog_only=self._compat)
        if reasoning_model:
            # With store=False the server keeps nothing between requests;
            # ask for the encrypted reasoning so it can be replayed.
            kwargs["include"] = ["reasoning.encrypted_content"]
        # Reasoning / verbosity controls — used by the compactor to keep
        # gpt-5-class reasoning models from emitting scratchpad output as
        # the final answer. Not set by default for normal chat turns, and
        # dropped for models that would reject them.
        effort = resolve_reasoning_effort(
            OPENAI, self._model, reasoning_effort, catalog_only=self._compat
        )
        if effort:
            kwargs["reasoning"] = {"effort": effort}
        if text_verbosity:
            if not self._compat and supports_text_verbosity(OPENAI, self._model):
                kwargs["text"] = {"verbosity": text_verbosity}
            else:
                logger.debug(
                    "Skipping text_verbosity=%r: not supported by %r",
                    text_verbosity, self._model,
                )
        return kwargs

    async def structured_output(
        self,
        messages: list[Message],
        schema: dict[str, Any],
        *,
        system: str = "",
        name: str = "response",
        strict: bool = False,
    ) -> dict[str, Any]:
        """Schema-shaped reply (see ``StructuredOutputProvider``).

        Uses the Responses ``text.format`` json_schema response format. It is
        streamed like a normal turn because the ChatGPT (Codex) backend only
        accepts streaming requests. Third-party (compat) endpoints use the
        tool-call fallback, since Open Responses servers may not implement
        response formats.
        """
        from dataclaw.providers.llm.structured import (
            check_required,
            parse_json_object,
            tool_call_structured_output,
        )

        if self._compat:
            return await tool_call_structured_output(self, messages, schema, system=system, name=name)

        kwargs = self._request_kwargs(_build_input_ordered(messages, ""), system, [], None, None)
        kwargs["text"] = {
            "format": {"type": "json_schema", "name": name, "schema": schema, "strict": strict},
        }
        chunks: list[str] = []
        completed = False
        stream = await self._client.responses.create(**kwargs)
        async for event in stream:
            if event.type == "response.output_text.delta":
                chunks.append(event.delta)
            elif event.type == "response.completed":
                completed = True
                break
            elif event.type in ("response.failed", "response.incomplete", "error"):
                message, code = _describe_failure(event)
                raise LLMStreamError(message, code=code)
        if not completed:
            raise LLMStreamError("Responses stream ended before response.completed", code="stream_incomplete")
        return check_required(parse_json_object("".join(chunks)), schema)

    def build_tool_result_message(
        self,
        tool_calls: list[PendingToolCall],
        results: list[dict[str, Any]],
        errors: list[Exception | None],
    ) -> list[Message]:
        reasoning = next(
            (self._turns[tc.call_id] for tc in tool_calls if tc.call_id in self._turns),
            None,
        )
        for tc in tool_calls:
            self._turns.pop(tc.call_id, None)

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

        provider_state = (
            {"provider": PROVIDER_TAG, "reasoning": reasoning} if reasoning else None
        )
        return [
            Message.tool_call(assistant_content, provider_state=provider_state),
            Message.tool_result(tool_results),
        ]


# ── Helpers ──────────────────────────────────────────────────────────────────


def _call_id(item: Any) -> str:
    """The id that pairs a function_call with its function_call_output."""
    return getattr(item, "call_id", None) or getattr(item, "id", None) or ""


def _reasoning_replay_item(item: Any) -> dict[str, Any] | None:
    """Input-shaped copy of a reasoning output item, or None if unusable.

    Without ``encrypted_content`` a reasoning item can only be referenced by
    id, which fails with store=False, so such items are not replayed. The
    item ``id`` is omitted for the same reason (the Codex client sends
    reasoning items the same way); the encrypted content carries the state.
    """
    encrypted = getattr(item, "encrypted_content", None)
    if not encrypted:
        return None
    summary = [
        {"type": "summary_text", "text": getattr(s, "text", "")}
        for s in (getattr(item, "summary", None) or [])
    ]
    return {"type": "reasoning", "summary": summary, "encrypted_content": encrypted}


def _usage_event(usage: Any) -> UsageEvent | None:
    """Convert a Responses ``ResponseUsage`` to a UsageEvent."""
    if usage is None:
        return None
    input_details = getattr(usage, "input_tokens_details", None)
    output_details = getattr(usage, "output_tokens_details", None)
    return UsageEvent(
        input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
        output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
        cached_input_tokens=int(getattr(input_details, "cached_tokens", 0) or 0),
        reasoning_tokens=int(getattr(output_details, "reasoning_tokens", 0) or 0),
    )


def _describe_failure(event: Any) -> tuple[str, str | None]:
    """Human-readable message and code for a failed/incomplete/error event."""
    if event.type == "error":
        code = getattr(event, "code", None)
        return f"Model API error: {getattr(event, 'message', '') or 'unknown error'}", code
    response = getattr(event, "response", None)
    if event.type == "response.incomplete":
        details = getattr(response, "incomplete_details", None)
        reason = getattr(details, "reason", None) or "unknown"
        return f"Model response incomplete ({reason})", f"incomplete:{reason}"
    error = getattr(response, "error", None)
    code = getattr(error, "code", None)
    message = getattr(error, "message", None) or "unknown error"
    return f"Model response failed: {message}", code


def _replay_reasoning(msg: Message) -> list[dict[str, Any]]:
    """Reasoning items this provider stored on a tool_call message."""
    state = msg.provider_state
    if not state or state.get("provider") != PROVIDER_TAG:
        return []
    return [r for r in state.get("reasoning") or [] if isinstance(r, dict)]


def _function_call_item(block: dict[str, Any]) -> dict[str, Any]:
    # Only ``call_id`` is sent. The output item ``id`` (fc_...) is optional
    # on input, and naming items by id under store=False makes the API
    # demand their paired reasoning items by id as well.
    return {
        "type": "function_call",
        "call_id": block["id"],
        "name": block["name"],
        "arguments": json.dumps(block.get("input", {})),
    }


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
                            "call_id": block["call_id"],
                            "output": block.get("content", ""),
                        })
                    elif block.get("type") == "text" and block.get("text"):
                        items.append({"role": "user", "content": block["text"]})

        elif role == "assistant" and isinstance(content, str):
            if content:
                items.append({"role": "assistant", "content": content})

        elif role in ("assistant", "tool_call") and isinstance(content, list):
            # The turn's reasoning preceded its output in the response, so
            # replay it first.
            items.extend(_replay_reasoning(msg))
            text_parts: list[str] = []
            for block in content:
                if block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
                elif block.get("type") == "tool_call":
                    # Emit text before tool call
                    if text_parts:
                        items.append({"role": "assistant", "content": "".join(text_parts)})
                        text_parts = []
                    items.append(_function_call_item(block))
            if text_parts:
                items.append({"role": "assistant", "content": "".join(text_parts)})

        elif role == "tool_result":
            if isinstance(content, list):
                for block in content:
                    if block.get("type") == "tool_result":
                        items.append({
                            "type": "function_call_output",
                            "call_id": block["call_id"],
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
