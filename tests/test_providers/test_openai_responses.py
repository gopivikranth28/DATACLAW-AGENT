"""Tests for the OpenAI Responses API provider (codex backend).

Uses a fake ``responses.create`` that records the request and replays
scripted stream events, so no network access is needed.
"""

from __future__ import annotations

import json
from types import SimpleNamespace as NS
from typing import Any

import pytest

from dataclaw.providers.llm.implementations.openai_responses import (
    OpenAIResponsesLLM,
    _build_input,
    _build_input_ordered,
)
from dataclaw.providers.llm.provider import (
    ErrorEvent,
    LLMStreamError,
    PendingToolCall,
    TextDeltaEvent,
    ToolUseStartEvent,
    TurnCompleteEvent,
    UsageEvent,
)
from dataclaw.schema import Message


class _FakeResponses:
    def __init__(self, *streams: list[Any]) -> None:
        self.streams = list(streams)
        self.requests: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any):
        self.requests.append(kwargs)
        events = self.streams.pop(0)

        async def gen():
            for event in events:
                yield event

        return gen()


def _llm(*streams: list[Any], model: str = "gpt-5.5") -> tuple[OpenAIResponsesLLM, _FakeResponses]:
    llm = OpenAIResponsesLLM(api_key="test", base_url="http://localhost/v1", model=model)
    fake = _FakeResponses(*streams)
    llm._client = NS(responses=fake)  # type: ignore[assignment]
    return llm, fake


def _usage(inp: int = 50, out: int = 10, cached: int = 40, reasoning: int = 6) -> NS:
    return NS(
        input_tokens=inp,
        output_tokens=out,
        input_tokens_details=NS(cached_tokens=cached),
        output_tokens_details=NS(reasoning_tokens=reasoning),
    )


def _completed(usage: NS | None = None) -> NS:
    return NS(type="response.completed", response=NS(usage=usage or _usage()))


def _fc_item(call_id: str = "call_abc", item_id: str = "fc_123", name: str = "search", args: str = '{"q": "x"}') -> NS:
    return NS(type="function_call", id=item_id, call_id=call_id, name=name, arguments=args)


def _reasoning_item(enc: str | None = "ENC-1") -> NS:
    return NS(type="reasoning", id="rs_1", summary=[NS(type="summary_text", text="thinking")], encrypted_content=enc)


def _tool_turn() -> list[NS]:
    return [
        NS(type="response.output_item.done", item=_reasoning_item()),
        NS(type="response.output_item.added", item=_fc_item(args="")),
        NS(type="response.function_call_arguments.delta", item_id="fc_123", delta='{"q": "x"}'),
        NS(type="response.output_item.done", item=_fc_item()),
        _completed(),
    ]


async def _run(llm: OpenAIResponsesLLM, messages: list[Message], **kwargs: Any) -> list[Any]:
    kwargs.setdefault("system", "STATIC")
    kwargs.setdefault("tools", [])
    return [e async for e in llm.stream_turn(messages, **kwargs)]


# ── input building ─────────────────────────────────────────────────────────


def test_build_input_ordered_places_dynamic_before_last_user():
    messages = [
        Message.system("[Conversation summary]\nS"),
        Message.user("first"),
        Message.assistant("answer"),
        Message.user("second"),
        Message.tool_call([{"type": "tool_call", "id": "call_1", "name": "search", "input": {"q": 1}}]),
        Message.tool_result([{"type": "tool_result", "call_id": "call_1", "content": "R", "is_error": False}]),
    ]
    items = _build_input_ordered(messages, "DYNAMIC")
    assert items == [
        {"role": "developer", "content": "[Conversation summary]\nS"},
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "answer"},
        {"role": "developer", "content": "DYNAMIC"},
        {"role": "user", "content": "second"},
        {"type": "function_call", "call_id": "call_1", "name": "search", "arguments": '{"q": 1}'},
        {"type": "function_call_output", "call_id": "call_1", "output": "R"},
    ]


def test_build_input_uses_call_id_verbatim_and_no_item_id():
    items = _build_input([
        Message.tool_call([{"type": "tool_call", "id": "toolu_9", "name": "t", "input": {}}]),
        Message.tool_result([{"type": "tool_result", "call_id": "toolu_9", "content": "", "is_error": False}]),
    ])
    assert items[0]["call_id"] == items[1]["call_id"] == "toolu_9"
    assert "id" not in items[0]


def test_build_input_replays_reasoning_before_function_calls():
    msg = Message.tool_call(
        [
            {"type": "text", "text": "Checking."},
            {"type": "tool_call", "id": "call_1", "name": "search", "input": {}},
        ],
        provider_state={
            "provider": "openai_responses",
            "reasoning": [{"type": "reasoning", "summary": [], "encrypted_content": "ENC"}],
        },
    )
    items = _build_input([msg])
    assert [i.get("type") or i.get("role") for i in items] == ["reasoning", "assistant", "function_call"]
    assert items[0]["encrypted_content"] == "ENC"


