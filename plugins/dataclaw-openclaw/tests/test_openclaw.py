"""Tests for the OpenClaw bridge plugin."""

import asyncio
import pytest

from dataclaw.providers.llm.provider import (
    PendingToolCall,
    TextDeltaEvent,
    ToolUseStartEvent,
    TurnCompleteEvent,
)
from dataclaw.schema import Message

from dataclaw_openclaw.bridge import (
    ToolCallBridge,
    create_bridge,
    get_bridge,
    destroy_bridge,
)
from dataclaw_openclaw.agent_provider import (
    OpenClawAgentProvider,
    _extract_last_user_text,
    _extract_latest_tool_result,
)


# ── Bridge Tests ────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def clean_bridges():
    """Ensure bridges are cleaned up between tests."""
    yield
    from dataclaw_openclaw.bridge import _bridges
    _bridges.clear()


@pytest.mark.asyncio
async def test_bridge_create_get_destroy():
    bridge = create_bridge("sess-1")
    assert get_bridge("sess-1") is bridge
    destroy_bridge("sess-1")
    assert get_bridge("sess-1") is None


@pytest.mark.asyncio
async def test_bridge_tool_call_flow():
    """Tool proxy pushes call → agent provider reads it."""
    bridge = create_bridge("sess-1")

    # Simulate tool proxy pushing a call
    await bridge.push_tool_call({
        "call_id": "c1",
        "tool_name": "echo",
        "tool_input": {"q": "test"},
    })

    # Agent provider side: should get tool_call event
    event = await bridge.wait_for_call_or_response(timeout=2)
    assert event["type"] == "tool_call"
    assert event["tool_name"] == "echo"
    assert event["call_id"] == "c1"


@pytest.mark.asyncio
async def test_bridge_response_flow():
    """HTTP response arrives → agent provider gets it."""
    bridge = create_bridge("sess-1")

    # Simulate HTTP response arriving (from _post_to_openclaw task)
    bridge.set_response({
        "ok": True,
        "response": {"text": "Hello from OpenClaw!", "messageId": "msg-1"},
    })

    event = await bridge.wait_for_call_or_response(timeout=2)
    assert event["type"] == "response"
    assert event["text"] == "Hello from OpenClaw!"


@pytest.mark.asyncio
async def test_bridge_tool_result_roundtrip():
    """Agent provider pushes result → tool proxy reads it."""
    bridge = create_bridge("sess-1")

    # Agent provider pushes tool result
    await bridge.push_tool_result({"call_id": "c1", "result": {"echo": "test"}})

    # Tool proxy side: should get the result
    result = await bridge.wait_for_tool_result(timeout=2)
    assert result is not None
    assert result["result"] == {"echo": "test"}


@pytest.mark.asyncio
async def test_bridge_timeout():
    """Timeout when nothing arrives."""
    bridge = create_bridge("sess-1")
    event = await bridge.wait_for_call_or_response(timeout=0.1)
    assert event["type"] == "timeout"


@pytest.mark.asyncio
async def test_bridge_concurrent_events():
    """When both tool call and response arrive, either is valid."""
    bridge = create_bridge("sess-1")

    await bridge.push_tool_call({"call_id": "c1", "tool_name": "echo", "tool_input": {}})
    bridge.set_response({"response": {"text": "done"}})

    event = await bridge.wait_for_call_or_response(timeout=2)
    assert event["type"] in ("tool_call", "response")


# ── Helper Tests ────────────────────────────────────────────────────────────


def test_extract_last_user_text():
    messages = [
        Message.user("first"),
        Message.assistant("response"),
        Message.user("second"),
    ]
    assert _extract_last_user_text(messages) == "second"


def test_extract_last_user_text_empty():
    assert _extract_last_user_text([]) == ""
    assert _extract_last_user_text([Message.assistant("hi")]) == ""


def test_extract_latest_tool_result():
    messages = [
        Message.user("hello"),
        Message(role="assistant", content=[
            {"type": "tool_call", "id": "c1", "name": "echo", "input": {"q": "test"}},
        ]),
        Message(role="user", content=[
            {"type": "tool_result", "call_id": "c1", "content": '{"echo":"test"}', "is_error": False},
        ]),
    ]
    result = _extract_latest_tool_result(messages)
    assert result is not None
    assert result["call_id"] == "c1"
    assert result["is_error"] is False


