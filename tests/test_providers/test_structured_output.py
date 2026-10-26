"""Tests for structured (JSON-schema) output across providers."""

from __future__ import annotations

from types import SimpleNamespace as NS
from typing import Any

import pytest

from dataclaw.providers.llm import structured
from dataclaw.providers.llm.implementations.langchain_llm import LangChainLLM
from dataclaw.providers.llm.implementations.mock_llm import MockLLM
from dataclaw.providers.llm.implementations.openai_responses import OpenAIResponsesLLM
from dataclaw.providers.llm.provider import (
    LLMStreamError,
    PendingToolCall,
    StructuredOutputError,
    StructuredOutputProvider,
    TextDeltaEvent,
    TurnCompleteEvent,
)
from dataclaw.providers.llm.structured import structured_output
from dataclaw.schema import Message

SCHEMA = {
    "type": "object",
    "properties": {"choice": {"type": "string"}, "confidence": {"type": "number"}},
    "required": ["choice", "confidence"],
    "additionalProperties": False,
}


class _ToolCallingLLM:
    """Provider without structured_output: answers through the offered tool."""

    def __init__(self, tool_input: dict[str, Any] | None) -> None:
        self.tool_input = tool_input
        self.calls: list[dict[str, Any]] = []

    async def stream_turn(self, messages, *, system, tools, **kwargs):
        self.calls.append({"system": system, "tools": tools})
        yield TextDeltaEvent(text="thinking out loud")
        if self.tool_input is not None:
            yield PendingToolCall(call_id="c1", tool_name=tools[0]["name"], tool_input=self.tool_input)
        yield TurnCompleteEvent(has_pending_tool_calls=self.tool_input is not None)

    def build_tool_result_message(self, tool_calls, results, errors):
        return []


@pytest.mark.asyncio
async def test_tool_call_fallback_returns_tool_arguments():
    llm = _ToolCallingLLM({"choice": "a", "confidence": 0.9})
    assert not isinstance(llm, StructuredOutputProvider)

    result = await structured_output(llm, [Message.user("pick")], SCHEMA, system="Be brief.", name="decision")

    assert result == {"choice": "a", "confidence": 0.9}
    call = llm.calls[0]
    assert call["tools"] == [{
        "name": "decision",
        "description": call["tools"][0]["description"],
        "parameters": SCHEMA,
    }]
    assert call["system"].startswith("Be brief.")
    assert "`decision` tool" in call["system"]


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_input", [None, {"choice": "a"}])
async def test_tool_call_fallback_rejects_missing_answer(tool_input):
    with pytest.raises(StructuredOutputError):
        await structured_output(_ToolCallingLLM(tool_input), [Message.user("pick")], SCHEMA)


@pytest.mark.asyncio
async def test_mock_llm_without_tool_calls_raises():
    with pytest.raises(StructuredOutputError):
        await structured_output(MockLLM(), [Message.user("pick")], SCHEMA)


@pytest.mark.asyncio
async def test_native_method_is_preferred():
    class _Native(_ToolCallingLLM):
        async def structured_output(self, messages, schema, *, system="", name="response", strict=False):
            return {"choice": "native", "confidence": 1.0, "strict": strict}

    llm = _Native(None)
    result = await structured_output(llm, [Message.user("x")], SCHEMA, strict=True)
    assert result["choice"] == "native" and result["strict"] is True
    assert llm.calls == []


# ── OpenAI Responses ───────────────────────────────────────────────────────


class _FakeResponses:
    def __init__(self, events: list[Any]) -> None:
        self.events = events
        self.requests: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any):
        self.requests.append(kwargs)

        async def gen():
            for event in self.events:
                yield event

        return gen()


def _responses_llm(events: list[Any], *, compat: bool = False) -> tuple[OpenAIResponsesLLM, _FakeResponses]:
    llm = OpenAIResponsesLLM(api_key="k", base_url="http://localhost/v1", model="gpt-6.1-sol", compat=compat)
    fake = _FakeResponses(events)
    llm._client = NS(responses=fake)  # type: ignore[assignment]
    return llm, fake


@pytest.mark.asyncio
async def test_responses_uses_json_schema_format():
    llm, fake = _responses_llm([
        NS(type="response.output_text.delta", delta='{"choice": "b", '),
        NS(type="response.output_text.delta", delta='"confidence": 0.5}'),
        NS(type="response.completed", response=NS(usage=None)),
    ])

    result = await structured_output(llm, [Message.user("pick")], SCHEMA, system="sys", name="decision", strict=True)

    assert result == {"choice": "b", "confidence": 0.5}
    request = fake.requests[0]
    assert request["text"] == {
        "format": {"type": "json_schema", "name": "decision", "schema": SCHEMA, "strict": True},
    }
    assert request["instructions"] == "sys"
    assert request["store"] is False and request["stream"] is True
    assert "tools" not in request


