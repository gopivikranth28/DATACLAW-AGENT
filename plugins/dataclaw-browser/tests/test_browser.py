"""Tests for browser plugin — disabled mode and config."""

import sys
import types

import pytest

from dataclaw_browser.tools import browser_use


@pytest.mark.asyncio
async def test_browser_disabled():
    result = await browser_use(task="search for something", enabled=False)
    assert "disabled" in result["error"]


@pytest.mark.asyncio
async def test_browser_missing_library(monkeypatch):
    """A missing browser-use package is reported without touching browser APIs."""
    monkeypatch.setitem(sys.modules, "browser_use", None)

    result = await browser_use(
        task="test", enabled=True,
        llm_provider="nonexistent", llm_model="x",
        timeout=5, timeout_max=5,
    )

    assert result == {"error": "browser-use is not installed. Run: pip install browser-use"}


@pytest.mark.asyncio
async def test_browser_unsupported_provider_without_real_browser(monkeypatch):
    """Unsupported provider handling is tested against a fake browser-use module."""
    fake_browser_use = types.ModuleType("browser_use")
    fake_browser_use.Agent = object
    fake_browser_use.BrowserProfile = object
    monkeypatch.setitem(sys.modules, "browser_use", fake_browser_use)

    result = await browser_use(
        task="test", enabled=True,
        llm_provider="nonexistent", llm_model="x",
        timeout=5, timeout_max=5,
    )

    assert result == {"error": "Unsupported LLM provider: nonexistent"}