def test_extract_latest_tool_result_none():
    messages = [Message.user("hello")]
    assert _extract_latest_tool_result(messages) is None


# ── Agent Provider Tests ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_provider_turn1_response():
    """Turn 1: POST to OpenClaw, get text response back."""
    provider = OpenClawAgentProvider(
        url="http://fake:1234",
        token="test",
        wait_ms=5000,
    )

    state = {
        "session_id": "test-sess",
        "messages": [Message.user("hello")],
    }

    # Pre-create bridge and set response (simulating what _post_to_openclaw does)
    bridge = create_bridge("test-sess")
    bridge.set_response({
        "ok": True,
        "response": {"text": "Hi from OpenClaw!", "messageId": "m1"},
    })

    # Override to skip actual HTTP call
    provider._post_to_openclaw = lambda *a, **kw: asyncio.sleep(0)  # noop

    events = []
    async for event in provider.stream_turn(state):
        events.append(event)

    assert any(isinstance(e, TextDeltaEvent) and "Hi from OpenClaw!" in e.text for e in events)
    assert any(isinstance(e, TurnCompleteEvent) and not e.has_pending_tool_calls for e in events)
    # Bridge should be cleaned up
    assert get_bridge("test-sess") is None


@pytest.mark.asyncio
async def test_provider_turn1_tool_call():
    """Turn 1: OpenClaw requests a tool instead of responding."""
    provider = OpenClawAgentProvider(url="http://fake:1234", wait_ms=5000)
    state = {
        "session_id": "tool-sess",
        "messages": [Message.user("search for data")],
    }

    bridge = create_bridge("tool-sess")
    # Simulate OpenClaw calling a tool via the bridge
    await bridge.push_tool_call({
        "call_id": "tc1",
        "tool_name": "data_query",
        "tool_input": {"sql": "SELECT 1"},
    })

    provider._post_to_openclaw = lambda *a, **kw: asyncio.sleep(0)

    events = []
    async for event in provider.stream_turn(state):
        events.append(event)

    assert any(isinstance(e, ToolUseStartEvent) and e.tool_name == "data_query" for e in events)
    assert any(isinstance(e, PendingToolCall) and e.tool_name == "data_query" for e in events)
    assert any(isinstance(e, TurnCompleteEvent) and e.has_pending_tool_calls for e in events)
    # Bridge should still exist (waiting for tool result)
    assert get_bridge("tool-sess") is not None
    destroy_bridge("tool-sess")


@pytest.mark.asyncio
async def test_provider_turn2_pushes_result():
    """Turn 2: after tool execution, pushes result back to bridge."""
    provider = OpenClawAgentProvider(url="http://fake:1234", wait_ms=5000)

    # Create bridge (simulating it already exists from turn 1)
    bridge = create_bridge("result-sess")

    # Simulate: after result is pushed, OpenClaw responds
    async def set_response_after_result():
        # Wait for the result to be pushed
        result = await bridge.wait_for_tool_result(timeout=5)
        assert result is not None
        # Then set the final response
        bridge.set_response({"response": {"text": "Done with tools!"}})

    asyncio.create_task(set_response_after_result())

    # State has tool result from chat.py
    state = {
        "session_id": "result-sess",
        "messages": [
            Message.user("do something"),
            Message(role="assistant", content=[
                {"type": "tool_call", "id": "c1", "name": "echo", "input": {}},
            ]),
            Message(role="user", content=[
                {"type": "tool_result", "call_id": "c1", "content": '{"ok":true}', "is_error": False},
            ]),
        ],
    }

    events = []
    async for event in provider.stream_turn(state):
        events.append(event)

    assert any(isinstance(e, TextDeltaEvent) and "Done with tools!" in e.text for e in events)
    assert any(isinstance(e, TurnCompleteEvent) and not e.has_pending_tool_calls for e in events)
