"""Shared test fixtures — mock providers for testing."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, AsyncIterator

import pytest

from dataclaw.hooks.registry import HookRegistry
from dataclaw.providers.llm.provider import (
    BrokerEvent,
    PendingToolCall,
    TextDeltaEvent,
    TurnCompleteEvent,
)
from dataclaw.plugins.registry import ProviderRegistry
from dataclaw.schema import Message
from dataclaw.state import AgentState


# ── Override DATACLAW_HOME for tests ────────────────────────────────────────

@pytest.fixture(autouse=True)
def tmp_dataclaw_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Set DATACLAW_HOME to a temp dir for all tests."""
    home = tmp_path / ".dataclaw"
    home.mkdir()
    monkeypatch.setenv("DATACLAW_HOME", str(home))
    # Reimport paths to pick up new env
    import dataclaw.config.paths as paths
    monkeypatch.setattr(paths, "DATACLAW_HOME", home)
    return home


# ── Mock Providers ──────────────────────────────────────────────────────────


class MockCompactionProvider:
    async def compact(self, messages, *, max_messages=30, keep_recent=8):
        return messages


class MockSystemPromptProvider:
    async def build_system_prompt(self, state):
        return "You are a test assistant."


class MockMemoryProvider:
    async def retrieve_memories(self, state):
        return []

    async def search_memory(self, query, *, limit=10):
        return []

    def as_tool_definition(self):
        return None


class MockSkillProvider:
    async def resolve_skills(self, state):
        return []

    async def format_for_prompt(self, skills):
        return []

    async def fetch_skill(self, skill_id):
        return None


class MockToolAvailabilityProvider:
    def __init__(self, tools=None, callables=None):
        self._tools = tools or []
        self._callables = callables or {}

    async def resolve_tools(self, state):
        return self._tools, self._callables


class MockLLMProvider:
    """Mock LLM that returns a fixed response."""

    def __init__(self, response_text: str = "Hello from mock!", tool_calls: list | None = None):
        self._response_text = response_text
        self._tool_calls = tool_calls or []

    async def stream_turn(self, messages, *, system, tools) -> AsyncIterator[BrokerEvent]:
        yield TextDeltaEvent(text=self._response_text)
        for tc in self._tool_calls:
            yield PendingToolCall(**tc)
        yield TurnCompleteEvent(has_pending_tool_calls=bool(self._tool_calls))

    def build_tool_result_message(self, tool_calls, results, errors):
        assistant_content = []
        for tc in tool_calls:
            assistant_content.append({
                "type": "tool_call", "id": tc.call_id,
                "name": tc.tool_name, "input": tc.tool_input,
            })
        tool_results = []
        for tc, result, err in zip(tool_calls, results, errors):
            import json
            tool_results.append({
                "type": "tool_result", "call_id": tc.call_id,
                "content": json.dumps(result, default=str),
                "is_error": err is not None,
            })
        return [
            Message(role="assistant", content=assistant_content),
            Message(role="user", content=tool_results),
        ]


class MockAgentProvider:
    """Mock agent that returns fixed text."""

    def __init__(self, response_text: str = "Agent response"):
        self._response_text = response_text

    @classmethod
    def config_schema(cls):
        return []

    async def stream_turn(self, state) -> AsyncIterator[BrokerEvent]:
        yield TextDeltaEvent(text=self._response_text)
        yield TurnCompleteEvent(has_pending_tool_calls=False)


@pytest.fixture
def mock_providers() -> ProviderRegistry:
    """Create a ProviderRegistry with all mock providers."""
    registry = ProviderRegistry()
    registry.compaction = MockCompactionProvider()
    registry.system_prompt = MockSystemPromptProvider()
    registry.memory = MockMemoryProvider()
    registry.skill = MockSkillProvider()
    registry.tool_availability = MockToolAvailabilityProvider()
    registry.llm = MockLLMProvider()
    registry.agent = MockAgentProvider()
    return registry


@pytest.fixture
def hooks() -> HookRegistry:
    return HookRegistry()
