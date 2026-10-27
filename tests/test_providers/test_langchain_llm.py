"""Tests for the LangChain LLM provider's request building.

The fake models subclass the real LangChain chat models and only replace
``_astream``, which renders the provider request payload with the SDK's own
``_get_request_payload`` and replays scripted chunks. That exercises the real
message formatting (system blocks, thinking blocks, bound kwargs) without any
network access.
"""

from __future__ import annotations

import base64
from typing import Any

import pytest
from langchain_anthropic import ChatAnthropic as _RealChatAnthropic
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGenerationChunk
from langchain_openai import ChatOpenAI as _RealChatOpenAI

from dataclaw.providers.llm.implementations.langchain_llm import LangChainLLM, _to_lc_messages
from dataclaw.providers.llm.provider import (
    PendingToolCall,
    TextDeltaEvent,
    ToolUseStartEvent,
    TurnCompleteEvent,
    UsageEvent,
)
from dataclaw.schema import Message


class _Script:
    """Records request payloads and serves one chunk list per call."""

    def __init__(self, *turns: list[AIMessageChunk]) -> None:
        self.turns = list(turns)
        self.payloads: list[dict[str, Any]] = []
        self.messages: list[list[Any]] = []


# Class names matter: LangChainLLM picks the provider family by class name.
class ChatAnthropic(_RealChatAnthropic):
    script: Any = None

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        self.script.messages.append(list(messages))
        kwargs.pop("stream_usage", None)
        self.script.payloads.append(self._get_request_payload(messages, stop=stop, **kwargs))
        for chunk in self.script.turns.pop(0):
            yield ChatGenerationChunk(message=chunk)


class ChatOpenAI(_RealChatOpenAI):
    script: Any = None

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        self.script.messages.append(list(messages))
        kwargs.pop("stream_usage", None)
        self.script.payloads.append(self._get_request_payload(messages, stop=stop, **kwargs))
        for chunk in self.script.turns.pop(0):
            yield ChatGenerationChunk(message=chunk)


def _anthropic(script: _Script, model: str = "claude-opus-4-5") -> ChatAnthropic:
    llm = ChatAnthropic(model=model, api_key="test-key")
    llm.script = script
    return llm


def _openai(script: _Script, model: str = "gpt-4o") -> ChatOpenAI:
    llm = ChatOpenAI(model=model, api_key="test-key")
    llm.script = script
    return llm


async def _collect(llm: LangChainLLM, messages: list[Message], **kwargs: Any) -> list[Any]:
    kwargs.setdefault("system", "STATIC")
    kwargs.setdefault("tools", [])
    return [e async for e in llm.stream_turn(messages, **kwargs)]


_TOOLS = [{"name": "search", "description": "Search", "parameters": {"type": "object", "properties": {"q": {"type": "string"}}}}]


def _anthropic_tool_turn() -> list[AIMessageChunk]:
    """Thinking (signed) + text + one tool_use, as langchain-anthropic streams it."""
    return [
        AIMessageChunk(content=[{"type": "thinking", "thinking": "Need data.", "signature": "SIG-1", "index": 0}]),
        AIMessageChunk(content=[{"type": "text", "text": "Searching.", "index": 1}]),
        AIMessageChunk(
            content=[{"type": "tool_use", "id": "toolu_1", "name": "search", "input": {}, "index": 2, "partial_json": '{"q": "x"}'}],
            tool_call_chunks=[{"name": "search", "args": '{"q": "x"}', "id": "toolu_1", "index": 2}],
        ),
        AIMessageChunk(
            content="",
            usage_metadata={
                "input_tokens": 120,
                "output_tokens": 30,
                "total_tokens": 150,
                "input_token_details": {"cache_read": 100},
                "output_token_details": {"reasoning": 12},
            },
        ),
    ]


# ── system prompt: static + summary + dynamic ──────────────────────────────


