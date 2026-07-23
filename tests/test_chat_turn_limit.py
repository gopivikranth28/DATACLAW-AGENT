"""Regression coverage for visible agent turn-limit termination."""

from __future__ import annotations

import json

import pytest

from dataclaw.api.run_tracker import get_run_tracker
from dataclaw.api.routers import chat
from dataclaw.hooks.registry import HookRegistry
from dataclaw.providers.llm.provider import PendingToolCall, TurnCompleteEvent
from dataclaw.storage import sessions
from dataclaw.tool_progress import emit_tool_progress
from tests.conftest import MockToolAvailabilityProvider


@pytest.mark.asyncio
async def test_agent_turn_limit_is_persisted_and_streamed(
    mock_providers,
    monkeypatch: pytest.MonkeyPatch,
):
    session_id = "turn-limit-session"
    run_id = "turn-limit-run"
    await sessions.create_session(session_id=session_id, title="Turn limit")

    async def echo(**kwargs):
        emit_tool_progress("working", "Echoing the test payload", outputChars=12)
        return kwargs

    class AlwaysCallsToolAgent:
        async def stream_turn(self, state):
            yield PendingToolCall(call_id="call-1", tool_name="echo", tool_input={"ok": True})
            yield TurnCompleteEvent(has_pending_tool_calls=True)

    mock_providers.agent = AlwaysCallsToolAgent()
    mock_providers.compaction.will_compact = lambda *args, **kwargs: False
    mock_providers.tool_availability = MockToolAvailabilityProvider(
        tools=[{"name": "echo", "description": "Echo", "parameters": {}}],
        callables={"echo": echo},
    )
    monkeypatch.setattr(
        chat,
        "resolve",
        lambda key, _env, fallback: "1" if key == "app.max_turns" else fallback,
    )

    tracker = get_run_tracker()
    run = tracker.start_run(session_id, run_id)
    await chat._run_agent_loop(
        session_id,
        run_id,
        [{"role": "user", "content": "Keep working"}],
        "Keep working",
        mock_providers,
        HookRegistry(),
    )

    stored = await sessions.get_session(session_id)
    assert stored is not None
    notice = stored["messages"][-1]
    assert notice["role"] == "run_notice"
    assert notice["reason"] == "max_turns"
    assert notice["maxTurns"] == 1
    assert "Continue from where you stopped" in notice["content"]

    encoded_events = "\n".join(event for _, event in run.events)
    assert "agent:max_turns_reached" in encoded_events
    assert "tool:progress" in encoded_events
    assert "Echoing the test payload" in encoded_events
    assert "RUN_FINISHED" in encoded_events
    assert run.status == "finished"


def test_run_notice_replays_after_trailing_tools_but_stays_out_of_llm_context():
    raw = [
        {"role": "user", "messageId": "u1", "content": "Do work"},
        {
            "role": "tool_call",
            "messageId": "tc-1",
            "toolCallId": "call-1",
            "toolName": "echo",
            "args": "{}",
            "result": json.dumps({"ok": True}),
            "status": "complete",
        },
        {
            "role": "run_notice",
            "messageId": "notice-1",
            "reason": "max_turns",
            "maxTurns": 30,
            "content": "Progress saved.",
        },
    ]

    replay = chat._session_messages_to_agui(raw)
    assert [message["role"] for message in replay] == ["user", "assistant", "tool", "system"]
    assert replay[-1]["content"] == "[RUN_NOTICE:max_turns:30]\nProgress saved."

    llm_context = "\n".join(str(message) for message in chat._stored_messages_to_llm(raw))
    assert "Progress saved" not in llm_context
