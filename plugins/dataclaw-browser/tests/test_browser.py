"""Tests for browser plugin — disabled mode and config."""

import os
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


def _install_fake_chat_classes(monkeypatch) -> dict:
    created: dict = {}

    def _factory(name):
        def _init(**kwargs):
            created[name] = kwargs
            return (name, kwargs)
        return _init

    fake_browser_use = types.ModuleType("browser_use")
    fake_browser_use.ChatAnthropic = _factory("anthropic")
    fake_browser_use.ChatOpenAI = _factory("openai")
    fake_browser_use.ChatGoogle = _factory("gemini")
    monkeypatch.setitem(sys.modules, "browser_use", fake_browser_use)
    return created


@pytest.mark.parametrize(
    ("provider", "env_var", "default_model"),
    [
        ("anthropic", "ANTHROPIC_API_KEY", "claude-opus-5-5"),
        ("openai", "OPENAI_API_KEY", "gpt-6.1-sol"),
        ("gemini", "GOOGLE_API_KEY", "gemini-4-argon"),
    ],
)
def test_create_llm_passes_keys_explicitly_and_uses_registry_defaults(
    monkeypatch, provider, env_var, default_model,
):
    from dataclaw.config.resolver import invalidate_cache
    from dataclaw_browser.tools import _create_llm

    created = _install_fake_chat_classes(monkeypatch)
    monkeypatch.delenv(env_var, raising=False)
    invalidate_cache()
    before = dict(os.environ)

    _create_llm(provider, "", "sk-override")

    assert created[provider] == {"model": default_model, "api_key": "sk-override"}
    assert dict(os.environ) == before

    # Without an override, DataClaw's own resolved key is passed through.
    monkeypatch.setenv(env_var, "sk-from-dataclaw")
    _create_llm(provider, "custom-model", "")
    assert created[provider] == {"model": "custom-model", "api_key": "sk-from-dataclaw"}
