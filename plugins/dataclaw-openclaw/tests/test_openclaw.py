"""Tests for the OpenClaw bridge plugin."""

import asyncio
import pytest

from dataclaw.providers.llm.provider import (
    TextDeltaEvent,
    TurnCompleteEvent,
)
from dataclaw.schema import Message

from dataclaw_openclaw import agent_provider as agent_provider_module
from dataclaw_openclaw.bridge import (
    ToolCallBridge,
    create_bridge,
    get_bridge,
    destroy_bridge,
)
from dataclaw_openclaw.agent_provider import (
    OpenClawAgentProvider,
    _extract_last_user_text,
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


# ── Agent Provider Tests ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_provider_no_user_message():
    """No user text is reported clearly and does not contact OpenClaw."""
    provider = OpenClawAgentProvider(
        url="http://fake:1234",
        token="test",
    )

    state = {
        "session_id": "test-sess",
        "messages": [Message.assistant("hello")],
    }

    events = []
    async for event in provider.stream_turn(state):
        events.append(event)

    assert any(isinstance(e, TextDeltaEvent) and "No user message found" in e.text for e in events)
    assert any(isinstance(e, TurnCompleteEvent) and not e.has_pending_tool_calls for e in events)


@pytest.mark.asyncio
async def test_provider_health_failure(monkeypatch):
    """If the OpenClaw runtime is down, the provider emits a helpful message."""

    class FailingClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url):
            raise RuntimeError("down")

    monkeypatch.setattr(agent_provider_module.httpx, "AsyncClient", FailingClient)
    provider = OpenClawAgentProvider(url="http://fake:1234", wait_ms=5000)

    state = {
        "session_id": "health-sess",
        "messages": [Message.user("hello")],
    }

    events = []
    async for event in provider.stream_turn(state):
        events.append(event)

    assert any(isinstance(e, TextDeltaEvent) and "OpenClaw is not running" in e.text for e in events)
    assert any(isinstance(e, TurnCompleteEvent) and not e.has_pending_tool_calls for e in events)


@pytest.mark.asyncio
async def test_provider_fire_and_forget_after_health(monkeypatch):
    """Healthy OpenClaw turns are posted in the background and skipped for persistence."""

    health_urls: list[str] = []

    class HealthyClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url):
            health_urls.append(url)
            return object()

    created_coroutines = []
    post_args = []

    def fake_create_task(coro):
        created_coroutines.append(coro)
        coro.close()
        return object()

    def fake_post_to_openclaw(session_id, user_text):
        post_args.append((session_id, user_text))

        async def noop():
            return None

        return noop()

    monkeypatch.setattr(agent_provider_module.httpx, "AsyncClient", HealthyClient)
    monkeypatch.setattr(agent_provider_module.asyncio, "create_task", fake_create_task)

    provider = OpenClawAgentProvider(url="http://fake:1234", wait_ms=5000)
    provider._post_to_openclaw = fake_post_to_openclaw
    state = {
        "session_id": "fire-sess",
        "messages": [Message.user("run the agent")],
    }

    events = []
    async for event in provider.stream_turn(state):
        events.append(event)

    assert health_urls == ["http://fake:1234/dataclaw/health"]
    assert post_args == [("fire-sess", "run the agent")]
    assert len(created_coroutines) == 1
    assert events == [TurnCompleteEvent(has_pending_tool_calls=False, skip_persist=True)]


@pytest.mark.asyncio
async def test_post_to_openclaw_delivers_direct_response_callback(monkeypatch):
    """Direct OpenClaw text responses are forwarded to DataClaw's callback endpoint."""
    posts = []

    class FakeResponse:
        def __init__(self, data):
            self._data = data

        def raise_for_status(self):
            return None

        def json(self):
            return self._data

    class PostingClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, **kwargs):
            posts.append((url, kwargs))
            if url.endswith("/dataclaw/message"):
                return FakeResponse({"response": {"text": "Hello from OpenClaw!"}})
            return FakeResponse({})

    monkeypatch.setattr(agent_provider_module.httpx, "AsyncClient", PostingClient)

    provider = OpenClawAgentProvider(
        url="http://fake:1234",
        token="secret",
        wait_ms=250,
    )
    await provider._post_to_openclaw("callback-sess", "hello")

    assert posts[0][0] == "http://fake:1234/dataclaw/message"
    assert posts[0][1]["headers"]["X-Dataclaw-Token"] == "secret"
    assert posts[0][1]["json"] == {
        "sessionId": "callback-sess",
        "userId": "dataclaw",
        "text": "hello",
        "waitForResponseMs": 250,
    }
    assert posts[1] == (
        "http://127.0.0.1:8000/api/agent/callback/callback-sess",
        {"json": {"text": "Hello from OpenClaw!"}},
    )
