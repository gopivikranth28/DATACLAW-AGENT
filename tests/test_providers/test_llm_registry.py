"""Tests for the LLM backend registry, presets, catalog metadata and effort checks."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from dataclaw.config.resolver import invalidate_cache, resolve_utility_backend, resolve_utility_model
from dataclaw.providers.llm.capabilities import (
    ANTHROPIC,
    GEMINI,
    OPENAI,
    resolve_reasoning_effort,
    supports_reasoning_effort,
)
from dataclaw.providers.llm.catalog import enrich_model, lookup_model_info, nearest_effort
from dataclaw.providers.llm.implementations.factory import llm_from_config
from dataclaw.providers.llm.implementations.langchain_llm import LangChainLLM, _native_request_kwargs
from dataclaw.providers.llm.implementations.mock_llm import MockLLM
from dataclaw.providers.llm.implementations.openai_compatible import CompatibleChatOpenAI
from dataclaw.providers.llm.implementations.openai_responses import OpenAIResponsesLLM
from dataclaw.providers.llm.registry import (
    KEYLESS_API_KEY,
    LLMBackendSpec,
    LLMConfigurationError,
    get_llm_backend,
    list_llm_backends,
    llm_backend_ids,
    register_llm_backend,
    resolve_backend_config,
    unregister_llm_backend,
    utility_backend_ids,
)

_ENV = [
    "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL",
    "OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_BASE_URL",
    "GOOGLE_API_KEY", "GEMINI_MODEL",
    "CODEX_MODEL", "CODEX_AUTH_MODE", "CODEX_BIN",
    "OPENROUTER_API_KEY", "GROQ_API_KEY", "XAI_API_KEY", "DEEPSEEK_API_KEY",
    "MISTRAL_API_KEY", "TOGETHER_API_KEY",
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


def _write_config(home: Path, config: dict) -> None:
    (home / "dataclaw.config.json").write_text(json.dumps(config))
    invalidate_cache()


# ── registry and derived lists ─────────────────────────────────────────────


def test_builtin_backends_and_derived_lists():
    from dataclaw.config import migrations
    from dataclaw.providers.agent.implementations.langchain_agent import LangChainAgentProvider

    assert utility_backend_ids() == {
        "anthropic", "openai", "gemini", "codex", "openrouter", "openai_compatible", "open_responses",
    }
    # mock can be built but is never offered as a utility backend.
    assert llm_backend_ids() == utility_backend_ids() | {"mock"}
    assert migrations._utility_backends() == utility_backend_ids()

    schema = {f.name: f for f in LangChainAgentProvider.config_schema()}
    assert {o["value"] for o in schema["llm_backend"].options} == llm_backend_ids()


@pytest.mark.parametrize(
    ("backend", "default", "utility"),
    [
        ("anthropic", "claude-opus-5-5", "claude-haiku-5-5"),
        ("openai", "gpt-6.1-sol", "gpt-6-luna"),
        ("gemini", "gemini-4-argon", "gemini-3.8-flash"),
        ("codex", "gpt-5.5", "gpt-5.5"),
        ("openrouter", "anthropic/claude-opus-5.5", "anthropic/claude-haiku-5.5"),
    ],
)
def test_default_models_come_from_registry(backend, default, utility):
    spec = get_llm_backend(backend)
    assert spec.default_model_for("agent") == default
    assert spec.default_model_for("utility") == utility


def test_utility_model_default_depends_on_runtime(monkeypatch):
    monkeypatch.setenv("DATACLAW_AGENT_RUNTIME", "dataclaw")
    assert resolve_utility_model("anthropic") == "claude-opus-5-5"
    monkeypatch.setenv("DATACLAW_AGENT_RUNTIME", "hermes")
    assert resolve_utility_model("anthropic") == "claude-haiku-5-5"
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")
    assert resolve_utility_model("anthropic") == "claude-sonnet-5-5"


def test_new_backends_are_valid_utility_backends(monkeypatch):
    monkeypatch.setenv("DATACLAW_UTILITY_BACKEND", "openai_compatible")
    assert resolve_utility_backend() == "openai_compatible"


def _fake_spec(backend_id: str = "acme") -> LLMBackendSpec:
    return LLMBackendSpec(
        id=backend_id,
        label="Acme",
        transport="openai_chat",
        build=lambda cfg, model: MockLLM(),
        requires_api_key=False,
        default_model="acme-1",
    )


def test_plugin_context_registers_llm_backend():
    from dataclaw.plugins.base import PluginContext
    from dataclaw.plugins.registry import ProviderRegistry

    ctx = PluginContext(hooks=None, providers=ProviderRegistry(), app=None, config=None, tool_registry=None)  # type: ignore[arg-type]
    try:
        ctx.register_llm_backend(_fake_spec())
        assert "acme" in utility_backend_ids()
        assert isinstance(llm_from_config(backend="acme"), MockLLM)
        # Re-registering (a new app in the same process) replaces the spec.
        ctx.register_llm_backend(_fake_spec())
    finally:
        unregister_llm_backend("acme")
    assert "acme" not in utility_backend_ids()


def test_builtin_backends_cannot_be_replaced():
    with pytest.raises(ValueError, match="built in"):
        register_llm_backend(_fake_spec("openai"))


def test_unknown_backend_raises():
    with pytest.raises(ValueError, match="Unknown LLM backend"):
        llm_from_config(backend="nope")


@pytest.mark.asyncio
async def test_llm_backends_endpoint_shape():
    from dataclaw.api.routers.providers import list_llm_backends as endpoint

    payload = await endpoint()
    by_id = {entry["id"]: entry for entry in payload}
    assert "mock" not in by_id
    assert set(by_id) == utility_backend_ids()

    anthropic = by_id["anthropic"]
    assert anthropic["default_model"] == "claude-opus-5-5"
    assert anthropic["utility_default_model"] == "claude-haiku-5-5"
    assert anthropic["requires_api_key"] is True
    key_field = next(f for f in anthropic["fields"] if f["name"] == "api_key")
    assert key_field["field_type"] == "secret"
    assert key_field["env"] == "ANTHROPIC_API_KEY"

    compat = by_id["openai_compatible"]
    assert compat["transport"] == "openai_chat"
    assert compat["requires_api_key"] is False
    presets = {p["id"]: p for p in compat["presets"]}
    assert presets["ollama"] == {
        "id": "ollama",
        "label": "Ollama",
        "base_url": "http://localhost:11434/v1",
        "default_model": "",
        "requires_api_key": False,
        "api_key_env": None,
        "headers": {},
        "notes": presets["ollama"]["notes"],
        "deprecated": False,
    }
    assert {f["name"] for f in compat["fields"]} >= {"preset", "base_url", "api_key", "model", "headers", "reasoning_effort"}
    # The OpenRouter preset still resolves (deprecated) but is not offered.
    assert presets["openrouter"]["deprecated"] is True
    preset_field = next(f for f in compat["fields"] if f["name"] == "preset")
    assert "openrouter" not in {o["value"] for o in preset_field["options"]}

    openrouter = by_id["openrouter"]
    assert openrouter["transport"] == "openai_chat"
    assert openrouter["requires_api_key"] is True
    assert openrouter["supports_model_listing"] is True
    assert {f["name"] for f in openrouter["fields"]} == {"api_key", "model", "reasoning_effort", "headers", "routing"}
    assert next(f for f in openrouter["fields"] if f["name"] == "api_key")["env"] == "OPENROUTER_API_KEY"
    assert json.dumps(payload)  # JSON-serializable


# ── backend construction (no network) ──────────────────────────────────────


def test_anthropic_reasoning_effort_from_config(tmp_dataclaw_home):
    _write_config(tmp_dataclaw_home, {
        "llm": {"backends": {"anthropic": {"api_key": "sk-ant", "reasoning_effort": "high"}}},
    })
    llm = llm_from_config(backend="anthropic")
    assert isinstance(llm, LangChainLLM)
    assert llm._default_reasoning_effort == "high"
    assert llm._model.anthropic_api_key.get_secret_value() == "sk-ant"


def test_openai_explicit_chat_completions(tmp_dataclaw_home):
    _write_config(tmp_dataclaw_home, {
        "llm": {"backends": {"openai": {"api_key": "sk", "api": "chat_completions", "model": "gpt-6-luna"}}},
    })
    llm = llm_from_config(backend="openai")
    assert isinstance(llm, LangChainLLM)
    assert type(llm._model).__name__ == "ChatOpenAI"
    assert llm._model.model_name == "gpt-6-luna"


def test_openai_responses_request_is_stateless(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk")
    llm = llm_from_config(backend="openai")
    kwargs = llm._request_kwargs([], "sys", [], "minimal", None)
    assert kwargs["store"] is False
    assert kwargs["include"] == ["reasoning.encrypted_content"]
    # gpt-6.1-sol has no "minimal": the nearest supported level is sent.
    assert kwargs["reasoning"] == {"effort": "low"}


def test_gemini_backend(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "g-test")
    llm = llm_from_config(backend="gemini")
    assert type(llm._model).__name__ == "ChatGoogleGenerativeAI"
    assert llm._model.model.endswith("gemini-4-argon")


def test_open_responses_keyless_custom_endpoint(tmp_dataclaw_home, monkeypatch):
    # The user's OpenAI key must never reach a third-party endpoint.
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-openai")
    _write_config(tmp_dataclaw_home, {
        "llm": {"backends": {"open_responses": {
            "base_url": "http://localhost:8001/v1/",
            "model": "my-model",
            "headers": {"X-Gateway": "dc"},
        }}},
    })
    llm = llm_from_config(backend="open_responses")
    assert isinstance(llm, OpenAIResponsesLLM)
    assert str(llm._client.base_url) == "http://localhost:8001/v1/"
    assert llm._client.api_key == KEYLESS_API_KEY
    assert llm._client.default_headers["X-Gateway"] == "dc"
    llm.prompt_cache_key = "thread"
    kwargs = llm._request_kwargs([], "sys", [], "high", "low")
    # OpenAI-only extras are not sent to a third-party server, and an
    # uncatalogued model gets no reasoning effort.
    assert "prompt_cache_key" not in kwargs
    assert "text" not in kwargs
    assert "reasoning" not in kwargs


def test_open_responses_requires_base_url_and_model(tmp_dataclaw_home):
    with pytest.raises(LLMConfigurationError, match="llm.backends.open_responses.base_url"):
        llm_from_config(backend="open_responses")
    _write_config(tmp_dataclaw_home, {"llm": {"backends": {"open_responses": {"base_url": "http://x/v1"}}}})
    with pytest.raises(LLMConfigurationError, match="llm.backends.open_responses.model"):
        llm_from_config(backend="open_responses")


@pytest.mark.parametrize(
    ("preset", "base_url"),
    [
        ("ollama", "http://localhost:11434/v1"),
        ("lmstudio", "http://localhost:1234/v1"),
        ("vllm", "http://localhost:8001/v1"),
    ],
)
def test_openai_compatible_keyless_presets(tmp_dataclaw_home, monkeypatch, preset, base_url):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-openai")
    _write_config(tmp_dataclaw_home, {
        "llm": {"backends": {"openai_compatible": {"preset": preset, "model": "qwen3"}}},
    })
    llm = llm_from_config(backend="openai_compatible")
    assert isinstance(llm, LangChainLLM)
    assert isinstance(llm._model, CompatibleChatOpenAI)
    assert llm._model.openai_api_base == base_url
    assert llm._model.openai_api_key.get_secret_value() == KEYLESS_API_KEY
    assert llm._model.stream_usage is True
    assert llm._compat is True


def test_openai_compatible_openrouter_headers_and_key_env(tmp_dataclaw_home, monkeypatch):
    _write_config(tmp_dataclaw_home, {
        "llm": {"backends": {"openai_compatible": {
            "preset": "openrouter",
            "model": "anthropic/claude-opus-5-5",
            "headers": {"X-Title": "Custom"},
        }}},
    })
    with pytest.raises(LLMConfigurationError) as exc_info:
        llm_from_config(backend="openai_compatible")
    assert "OPENROUTER_API_KEY" in str(exc_info.value)
    assert "llm.backends.openai_compatible.api_key" in str(exc_info.value)

    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    llm = llm_from_config(backend="openai_compatible")
    assert llm._model.openai_api_base == "https://openrouter.ai/api/v1"
    assert llm._model.openai_api_key.get_secret_value() == "or-key"
    # Preset headers, with configured headers taking precedence.
    assert llm._model.default_headers == {
        "HTTP-Referer": "https://github.com/gopivikranth28/DATACLAW-AGENT",
        "X-Title": "Custom",
    }


def test_openai_compatible_preset_default_model(tmp_dataclaw_home):
    _write_config(tmp_dataclaw_home, {
        "llm": {"backends": {"openai_compatible": {"preset": "xai", "api_key": "xai-key"}}},
    })
    assert llm_from_config(backend="openai_compatible")._model.model_name == "grok-4.7"
    assert resolve_utility_model("openai_compatible") == "grok-4.7"


def test_openai_compatible_custom_endpoint_needs_url(tmp_dataclaw_home):
    with pytest.raises(LLMConfigurationError, match="base_url or choose a preset"):
        llm_from_config(backend="openai_compatible", model="m")


def test_compatible_client_sends_system_role():
    model = CompatibleChatOpenAI(model="o3-mini", api_key="k", base_url="http://localhost:1/v1")  # type: ignore[arg-type]
    payload = model._get_request_payload([SystemMessage(content="s"), HumanMessage(content="h")])
    assert [m["role"] for m in payload["messages"]] == ["system", "user"]


def test_compat_mode_gates_effort_on_catalog_and_drops_verbosity():
    compat_model = CompatibleChatOpenAI(model="gpt-oss-120b", api_key="k", base_url="http://localhost:1/v1")  # type: ignore[arg-type]
    # gpt-oss would pass the prefix rules, but compat mode requires the catalog.
    assert _native_request_kwargs(compat_model, "high", "low", compat=True) == {}
    known = CompatibleChatOpenAI(model="openai/gpt-6.1-sol", api_key="k", base_url="http://localhost:1/v1")  # type: ignore[arg-type]
    assert _native_request_kwargs(known, "high", "low", compat=True) == {"reasoning_effort": "high"}


# ── secrets and config resolution ──────────────────────────────────────────


def test_unmigrated_legacy_section_still_resolves(tmp_dataclaw_home):
    _write_config(tmp_dataclaw_home, {"llm": {"anthropic": {"api_key": "legacy-key", "model": "claude-x"}}})
    cfg = resolve_backend_config("anthropic")
    assert cfg.api_key == "legacy-key"
    assert cfg.model == "claude-x"


def test_new_section_wins_over_legacy_and_env_wins_over_both(tmp_dataclaw_home, monkeypatch):
    _write_config(tmp_dataclaw_home, {"llm": {
        "anthropic": {"api_key": "legacy-key"},
        "backends": {"anthropic": {"api_key": "new-key"}},
    }})
    assert resolve_backend_config("anthropic").api_key == "new-key"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")
    assert resolve_backend_config("anthropic").api_key == "env-key"
    assert resolve_backend_config("anthropic", {"api_key": "typed"}).api_key == "typed"


# ── catalog metadata and effort validation ─────────────────────────────────


def test_catalog_lookup_uses_longest_prefix_and_gateway_ids():
    sol = lookup_model_info("openai/gpt-6.1-sol-2026-09-01")
    assert sol is not None
    assert sol.context_window == 1_050_000
    assert sol.max_output == 128_000
    assert "none" not in sol.reasoning_efforts
    luna = lookup_model_info("gpt-6-luna")
    assert luna.reasoning_efforts[0] == "none"
    opus = lookup_model_info("claude-opus-5-5")
    assert opus.supports_reasoning and opus.reasoning_efforts == ["low", "medium", "high", "xhigh", "max"]
    assert lookup_model_info("totally-unknown") is None


def test_enrich_model_prefers_reported_values():
    info = enrich_model("gemini-4-argon", "Gemini Argon", transport="gemini", reported={"max_output": 65536})
    assert info.label == "Gemini Argon"
    assert info.context_window == 1_000_000
    assert info.max_output == 65536
    assert info.transport == "gemini"
    unknown = enrich_model("local-llama", transport="openai_chat")
    assert unknown.supports_reasoning is False and unknown.reasoning_efforts == []


@pytest.mark.parametrize(
    ("requested", "supported", "expected"),
    [
        ("high", ["low", "medium", "high"], "high"),
        ("minimal", ["low", "medium", "high", "xhigh", "max"], "low"),
        ("minimal", ["none", "low", "high"], "low"),
        ("none", ["low", "high"], "low"),
        ("max", ["low", "medium", "high"], "high"),
        ("ultra", ["low", "high"], None),
        ("high", [], None),
    ],
)
def test_nearest_effort(requested, supported, expected):
    assert nearest_effort(requested, supported) == expected


@pytest.mark.parametrize(
    ("provider", "model", "effort", "expected"),
    [
        (ANTHROPIC, "claude-opus-5-5", "minimal", "low"),
        (ANTHROPIC, "claude-haiku-5-5", "xhigh", "xhigh"),
        (OPENAI, "gpt-6-luna", "none", "none"),
        (OPENAI, "gpt-6.1-sol", "none", "low"),
        (OPENAI, "gpt-4o", "high", None),
        (GEMINI, "gemini-4-argon", "medium", "high"),
        # Not in the catalog: prefix rules decide, value passes through.
        (OPENAI, "gpt-5", "medium", "medium"),
        (ANTHROPIC, "claude-sonnet-4-20250514", "high", None),
        (OPENAI, "gpt-5", None, None),
    ],
)
def test_resolve_reasoning_effort(provider, model, effort, expected):
    assert resolve_reasoning_effort(provider, model, effort) == expected


def test_catalog_only_skips_prefix_rules():
    assert supports_reasoning_effort(OPENAI, "gpt-5") is True
    assert supports_reasoning_effort(OPENAI, "gpt-5", catalog_only=True) is False
    assert supports_reasoning_effort(OPENAI, "gpt-6.1-sol", catalog_only=True) is True


def test_listed_backends_have_unique_ids():
    ids = [spec.id for spec in list_llm_backends(include_hidden=True)]
    assert len(ids) == len(set(ids))