@pytest.mark.asyncio
async def test_anthropic_system_dynamic_and_summary_with_cache_breakpoints():
    script = _Script([AIMessageChunk(content="ok")])
    llm = LangChainLLM(_anthropic(script))
    messages = [Message.system("[Conversation summary]\nearlier"), Message.user("hi")]

    events = await _collect(llm, messages, system_dynamic="## Relevant Memories\n- likes csv")

    assert any(isinstance(e, TextDeltaEvent) and e.text == "ok" for e in events)
    payload = script.payloads[0]
    assert payload["system"] == [
        {"type": "text", "text": "STATIC", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "[Conversation summary]\nearlier", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "## Relevant Memories\n- likes csv"},
    ]
    # The summary is folded into the system prompt, not left mid-conversation.
    assert payload["messages"] == [{"role": "user", "content": "hi"}]


@pytest.mark.asyncio
async def test_openai_system_dynamic_appended_after_static_prefix():
    script = _Script([AIMessageChunk(content="ok")])
    llm = LangChainLLM(_openai(script))
    messages = [Message.system("SUMMARY"), Message.user("hi")]

    await _collect(llm, messages, system_dynamic="DYNAMIC")

    sent = script.payloads[0]["messages"]
    assert sent[0] == {"role": "system", "content": "STATIC\n\nSUMMARY\n\nDYNAMIC"}
    assert [m["role"] for m in sent] == ["system", "user"]


@pytest.mark.asyncio
async def test_agent_provider_dynamic_prompt_reaches_the_model():
    """End to end from pipeline state: memories/skills are no longer dropped."""
    from dataclaw.providers.agent.implementations.langchain_agent import LangChainAgentProvider

    script = _Script([AIMessageChunk(content="ok")])
    agent = LangChainAgentProvider(LangChainLLM(_openai(script)))
    state = {
        "system_prompt": "STATIC",
        "system_prompt_dynamic": "## Available Skills\nskill-a",
        "messages": [Message.user("hi")],
        "tools": [],
    }
    _ = [e async for e in agent.stream_turn(state)]  # type: ignore[arg-type]
    assert "## Available Skills\nskill-a" in script.payloads[0]["messages"][0]["content"]


@pytest.mark.asyncio
async def test_system_message_omitted_when_everything_empty():
    script = _Script([AIMessageChunk(content="ok")])
    llm = LangChainLLM(_openai(script))
    await _collect(llm, [Message.user("hi")], system="")
    assert [m["role"] for m in script.payloads[0]["messages"]] == ["user"]


# ── reasoning effort / verbosity gating ────────────────────────────────────


@pytest.mark.asyncio
async def test_reasoning_effort_dropped_for_non_reasoning_openai_model():
    script = _Script([AIMessageChunk(content="ok")])
    llm = LangChainLLM(_openai(script, model="gpt-4o"))
    await _collect(llm, [Message.user("hi")], reasoning_effort="high", text_verbosity="low")
    payload = script.payloads[0]
    assert "reasoning_effort" not in payload
    assert "verbosity" not in payload


@pytest.mark.asyncio
async def test_reasoning_effort_and_verbosity_bound_for_gpt5():
    script = _Script([AIMessageChunk(content="ok")])
    llm = LangChainLLM(_openai(script, model="gpt-5"))
    await _collect(llm, [Message.user("hi")], reasoning_effort="high", text_verbosity="low")
    payload = script.payloads[0]
    assert payload["reasoning_effort"] == "high"
    assert payload["verbosity"] == "low"


@pytest.mark.asyncio
async def test_anthropic_effort_goes_to_output_config_only_when_supported():
    script = _Script([AIMessageChunk(content="ok")], [AIMessageChunk(content="ok")])
    supported = LangChainLLM(_anthropic(script, model="claude-opus-4-5"))
    await _collect(supported, [Message.user("hi")], reasoning_effort="minimal")
    assert script.payloads[0]["output_config"] == {"effort": "low"}
    assert "effort" not in script.payloads[0]

    legacy = LangChainLLM(_anthropic(script, model="claude-sonnet-4-20250514"))
    await _collect(legacy, [Message.user("hi")], reasoning_effort="high")
    assert "output_config" not in script.payloads[1]


# ── tool turns: events, usage, and provider-native round trip ──────────────


