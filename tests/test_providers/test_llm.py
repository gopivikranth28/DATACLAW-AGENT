"""Tests for LLM providers."""

import pytest

from dataclaw.providers.llm.provider import TextDeltaEvent, TurnCompleteEvent
from tests.conftest import MockLLMProvider


@pytest.mark.asyncio
async def test_mock_llm_text_response():
    llm = MockLLMProvider(response_text="Hello!")
    events = []
    async for event in llm.stream_turn(
        [{"role": "user", "content": "hi"}],
        system="test",
        tools=[],
    ):
        events.append(event)

    assert any(isinstance(e, TextDeltaEvent) and e.text == "Hello!" for e in events)
    assert any(isinstance(e, TurnCompleteEvent) and not e.has_pending_tool_calls for e in events)
