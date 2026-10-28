"""The chat loop's handling of UsageEvent and ErrorEvent from providers."""

from __future__ import annotations

import pytest

from dataclaw.api.routers import chat
from dataclaw.api.run_tracker import get_run_tracker
from dataclaw.hooks.registry import HookRegistry
from dataclaw.providers.llm.provider import (
    ErrorEvent,
    LLMStreamError,
    TextDeltaEvent,
    TurnCompleteEvent,
    UsageEvent,
)
from dataclaw.storage import sessions


async def _run(session_id: str, mock_providers, agent):
    await sessions.create_session(session_id=session_id, title="LLM events")
    mock_providers.agent = agent
    mock_providers.compaction.will_compact = lambda *args, **kwargs: False
    run = get_run_tracker().start_run(session_id, f"{session_id}-run")
    await chat._run_agent_loop(
        session_id,
        f"{session_id}-run",
        [{"role": "user", "content": "hi"}],
        "hi",
        mock_providers,
        HookRegistry(),
    )
    return run, "\n".join(event for _, event in run.events)


@pytest.mark.asyncio
async def test_usage_event_is_streamed_and_run_finishes(mock_providers):
    class Agent:
        async def stream_turn(self, state):
            yield TextDeltaEvent(text="Hello")
            yield UsageEvent(input_tokens=10, output_tokens=2, cached_input_tokens=8, reasoning_tokens=1)
            yield TurnCompleteEvent(has_pending_tool_calls=False)

    run, encoded = await _run("usage-session", mock_providers, Agent())

    assert "llm:usage" in encoded
    assert '"cachedInputTokens":8' in encoded.replace(" ", "")
    assert "RUN_FINISHED" in encoded
    assert run.status == "finished"


@pytest.mark.asyncio
async def test_usage_cost_is_streamed_and_totalled(mock_providers):
    class Agent:
        def __init__(self):
            self.turns = 0

        async def stream_turn(self, state):
            self.turns += 1
            yield TextDeltaEvent(text="Hello")
            yield UsageEvent(input_tokens=10, output_tokens=2, cost_usd=0.00125)
            yield TurnCompleteEvent(has_pending_tool_calls=False)

    run, encoded = await _run("usage-cost-session", mock_providers, Agent())

    compact = encoded.replace(" ", "")
    assert '"costUsd":0.00125' in compact
    assert '"runTotals":{"inputTokens":10,"outputTokens":2,"cachedInputTokens":0,"reasoningTokens":0,"costUsd":0.00125}' in compact
    assert run.status == "finished"


@pytest.mark.asyncio
async def test_usage_without_cost_reports_null(mock_providers):
    class Agent:
        async def stream_turn(self, state):
            yield UsageEvent(input_tokens=1, output_tokens=1)
            yield TurnCompleteEvent(has_pending_tool_calls=False)

    _, encoded = await _run("usage-nocost-session", mock_providers, Agent())
    assert '"costUsd":null' in encoded.replace(" ", "")


@pytest.mark.asyncio
async def test_error_event_fails_run_with_provider_message(mock_providers):
    class Agent:
        async def stream_turn(self, state):
            yield TextDeltaEvent(text="partial")
            yield ErrorEvent(message="Model response incomplete (max_output_tokens)", code="incomplete")
            raise LLMStreamError("Model response incomplete (max_output_tokens)")

    run, encoded = await _run("error-session", mock_providers, Agent())

    assert "RUN_ERROR" in encoded
    assert "Model response incomplete (max_output_tokens)" in encoded
    assert "Internal error" not in encoded
    # The open text message is closed before the run errors.
    assert encoded.index("TEXT_MESSAGE_END") < encoded.index("RUN_ERROR")
    assert run.status != "finished"
