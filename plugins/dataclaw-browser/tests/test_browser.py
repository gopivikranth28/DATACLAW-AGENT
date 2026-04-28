"""Tests for browser plugin — disabled mode and config."""

import pytest

from dataclaw_browser.tools import browser_use


@pytest.mark.asyncio
async def test_browser_disabled():
    result = await browser_use(task="search for something", enabled=False)
    assert "disabled" in result["error"]


@pytest.mark.asyncio
async def test_browser_missing_library():
    """When browser-use is importable but we test the wrapper logic."""
    # This tests the tool function directly with enabled=True
    # but without a real browser — will either fail on import or on LLM creation
    result = await browser_use(
        task="test", enabled=True,
        llm_provider="nonexistent", llm_model="x",
        timeout=5, timeout_max=5,
    )
    # Should get an error about unsupported provider or missing library
    assert "error" in result or result.get("success") is False