def test_build_input_ignores_foreign_provider_state():
    msg = Message.tool_call(
        [{"type": "tool_call", "id": "c", "name": "s", "input": {}}],
        provider_state={"provider": "ChatAnthropic", "content": [{"type": "thinking"}]},
    )
    assert [i["type"] for i in _build_input([msg])] == ["function_call"]


# ── request kwargs ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_request_includes_encrypted_reasoning_and_static_instructions():
    llm, fake = _llm([_completed()])
    llm.prompt_cache_key = "thread-1"
    await _run(llm, [Message.user("hi")], system_dynamic="DYN", reasoning_effort="low", text_verbosity="low")
    req = fake.requests[0]
    assert req["instructions"] == "STATIC"
    assert req["store"] is False and req["stream"] is True
    assert req["include"] == ["reasoning.encrypted_content"]
    assert req["reasoning"] == {"effort": "low"}
    assert req["text"] == {"verbosity": "low"}
    assert req["prompt_cache_key"] == "thread-1"
    assert req["input"] == [{"role": "developer", "content": "DYN"}, {"role": "user", "content": "hi"}]


@pytest.mark.asyncio
async def test_reasoning_knobs_dropped_for_non_reasoning_model():
    llm, fake = _llm([_completed()], model="gpt-4.1")
    await _run(llm, [Message.user("hi")], reasoning_effort="high", text_verbosity="low")
    req = fake.requests[0]
    assert "reasoning" not in req and "text" not in req and "include" not in req


# ── stream parsing ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stream_text_and_usage():
    llm, _ = _llm([
        NS(type="response.output_text.delta", delta="Hel"),
        NS(type="response.output_text.delta", delta="lo"),
        _completed(_usage(100, 20, 64, 8)),
    ])
    events = await _run(llm, [Message.user("hi")])
    assert "".join(e.text for e in events if isinstance(e, TextDeltaEvent)) == "Hello"
    assert events[-2] == UsageEvent(input_tokens=100, output_tokens=20, cached_input_tokens=64, reasoning_tokens=8)
    assert events[-1] == TurnCompleteEvent(has_pending_tool_calls=False)


@pytest.mark.asyncio
async def test_function_call_uses_call_id_and_reasoning_round_trips():
    llm, fake = _llm(_tool_turn(), [_completed()])
    history = [Message.user("find x")]

    events = await _run(llm, history, tools=[{"name": "search"}])

    starts = [e for e in events if isinstance(e, ToolUseStartEvent)]
    assert starts == [ToolUseStartEvent(tool_name="search", call_id="call_abc")]
    calls = [e for e in events if isinstance(e, PendingToolCall)]
    assert calls == [PendingToolCall(call_id="call_abc", tool_name="search", tool_input={"q": "x"})]
    assert events[-1] == TurnCompleteEvent(has_pending_tool_calls=True)

    tool_msgs = llm.build_tool_result_message(calls, [{"rows": 3}], [None])
    assert tool_msgs[0].provider_state == {
        "provider": "openai_responses",
        "reasoning": [{"type": "reasoning", "summary": [{"type": "summary_text", "text": "thinking"}], "encrypted_content": "ENC-1"}],
    }

    await _run(llm, history + tool_msgs, tools=[{"name": "search"}])
    sent = fake.requests[1]["input"]
    assert [i.get("type") or i.get("role") for i in sent] == ["user", "reasoning", "function_call", "function_call_output"]
    assert sent[2]["call_id"] == sent[3]["call_id"] == "call_abc"


@pytest.mark.asyncio
async def test_reasoning_without_encrypted_content_is_not_replayed():
    turn = _tool_turn()
    turn[0] = NS(type="response.output_item.done", item=_reasoning_item(enc=None))
    llm, _ = _llm(turn)
    calls = [e for e in await _run(llm, [Message.user("x")]) if isinstance(e, PendingToolCall)]
    assert llm.build_tool_result_message(calls, [{}], [None])[0].provider_state is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("event", "message", "code"),
    [
        (
            NS(type="response.failed", response=NS(usage=None, error=NS(code="server_error", message="boom"))),
            "Model response failed: boom",
            "server_error",
        ),
        (
            NS(type="response.incomplete", response=NS(usage=_usage(), incomplete_details=NS(reason="max_output_tokens"))),
            "Model response incomplete (max_output_tokens)",
            "incomplete:max_output_tokens",
        ),
        (
            NS(type="error", code="rate_limit_exceeded", message="slow down", param=None),
            "Model API error: slow down",
            "rate_limit_exceeded",
        ),
    ],
)
async def test_terminal_failures_yield_error_event_then_raise(event, message, code):
    llm, _ = _llm([NS(type="response.output_text.delta", delta="partial"), event])
    events: list[Any] = []
    with pytest.raises(LLMStreamError) as excinfo:
        async for e in llm.stream_turn([Message.user("hi")], system="", tools=[]):
            events.append(e)
    assert events[-1] == ErrorEvent(message=message, code=code)
    assert not any(isinstance(e, TurnCompleteEvent) for e in events)
    assert str(excinfo.value) == message and excinfo.value.code == code