@pytest.mark.asyncio
async def test_responses_invalid_json_and_failures():
    llm, _ = _responses_llm([
        NS(type="response.output_text.delta", delta="not json"),
        NS(type="response.completed", response=NS(usage=None)),
    ])
    with pytest.raises(StructuredOutputError):
        await structured_output(llm, [Message.user("pick")], SCHEMA)

    failed, _ = _responses_llm([
        NS(type="response.failed", response=NS(usage=None, error=NS(message="boom", code="server_error"))),
    ])
    with pytest.raises(LLMStreamError):
        await structured_output(failed, [Message.user("pick")], SCHEMA)


@pytest.mark.asyncio
async def test_open_responses_endpoint_uses_tool_call_fallback(monkeypatch):
    seen = {}

    async def fake_fallback(llm, messages, schema, *, system="", name="response"):
        seen["llm"] = llm
        return {"choice": "c", "confidence": 0.1}

    monkeypatch.setattr(structured, "tool_call_structured_output", fake_fallback)
    llm, fake = _responses_llm([], compat=True)

    assert await structured_output(llm, [Message.user("x")], SCHEMA) == {"choice": "c", "confidence": 0.1}
    assert seen["llm"] is llm
    assert fake.requests == []


# ── LangChain ──────────────────────────────────────────────────────────────


class _Runnable:
    def __init__(self, result: Any) -> None:
        self.result = result
        self.inputs: list[Any] = []

    async def ainvoke(self, messages):
        self.inputs.append(messages)
        return self.result


def _fake_model(class_name: str, model: str, result: Any):
    calls: list[dict[str, Any]] = []
    runnable = _Runnable(result)

    def with_structured_output(self, schema, **kwargs):
        calls.append({"schema": schema, **kwargs})
        return runnable

    cls = type(class_name, (), {"model": model, "with_structured_output": with_structured_output})
    return cls(), calls, runnable


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("class_name", "model", "method", "strict"),
    [
        ("ChatOpenAI", "gpt-6.1-sol", "json_schema", True),
        ("ChatAnthropic", "claude-opus-5-5", "json_schema", None),
        ("ChatAnthropic", "claude-sonnet-4-20250514", "function_calling", None),
        ("ChatGoogleGenerativeAI", "gemini-4-argon", "json_schema", None),
    ],
)
async def test_langchain_structured_output_method(class_name, model, method, strict):
    fake, calls, runnable = _fake_model(class_name, model, {"choice": "d", "confidence": 0.7})
    llm = LangChainLLM(fake)  # type: ignore[arg-type]

    result = await structured_output(llm, [Message.user("pick")], SCHEMA, system="sys", name="decision", strict=True)

    assert result == {"choice": "d", "confidence": 0.7}
    assert calls[0]["method"] == method
    assert calls[0].get("strict") == strict
    assert calls[0]["schema"]["title"] == "decision"
    assert calls[0]["schema"]["properties"] == SCHEMA["properties"]
    sent = runnable.inputs[0]
    assert type(sent[0]).__name__ == "SystemMessage"
    assert type(sent[-1]).__name__ == "HumanMessage"


@pytest.mark.asyncio
async def test_langchain_structured_output_validates_reply():
    fake, _, _ = _fake_model("ChatOpenAI", "gpt-6.1-sol", None)
    with pytest.raises(StructuredOutputError):
        await structured_output(LangChainLLM(fake), [Message.user("x")], SCHEMA)  # type: ignore[arg-type]
    partial, _, _ = _fake_model("ChatOpenAI", "gpt-6.1-sol", {"choice": "x"})
    with pytest.raises(StructuredOutputError, match="confidence"):
        await structured_output(LangChainLLM(partial), [Message.user("x")], SCHEMA)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_langchain_compat_uses_tool_call_fallback(monkeypatch):
    async def fake_fallback(llm, messages, schema, *, system="", name="response"):
        return {"choice": "e", "confidence": 0.2}

    monkeypatch.setattr(structured, "tool_call_structured_output", fake_fallback)
    fake, calls, _ = _fake_model("ChatOpenAI", "qwen3", None)
    llm = LangChainLLM(fake, compat=True)  # type: ignore[arg-type]

    assert await structured_output(llm, [Message.user("x")], SCHEMA) == {"choice": "e", "confidence": 0.2}
    assert calls == []
