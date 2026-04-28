"""Tests for memory providers."""

import pytest

from dataclaw.providers.memory.implementations.noop import NoopMemoryProvider


@pytest.mark.asyncio
async def test_noop_memory_retrieve():
    provider = NoopMemoryProvider()
    result = await provider.retrieve_memories({"session_id": "test", "messages": []})
    assert result == []


@pytest.mark.asyncio
async def test_noop_memory_search():
    provider = NoopMemoryProvider()
    result = await provider.search_memory("test query")
    assert result == []


def test_noop_memory_tool_definition():
    provider = NoopMemoryProvider()
    assert provider.as_tool_definition() is None