@pytest.mark.asyncio
async def test_stream_ending_without_completed_is_an_error():
    llm, _ = _llm([NS(type="response.output_text.delta", delta="cut")])
    with pytest.raises(LLMStreamError):
        await _run(llm, [Message.user("hi")])


# ── real SDK over a mocked transport ──────────────────────────────────────
# The tests above replay SimpleNamespace events. These run the installed
# openai SDK end to end (HTTPX2 transport, SSE parsing, typed event models),
# so an SDK upgrade that renames events or fields fails here.


def _sse(*events: dict[str, Any]) -> bytes:
    return b"".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n".encode() for e in events)


def _sdk_llm(body: bytes) -> tuple[OpenAIResponsesLLM, list[dict[str, Any]]]:
    import httpx2
    from openai import AsyncOpenAI, DefaultAsyncHttpx2Client

    sent: list[dict[str, Any]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(json.loads(request.content))
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=body)

    llm = OpenAIResponsesLLM(api_key="test", base_url="http://localhost/v1", model="gpt-5.5")
    llm._client = AsyncOpenAI(
        api_key="test",
        base_url="http://localhost/v1",
        http_client=DefaultAsyncHttpx2Client(transport=httpx2.MockTransport(handler)),
    )
    return llm, sent


_SDK_USAGE = {
    "input_tokens": 50,
    "input_tokens_details": {"cached_tokens": 40},
    "output_tokens": 10,
    "output_tokens_details": {"reasoning_tokens": 6},
    "total_tokens": 60,
}


def _sdk_response(status: str, **extra: Any) -> dict[str, Any]:
    return {"id": "resp_1", "object": "response", "status": status, "output": [], "usage": _SDK_USAGE, **extra}


@pytest.mark.asyncio
async def test_sdk_stream_parses_tool_call_reasoning_and_usage():
    reasoning = {
        "type": "reasoning", "id": "rs_1", "encrypted_content": "ENC-1",
        "summary": [{"type": "summary_text", "text": "thinking"}],
    }
    fc = {
        "type": "function_call", "id": "fc_123", "call_id": "call_abc",
        "name": "search", "arguments": '{"q": "x"}', "status": "completed",
    }
    body = _sse(
        {"type": "response.output_item.done", "output_index": 0, "sequence_number": 1, "item": reasoning},
        {"type": "response.output_item.added", "output_index": 1, "sequence_number": 2, "item": {**fc, "arguments": ""}},
        {"type": "response.output_item.done", "output_index": 1, "sequence_number": 3, "item": fc},
        {"type": "response.completed", "sequence_number": 4, "response": _sdk_response("completed")},
    )
    llm, sent = _sdk_llm(body)

    events = await _run(llm, [Message.user("find x")], tools=[{"name": "search"}])

    assert sent[0]["stream"] is True
    assert sent[0]["include"] == ["reasoning.encrypted_content"]
    assert [e for e in events if isinstance(e, ToolUseStartEvent)] == [
        ToolUseStartEvent(tool_name="search", call_id="call_abc")
    ]
    calls = [e for e in events if isinstance(e, PendingToolCall)]
    assert calls == [PendingToolCall(call_id="call_abc", tool_name="search", tool_input={"q": "x"})]
    assert UsageEvent(input_tokens=50, output_tokens=10, cached_input_tokens=40, reasoning_tokens=6) in events
    state = llm.build_tool_result_message(calls, [{}], [None])[0].provider_state
    assert state["reasoning"][0]["encrypted_content"] == "ENC-1"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("event", "code"),
    [
        (
            {"type": "response.failed", "sequence_number": 1,
             "response": _sdk_response("failed", error={"code": "server_error", "message": "boom"})},
            "server_error",
        ),
        (
            {"type": "response.incomplete", "sequence_number": 1,
             "response": _sdk_response("incomplete", incomplete_details={"reason": "max_output_tokens"})},
            "incomplete:max_output_tokens",
        ),
    ],
)
async def test_sdk_stream_failed_and_incomplete_events(event, code):
    llm, _ = _sdk_llm(_sse(event))
    with pytest.raises(LLMStreamError) as excinfo:
        await _run(llm, [Message.user("hi")])
    assert excinfo.value.code == code


@pytest.mark.asyncio
async def test_sdk_structured_output_sends_text_format_json_schema():
    schema = {"type": "object", "properties": {"a": {"type": "integer"}}, "required": ["a"]}
    body = _sse(
        {"type": "response.output_text.delta", "item_id": "msg_1", "output_index": 0,
         "content_index": 0, "sequence_number": 1, "delta": '{"a": 1}', "logprobs": []},
        {"type": "response.completed", "sequence_number": 2, "response": _sdk_response("completed")},
    )
    llm, sent = _sdk_llm(body)

    assert await llm.structured_output([Message.user("q")], schema, name="answer", strict=True) == {"a": 1}
    assert sent[0]["text"]["format"] == {"type": "json_schema", "name": "answer", "schema": schema, "strict": True}
