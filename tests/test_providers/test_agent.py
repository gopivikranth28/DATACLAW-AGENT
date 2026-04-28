"""Tests for agent providers."""

import pytest

from dataclaw.providers.llm.provider import TextDeltaEvent, TurnCompleteEvent
from tests.conftest import MockAgentProvider


@pytest.mark.asyncio
async def test_mock_agent_response():
    agent = MockAgentProvider(response_text="Test response")
    events = []
    async for event in agent.stream_turn({"session_id": "t", "messages": [], "tools": [], "system_prompt": ""}):
        events.append(event)

    assert any(isinstance(e, TextDeltaEvent) and e.text == "Test response" for e in events)
    assert any(isinstance(e, TurnCompleteEvent) for e in events)