@pytest.mark.asyncio
async def test_anthropic_thinking_blocks_round_trip_across_tool_turn():
    script = _Script(_anthropic_tool_turn(), [AIMessageChunk(content="done")])
    llm = LangChainLLM(_anthropic(script))
    history = [Message.user("find x")]

    events = await _collect(llm, history, tools=_TOOLS)

    assert [type(e) for e in events if not isinstance(e, TextDeltaEvent)] == [
        ToolUseStartEvent, UsageEvent, PendingToolCall, TurnCompleteEvent,
    ]
    usage = next(e for e in events if isinstance(e, UsageEvent))
    assert (usage.input_tokens, usage.output_tokens, usage.cached_input_tokens, usage.reasoning_tokens) == (120, 30, 100, 12)
    call = next(e for e in events if isinstance(e, PendingToolCall))
    assert (call.call_id, call.tool_name, call.tool_input) == ("toolu_1", "search", {"q": "x"})

    tool_msgs = llm.build_tool_result_message([call], [{"rows": 1}], [None])
    assert tool_msgs[0].content[0] == {"type": "text", "text": "Searching."}
    assert tool_msgs[0].provider_state["provider"] == "ChatAnthropic"

    await _collect(llm, history + tool_msgs, tools=_TOOLS)

    assistant = script.payloads[1]["messages"][1]
    assert assistant["role"] == "assistant"
    blocks = assistant["content"]
    assert blocks[0] == {"type": "thinking", "thinking": "Need data.", "signature": "SIG-1"}
    assert {"type": "text", "text": "Searching."} in blocks
    tool_use = [b for b in blocks if b["type"] == "tool_use"]
    assert tool_use == [{"type": "tool_use", "name": "search", "input": {"q": "x"}, "id": "toolu_1"}]
    tool_result = script.payloads[1]["messages"][2]["content"][0]
    assert tool_result["type"] == "tool_result" and tool_result["tool_use_id"] == "toolu_1"


@pytest.mark.asyncio
async def test_split_tool_results_scope_native_tool_use_blocks():
    """A turn's calls split across messages each keep only their own tool_use."""
    turn = _anthropic_tool_turn()
    turn.insert(3, AIMessageChunk(
        content=[{"type": "tool_use", "id": "toolu_2", "name": "search", "input": {}, "index": 3, "partial_json": '{"q": "y"}'}],
        tool_call_chunks=[{"name": "search", "args": '{"q": "y"}', "id": "toolu_2", "index": 3}],
    ))
    script = _Script(turn, [AIMessageChunk(content="done")])
    llm = LangChainLLM(_anthropic(script))
    history = [Message.user("find")]

    events = await _collect(llm, history, tools=_TOOLS)
    calls = [e for e in events if isinstance(e, PendingToolCall)]
    blocked = llm.build_tool_result_message([calls[0]], [{}], [ValueError("blocked")])
    executed = llm.build_tool_result_message([calls[1]], [{"ok": True}], [None])

    await _collect(llm, history + blocked + executed, tools=_TOOLS)

    sent = script.payloads[1]["messages"]
    first_ids = [b["id"] for b in sent[1]["content"] if b["type"] == "tool_use"]
    second_ids = [b["id"] for b in sent[3]["content"] if b["type"] == "tool_use"]
    assert first_ids == ["toolu_1"] and second_ids == ["toolu_2"]


@pytest.mark.asyncio
async def test_turn_state_is_keyed_by_call_id_not_last_turn():
    """A nested turn (e.g. a sub-agent) must not clobber the outer turn's state."""
    nested = [
        AIMessageChunk(content=[{"type": "text", "text": "Nested.", "index": 0}]),
        AIMessageChunk(content=[], tool_call_chunks=[{"name": "search", "args": "{}", "id": "toolu_n", "index": 1}]),
    ]
    script = _Script(_anthropic_tool_turn(), nested)
    llm = LangChainLLM(_anthropic(script))

    outer = [e for e in await _collect(llm, [Message.user("a")], tools=_TOOLS) if isinstance(e, PendingToolCall)]
    await _collect(llm, [Message.user("b")], tools=_TOOLS)

    msgs = llm.build_tool_result_message(outer, [{}], [None])
    assert msgs[0].content[0] == {"type": "text", "text": "Searching."}
    assert msgs[0].provider_state["content"][0]["signature"] == "SIG-1"


