"""Tests for the agent loop."""

import pytest

from dataclaw.loop.runner import run_loop
from dataclaw.plugins.registry import ProviderRegistry
from dataclaw.hooks.registry import HookRegistry


@pytest.mark.asyncio
async def test_basic_message_loop(mock_providers, hooks):
    """Test the simplest path: user sends message, agent responds with text."""
    result = await run_loop(
        session_id="test-session",
        user_query="Hello",
        messages=[{"role": "user", "content": "Hello"}],
        providers=mock_providers,
        hooks=hooks,
        max_turns=5,
    )

    # Should have completed
    assert result is not None
    assert result.get("session_id") == "test-session"
    # Agent should have set turn > 0
    assert result.get("turn", 0) >= 1


@pytest.mark.asyncio
async def test_loop_with_tool_call(mock_providers, hooks):
    """Test agent making a tool call that gets executed."""
    # Set up a mock tool
    async def echo_tool(**kwargs):
        return {"echo": kwargs}

    from tests.conftest import MockAgentProvider, MockToolAvailabilityProvider
    from dataclaw.providers.llm.provider import PendingToolCall, TextDeltaEvent, TurnCompleteEvent

    call_count = 0

    class ToolCallingAgent:
        @classmethod
        def config_schema(cls):
            return []

        async def stream_turn(self, state):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First turn: make a tool call
                yield PendingToolCall(call_id="c1", tool_name="echo", tool_input={"msg": "test"})
                yield TurnCompleteEvent(has_pending_tool_calls=True)
            else:
                # Second turn: respond with text
                yield TextDeltaEvent(text="Done!")
                yield TurnCompleteEvent(has_pending_tool_calls=False)

    mock_providers.agent = ToolCallingAgent()
    mock_providers.tool_availability = MockToolAvailabilityProvider(
        tools=[{"name": "echo", "description": "Echo tool", "parameters": {}}],
        callables={"echo": echo_tool},
    )

    result = await run_loop(
        session_id="test-session",
        user_query="Use echo tool",
        messages=[{"role": "user", "content": "Use echo tool"}],
        providers=mock_providers,
        hooks=hooks,
        max_turns=5,
    )

    assert result is not None
    assert call_count == 2  # Agent was called twice (tool call + response)
