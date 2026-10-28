"""Tests for llm_from_config, model capability checks, and agent hot-reload."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from dataclaw.config.resolver import invalidate_cache
from dataclaw.providers.llm.capabilities import (
    ANTHROPIC,
    GEMINI,
    OPENAI,
    supports_reasoning_effort,
    supports_text_verbosity,
)
from dataclaw.providers.llm.implementations.factory import llm_from_config
from dataclaw.providers.llm.implementations.langchain_llm import LangChainLLM
from dataclaw.providers.llm.implementations.mock_llm import MockLLM
from dataclaw.providers.llm.implementations.openai_responses import OpenAIResponsesLLM
from dataclaw.providers.llm.registry import LLMConfigurationError

_ENV = [
    "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL",
    "OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_BASE_URL",
    "GOOGLE_API_KEY", "GEMINI_MODEL",
    "CODEX_MODEL", "CODEX_AUTH_MODE",
    "DATACLAW_UTILITY_BACKEND", "DATACLAW_LLM_BACKEND", "DATACLAW_AGENT_RUNTIME",
    "DATACLAW_HERMES_UTILITY_MODEL",
]


@pytest.fixture(autouse=True)
def clean_llm_env(monkeypatch: pytest.MonkeyPatch):
    for name in _ENV:
        monkeypatch.delenv(name, raising=False)
    invalidate_cache()
    yield
    invalidate_cache()


# ── llm_from_config ────────────────────────────────────────────────────────


def test_mock_backend():
    assert isinstance(llm_from_config(backend="mock"), MockLLM)


@pytest.mark.parametrize(
    ("backend", "env_var"),
    [("anthropic", "ANTHROPIC_API_KEY"), ("openai", "OPENAI_API_KEY"), ("gemini", "GOOGLE_API_KEY")],
)
def test_missing_key_raises_configuration_error(backend, env_var):
    # No silent MockLLM fallback: the error names where to put the key.
    with pytest.raises(LLMConfigurationError) as exc_info:
        llm_from_config(backend=backend)
    message = str(exc_info.value)
    assert env_var in message
    assert f"llm.backends.{backend}.api_key" in message


def test_anthropic_backend(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    llm = llm_from_config(backend="anthropic")
    assert isinstance(llm, LangChainLLM)
    assert type(llm._model).__name__ == "ChatAnthropic"
    assert llm._model.model == "claude-opus-5-5"
    # Catalog max output (128K) capped; never a thinking budget.
    assert llm._model.max_tokens == 32_000
    assert llm._model.thinking is None
    assert llm_from_config(backend="anthropic", model="claude-opus-4-5")._model.model == "claude-opus-4-5"


def test_openai_backend_uses_responses_api(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    llm = llm_from_config(backend="openai")
    assert isinstance(llm, OpenAIResponsesLLM)
    assert llm._model == "gpt-6.1-sol"
    assert str(llm._client.base_url) == "https://api.openai.com/v1/"
    assert llm._client.api_key == "sk-test"


def test_openai_custom_base_url_uses_chat_completions(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:9999/v1")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o")
    llm = llm_from_config(backend="openai")
    assert isinstance(llm, LangChainLLM)
    assert type(llm._model).__name__ == "ChatOpenAI"
    assert llm._model.model_name == "gpt-4o"
    assert llm._model.openai_api_base == "http://localhost:9999/v1"
    assert llm._model.stream_usage is True


def test_gemini_backend(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "g-test")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3-flash")
    llm = llm_from_config(backend="gemini")
    assert isinstance(llm, LangChainLLM)
    assert type(llm._model).__name__ == "ChatGoogleGenerativeAI"
    assert llm._model.model.endswith("gemini-3-flash")


def test_codex_backend(monkeypatch):
    from dataclaw.auth import codex_bridge

    seen = {}

    def fake_creds(*, auth_mode, api_key):
        seen.update(auth_mode=auth_mode, api_key=api_key)
        return codex_bridge.CodexCredentials(
            api_key="tok", base_url="https://example.invalid/codex", headers={"x-test": "1"}
        )

    monkeypatch.setattr(codex_bridge, "resolve_codex_credentials", fake_creds)
    llm = llm_from_config(backend="codex")
    assert isinstance(llm, OpenAIResponsesLLM)
    assert llm._model == "gpt-5.5"
    assert str(llm._client.base_url).startswith("https://example.invalid/codex")
    assert seen == {"auth_mode": "default", "api_key": ""}


def test_utility_backend_used_when_backend_omitted(monkeypatch):
    monkeypatch.setenv("DATACLAW_UTILITY_BACKEND", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    llm = llm_from_config()
    assert isinstance(llm, OpenAIResponsesLLM)


def test_unknown_backend_raises():
    with pytest.raises(ValueError, match="Unknown LLM backend"):
        llm_from_config(backend="dataclaw")


# ── capability checks ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("provider", "model", "expected"),
    [
        (OPENAI, "gpt-4o", False),
        (OPENAI, "gpt-4.1-mini", False),
        (OPENAI, "gpt-5", True),
        (OPENAI, "gpt-5.5", True),
        (OPENAI, "gpt-5-codex", True),
        (OPENAI, "gpt-5-chat-latest", False),
        (OPENAI, "o3", True),
        (OPENAI, "o4-mini", True),
        (OPENAI, "openai/gpt-5", True),
        (ANTHROPIC, "claude-sonnet-4-20250514", False),
        (ANTHROPIC, "claude-3-5-sonnet-20240620", False),
        (ANTHROPIC, "claude-haiku-4-5", False),
        (ANTHROPIC, "claude-opus-4-5-20251101", True),
        (ANTHROPIC, "claude-sonnet-4-6", True),
        (ANTHROPIC, "claude-opus-5-5", True),
        (GEMINI, "gemini-2.5-flash", False),
        (GEMINI, "models/gemini-3-pro-preview", True),
        ("unknown", "gpt-5", False),
        (OPENAI, "", False),
    ],
)
def test_supports_reasoning_effort(provider, model, expected):
    assert supports_reasoning_effort(provider, model) is expected


@pytest.mark.parametrize(
    ("provider", "model", "expected"),
    [
        (OPENAI, "gpt-5", True),
        (OPENAI, "gpt-5.5", True),
        (OPENAI, "gpt-5-codex", False),
        (OPENAI, "gpt-4o", False),
        (OPENAI, "o3", False),
        (ANTHROPIC, "claude-opus-5-5", False),
    ],
)
def test_supports_text_verbosity(provider, model, expected):
    assert supports_text_verbosity(provider, model) is expected


# ── _reload_llm_agent ──────────────────────────────────────────────────────


def test_reload_dataclaw_runtime_uses_utility_backend(monkeypatch):
    from dataclaw.api.routers.config import _reload_llm_agent
    from dataclaw.providers.agent.implementations.langchain_agent import LangChainAgentProvider

    monkeypatch.setenv("DATACLAW_UTILITY_BACKEND", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5")
    providers = SimpleNamespace()

    _reload_llm_agent(providers, "dataclaw")

    assert isinstance(providers.llm, OpenAIResponsesLLM)
    assert providers.llm._model == "gpt-5"
    assert isinstance(providers.agent, LangChainAgentProvider)
    assert providers.compaction._llm is providers.llm


@pytest.mark.parametrize(("runtime", "expected"), [("mock", MockLLM), ("anthropic", LangChainLLM)])
def test_reload_mock_and_legacy_backend_names(monkeypatch, runtime, expected):
    from dataclaw.api.routers.config import _reload_llm_agent

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    providers = SimpleNamespace()
    _reload_llm_agent(providers, runtime)
    assert isinstance(providers.llm, expected)