@pytest.mark.asyncio
async def test_plain_chat_completions_turn_stores_no_provider_state():
    turn = [AIMessageChunk(content="", tool_call_chunks=[{"name": "search", "args": "{}", "id": "call_1", "index": 0}])]
    script = _Script(turn)
    llm = LangChainLLM(_openai(script))
    calls = [e for e in await _collect(llm, [Message.user("a")], tools=_TOOLS) if isinstance(e, PendingToolCall)]
    msgs = llm.build_tool_result_message(calls, [{}], [None])
    assert msgs[0].provider_state is None


# ── _to_lc_messages ─────────────────────────────────────────────────────────


def test_to_lc_messages_maps_system_role():
    out = _to_lc_messages([Message.system("[Conversation summary]\nS"), Message.user("hi")])
    assert isinstance(out[0], SystemMessage) and out[0].content == "[Conversation summary]\nS"
    assert isinstance(out[1], HumanMessage)


def test_to_lc_messages_tool_call_and_result():
    msgs = [
        Message.tool_call([
            {"type": "text", "text": "Looking."},
            {"type": "tool_call", "id": "c1", "name": "search", "input": {"q": 1}},
        ]),
        Message.tool_result([{"type": "tool_result", "call_id": "c1", "content": "R", "is_error": False}]),
    ]
    ai, tool = _to_lc_messages(msgs)
    assert isinstance(ai, AIMessage) and ai.content == "Looking."
    assert ai.tool_calls[0]["id"] == "c1" and ai.tool_calls[0]["args"] == {"q": 1}
    assert isinstance(tool, ToolMessage) and tool.tool_call_id == "c1"


def test_provider_state_only_replayed_to_matching_provider():
    msg = Message.tool_call(
        [{"type": "tool_call", "id": "c1", "name": "search", "input": {}}],
        provider_state={"provider": "ChatAnthropic", "content": [{"type": "thinking", "thinking": "t", "signature": "s"}]},
    )
    (native,) = _to_lc_messages([msg], provider="ChatAnthropic")
    assert native.content[0]["type"] == "thinking"
    (foreign,) = _to_lc_messages([msg], provider="ChatOpenAI")
    assert foreign.content == ""
    (unknown,) = _to_lc_messages([msg])
    assert unknown.content == ""


def test_gemini_thought_signatures_restored_on_function_calls():
    from langchain_google_genai.chat_models import _parse_chat_history

    sig = base64.b64encode(b"thought-sig").decode()
    msg = Message.tool_call(
        [{"type": "tool_call", "id": "g1", "name": "search", "input": {"q": "x"}}],
        provider_state={
            "provider": "ChatGoogleGenerativeAI",
            "content": [],
            "additional_kwargs": {"__gemini_function_call_thought_signatures__": {"g1": sig, "other": sig}},
        },
    )
    lc = _to_lc_messages(
        [
            Message.user("find"),
            msg,
            Message.tool_result([{"type": "tool_result", "call_id": "g1", "content": "{}", "is_error": False}]),
        ],
        provider="ChatGoogleGenerativeAI",
    )
    assert lc[1].additional_kwargs == {"__gemini_function_call_thought_signatures__": {"g1": sig}}

    _, contents = _parse_chat_history(lc, model="gemini-2.5-flash")
    fc_part = next(p for p in contents[1].parts if p.function_call)
    assert fc_part.thought_signature == b"thought-sig"


def test_message_provider_state_survives_dict_round_trip():
    msg = Message.tool_call([], provider_state={"provider": "x", "content": [{"a": 1}]})
    assert Message.from_dict(msg.to_dict()).provider_state == {"provider": "x", "content": [{"a": 1}]}
    plain = Message.user("hi")
    assert "provider_state" not in plain.to_dict()
    assert Message.from_dict(plain.to_dict()).provider_state is None
