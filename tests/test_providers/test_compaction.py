"""Tests for compaction providers."""

import pytest

from tests.conftest import MockCompactionProvider


@pytest.mark.asyncio
async def test_mock_compaction_passthrough():
    provider = MockCompactionProvider()
    messages = [{"role": "user", "content": f"msg {i}"} for i in range(5)]
    result = await provider.compact(messages)
    assert len(result) == 5
