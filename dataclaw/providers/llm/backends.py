"""Built-in LLM backends registered in ``registry``.

SDK imports stay inside the build functions so listing backends (settings
UI, config migration) never imports langchain or openai.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from dataclaw.providers.config_field import ConfigField
from dataclaw.providers.llm.catalog import ModelInfo, lookup_model_info
from dataclaw.providers.llm.model_listing import (
    ModelCatalogError,
    ModelCatalogUnauthenticated,
    fetch_anthropic_models,
    fetch_codex_oauth_models,
    fetch_gemini_models,
    fetch_openai_models,
)
from dataclaw.providers.llm.registry import (
    KEYLESS_API_KEY,
    LLMBackendSpec,
    LLMConfigurationError,
    PresetSpec,
    ResolvedBackendConfig,
)

if TYPE_CHECKING:
    from dataclaw.providers.llm.provider import LLMProvider

logger = logging.getLogger(__name__)

OPENAI_API_BASE = "https://api.openai.com/v1"

# Claude 5 models allow 128K output tokens. A turn that long is almost never
# wanted for agent work and holds a request open for minutes, so the request
# limit is the model's maximum capped here.
ANTHROPIC_MAX_TOKENS_CAP = 32_000


# ── Shared config fields ────────────────────────────────────────────────────


def _api_key_field(env: str | None, *, required: bool = True, description: str = "") -> ConfigField:
    return ConfigField(
        name="api_key",
        field_type="secret",
        label="API key",
        description=description,
        required=required,
        env=env,
    )


def _model_field(env: str | None = None) -> ConfigField:
    return ConfigField(name="model", field_type="string", label="Model", env=env)


def _base_url_field(env: str | None = None, *, required: bool = False, description: str = "") -> ConfigField:
    return ConfigField(
        name="base_url",
        field_type="string",
        label="API endpoint",
        description=description,
        required=required,
        env=env,
    )


_REASONING_FIELD = ConfigField(
    name="reasoning_effort",
    field_type="reasoning_effort",
    label="Reasoning effort",
    description="Default thinking level for models that support it. Leave empty for the model default.",
)

_HEADERS_FIELD = ConfigField(
    name="headers",
    field_type="headers",
    label="Extra headers",
    description="Additional HTTP headers sent with every request, one 'Name: value' per line.",
)


# ── Builders ────────────────────────────────────────────────────────────────


def _require_model(spec_label: str, backend_id: str, model: str) -> None:
    if not model:
        raise LLMConfigurationError(
            f"No model is configured for the {spec_label} backend. "
            f"Set llm.backends.{backend_id}.model."
        )


def _require_base_url(spec_label: str, backend_id: str, cfg: ResolvedBackendConfig) -> str:
    if not cfg.base_url:
        raise LLMConfigurationError(
            f"No API endpoint is configured for the {spec_label} backend. "
            f"Set llm.backends.{backend_id}.base_url or choose a preset."
        )
    return cfg.base_url


def anthropic_max_tokens(model: str) -> int | None:
    """Request max_tokens for a Claude model: its catalog maximum, capped.

    None for models the catalog doesn't know; langchain-anthropic then uses
    its own per-model default.
    """
    info = lookup_model_info(model)
    if info is None or not info.max_output:
        return None
    return min(info.max_output, ANTHROPIC_MAX_TOKENS_CAP)


def _build_anthropic(cfg: ResolvedBackendConfig, model: str) -> "LLMProvider":
    from langchain_anthropic import ChatAnthropic

    from dataclaw.providers.llm.implementations.langchain_llm import LangChainLLM

    kwargs: dict = {"model": model, "api_key": cfg.api_key}
    max_tokens = anthropic_max_tokens(model)
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    # Never set ``thinking``: Claude 5 models think adaptively, steered by
    # output_config.effort, and reject a manual ``budget_tokens``.
    return LangChainLLM(
        ChatAnthropic(**kwargs),
        default_reasoning_effort=cfg.reasoning_effort,
    )


def openai_api_mode(cfg: ResolvedBackendConfig) -> str:
    """``responses`` or ``chat_completions`` for the openai backend.

    An explicit ``api`` wins. Otherwise the Responses API is used against
    OpenAI itself, and Chat Completions against any other endpoint (proxies
    configured before the switch to Responses mostly speak only that).
    """
    api = str(cfg.get("api", "")).strip().lower()
    if api in ("responses", "chat_completions"):
        return api
    if cfg.base_url and cfg.base_url != OPENAI_API_BASE:
        return "chat_completions"
    return "responses"


def _build_openai(cfg: ResolvedBackendConfig, model: str) -> "LLMProvider":
    if openai_api_mode(cfg) == "chat_completions":
        from langchain_openai import ChatOpenAI

        from dataclaw.providers.llm.implementations.langchain_llm import LangChainLLM

        return LangChainLLM(
            ChatOpenAI(
                model=model,
                api_key=cfg.api_key,  # type: ignore[arg-type]
                base_url=cfg.base_url or None,
                # ChatOpenAI only streams usage by default for its own URL.
                stream_usage=True,
            ),
            default_reasoning_effort=cfg.reasoning_effort,
        )

    from dataclaw.providers.llm.implementations.openai_responses import OpenAIResponsesLLM

    return OpenAIResponsesLLM(
        api_key=cfg.api_key,
        base_url=cfg.base_url or OPENAI_API_BASE,
        model=model,
        default_reasoning_effort=cfg.reasoning_effort,
    )


def _build_gemini(cfg: ResolvedBackendConfig, model: str) -> "LLMProvider":
    from langchain_google_genai import ChatGoogleGenerativeAI

    from dataclaw.providers.llm.implementations.langchain_llm import LangChainLLM

    return LangChainLLM(
        ChatGoogleGenerativeAI(model=model, google_api_key=cfg.api_key),  # type: ignore[arg-type]
        default_reasoning_effort=cfg.reasoning_effort,
    )


def _build_codex(cfg: ResolvedBackendConfig, model: str) -> "LLMProvider":
    from dataclaw.auth.codex_bridge import resolve_codex_credentials
    from dataclaw.providers.llm.implementations.openai_responses import OpenAIResponsesLLM

    auth_mode = str(cfg.get("auth_mode", "default"))
    creds = resolve_codex_credentials(auth_mode=auth_mode, api_key=cfg.api_key)
    logger.info("Using Codex LLM backend (model=%s, auth=%s, base_url=%s)", model, auth_mode, creds.base_url)
    return OpenAIResponsesLLM(
        api_key=creds.api_key,
        base_url=creds.base_url,
        model=model,
        default_headers=creds.headers,
        default_reasoning_effort=cfg.reasoning_effort,
    )


def _build_open_responses(cfg: ResolvedBackendConfig, model: str) -> "LLMProvider":
    from dataclaw.providers.llm.implementations.openai_responses import OpenAIResponsesLLM

    base_url = _require_base_url("Open Responses", "open_responses", cfg)
    _require_model("Open Responses", "open_responses", model)
    return OpenAIResponsesLLM(
        api_key=cfg.api_key or KEYLESS_API_KEY,
        base_url=base_url,
        model=model,
        default_headers=cfg.headers,
        default_reasoning_effort=cfg.reasoning_effort,
        compat=True,
    )


def _build_openai_compatible(cfg: ResolvedBackendConfig, model: str) -> "LLMProvider":
    from dataclaw.providers.llm.implementations.langchain_llm import LangChainLLM
    from dataclaw.providers.llm.implementations.openai_compatible import CompatibleChatOpenAI

    label = cfg.preset.label if cfg.preset else "OpenAI-compatible"
    base_url = _require_base_url(label, "openai_compatible", cfg)
    _require_model(label, "openai_compatible", model)
    return LangChainLLM(
        CompatibleChatOpenAI(
            model=model,
            api_key=cfg.api_key or KEYLESS_API_KEY,  # type: ignore[arg-type]
            base_url=base_url,
            default_headers=cfg.headers or None,
            stream_usage=True,
        ),
        default_reasoning_effort=cfg.reasoning_effort,
        compat=True,
    )


def _build_mock(cfg: ResolvedBackendConfig, model: str) -> "LLMProvider":
    from dataclaw.providers.llm.implementations.mock_llm import MockLLM

    logger.info("Using mock LLM backend")
    return MockLLM()


# ── Model listing ───────────────────────────────────────────────────────────


async def _list_anthropic(cfg: ResolvedBackendConfig) -> list[ModelInfo]:
    return await fetch_anthropic_models(cfg.api_key)


async def _list_openai(cfg: ResolvedBackendConfig) -> list[ModelInfo]:
    transport = "openai_chat" if openai_api_mode(cfg) == "chat_completions" else "openai_responses"
    return await fetch_openai_models(cfg.api_key, cfg.base_url or OPENAI_API_BASE, transport=transport)


async def _list_gemini(cfg: ResolvedBackendConfig) -> list[ModelInfo]:
    return await fetch_gemini_models(cfg.api_key)


async def _list_codex(cfg: ResolvedBackendConfig) -> list[ModelInfo]:
    auth_mode = str(cfg.get("auth_mode", "default"))
    if auth_mode == "api_key":
        if not cfg.api_key:
            raise ModelCatalogUnauthenticated("Enter your OpenAI API key to load available models.")
        return await fetch_openai_models(cfg.api_key, OPENAI_API_BASE, transport="codex")
    if auth_mode != "default":
        raise ModelCatalogError(400, f"Unknown Codex auth mode: {auth_mode!r}")

    # Validate the OAuth state before starting app-server. model/list can
    # return cached metadata even when no account is signed in, which would
    # make the UI incorrectly report that authentication succeeded.
    from dataclaw.auth.codex_bridge import resolve_codex_credentials

    try:
        resolve_codex_credentials(auth_mode="default")
    except ValueError as exc:
        raise ModelCatalogUnauthenticated("Log in to Codex to load available models.") from exc
    return await fetch_codex_oauth_models()


def _endpoint_lister(transport: str):
    async def _list(cfg: ResolvedBackendConfig) -> list[ModelInfo]:
        if not cfg.base_url:
            raise ModelCatalogUnauthenticated("Enter the endpoint's base URL to load available models.")
        provider = cfg.preset.label if cfg.preset else "The endpoint"
        return await fetch_openai_models(
            cfg.api_key,
            cfg.base_url,
            provider=provider,
            headers=cfg.headers,
            transport=transport,
        )

    return _list


# ── Presets ─────────────────────────────────────────────────────────────────

OPENAI_COMPATIBLE_PRESETS: dict[str, PresetSpec] = {
    p.id: p
    for p in (
        PresetSpec(
            id="ollama",
            label="Ollama",
            base_url="http://localhost:11434/v1",
            requires_api_key=False,
            notes="Local Ollama server; pull a model with `ollama pull` first.",
        ),
        PresetSpec(
            id="vllm",
            label="vLLM",
            base_url="http://localhost:8001/v1",
            requires_api_key=False,
            notes=(
                "vLLM listens on port 8000 by default, which DataClaw's API also "
                "uses. Start it with --port 8001 (or adjust the URL)."
            ),
        ),
        PresetSpec(
            id="lmstudio",
            label="LM Studio",
            base_url="http://localhost:1234/v1",
            requires_api_key=False,
            notes="Start the LM Studio local server first.",
        ),
        PresetSpec(
            id="openrouter",
            label="OpenRouter",
            base_url="https://openrouter.ai/api/v1",
            api_key_env="OPENROUTER_API_KEY",
            headers={
                "HTTP-Referer": "https://github.com/gopivikranth28/DATACLAW-AGENT",
                "X-Title": "DataClaw",
            },
            notes="Model ids look like 'vendor/model'.",
        ),
        PresetSpec(
            id="groq",
            label="Groq",
            base_url="https://api.groq.com/openai/v1",
            api_key_env="GROQ_API_KEY",
        ),
        PresetSpec(
            id="xai",
            label="xAI",
            base_url="https://api.x.ai/v1",
            default_model="grok-4.7",
            api_key_env="XAI_API_KEY",
        ),
        PresetSpec(
            id="deepseek",
            label="DeepSeek",
            base_url="https://api.deepseek.com",
            default_model="deepseek-v4-pro",
            api_key_env="DEEPSEEK_API_KEY",
        ),
        PresetSpec(
            id="mistral",
            label="Mistral",
            base_url="https://api.mistral.ai/v1",
            api_key_env="MISTRAL_API_KEY",
        ),
        PresetSpec(
            id="together",
            label="Together AI",
            base_url="https://api.together.xyz/v1",
            api_key_env="TOGETHER_API_KEY",
        ),
    )
}


# ── Specs ───────────────────────────────────────────────────────────────────


def builtin_backends() -> list[LLMBackendSpec]:
    return [
        LLMBackendSpec(
            id="codex",
            label="OpenAI Codex",
            vendor="OpenAI",
            transport="codex",
            build=_build_codex,
            list_models=_list_codex,
            requires_api_key=False,
            default_model="gpt-5.5",
            config_fields=[
                ConfigField(
                    name="auth_mode",
                    field_type="select",
                    label="Sign-in method",
                    default="default",
                    env="CODEX_AUTH_MODE",
                    options=[
                        {"value": "default", "label": "OpenAI account (OAuth)"},
                        {"value": "api_key", "label": "OpenAI API key"},
                    ],
                ),
                _api_key_field("OPENAI_API_KEY", required=False),
                _model_field("CODEX_MODEL"),
                ConfigField(name="codex_bin", field_type="string", label="Codex binary", env="CODEX_BIN"),
                _REASONING_FIELD,
            ],
        ),
        LLMBackendSpec(
            id="openai",
            label="OpenAI API",
            vendor="OpenAI",
            transport="openai_responses",
            build=_build_openai,
            list_models=_list_openai,
            default_model="gpt-6.1-sol",
            utility_default_model="gpt-6-luna",
            config_fields=[
                _api_key_field("OPENAI_API_KEY"),
                _base_url_field(
                    "OPENAI_BASE_URL",
                    description="Optional. Leave empty for api.openai.com.",
                ),
                ConfigField(
                    name="api",
                    field_type="select",
                    label="API",
                    description=(
                        "Responses is the default for api.openai.com. Chat Completions is "
                        "used automatically for a custom endpoint unless set here."
                    ),
                    options=[
                        {"value": "responses", "label": "Responses"},
                        {"value": "chat_completions", "label": "Chat Completions"},
                    ],
                ),
                _model_field("OPENAI_MODEL"),
                _REASONING_FIELD,
            ],
        ),
        LLMBackendSpec(
            id="anthropic",
            label="Anthropic Claude",
            vendor="Anthropic",
            transport="anthropic",
            build=_build_anthropic,
            list_models=_list_anthropic,
            default_model="claude-opus-5-5",
            utility_default_model="claude-haiku-5-5",
            config_fields=[
                _api_key_field("ANTHROPIC_API_KEY"),
                _model_field("ANTHROPIC_MODEL"),
                _REASONING_FIELD,
            ],
        ),
        LLMBackendSpec(
            id="gemini",
            label="Google Gemini",
            vendor="Gemini",
            transport="gemini",
            build=_build_gemini,
            list_models=_list_gemini,
            default_model="gemini-4-argon",
            utility_default_model="gemini-3.8-flash",
            config_fields=[
                _api_key_field("GOOGLE_API_KEY"),
                _model_field("GEMINI_MODEL"),
                _REASONING_FIELD,
            ],
        ),
        LLMBackendSpec(
            id="openai_compatible",
            label="OpenAI-compatible endpoint",
            vendor="Endpoint",
            description="Chat Completions at a custom URL: local servers (Ollama, vLLM, LM Studio) and hosted gateways.",
            transport="openai_chat",
            build=_build_openai_compatible,
            list_models=_endpoint_lister("openai_chat"),
            requires_api_key=False,
            presets=OPENAI_COMPATIBLE_PRESETS,
            config_fields=[
                ConfigField(
                    name="preset",
                    field_type="select",
                    label="Preset",
                    description="Fills in the endpoint and headers. Choose Custom to enter your own.",
                    options=[{"value": "", "label": "Custom"}]
                    + [{"value": p.id, "label": p.label} for p in OPENAI_COMPATIBLE_PRESETS.values()],
                ),
                _base_url_field(required=True, description="Base URL ending in /v1, e.g. http://localhost:11434/v1."),
                _api_key_field(None, required=False, description="Leave empty for keyless local servers."),
                _model_field(),
                _HEADERS_FIELD,
                _REASONING_FIELD,
            ],
        ),
        LLMBackendSpec(
            id="open_responses",
            label="Open Responses endpoint",
            vendor="Endpoint",
            description="An Open Responses (openresponses.org) server: the Responses API at a custom URL.",
            transport="openai_responses",
            build=_build_open_responses,
            list_models=_endpoint_lister("openai_responses"),
            requires_api_key=False,
            config_fields=[
                _base_url_field(required=True, description="Base URL that serves POST /responses, e.g. http://localhost:8001/v1."),
                _api_key_field(None, required=False, description="Leave empty if the server needs no key."),
                _model_field(),
                _HEADERS_FIELD,
                _REASONING_FIELD,
            ],
        ),
        LLMBackendSpec(
            id="mock",
            label="Mock (testing)",
            transport="mock",
            build=_build_mock,
            requires_api_key=False,
            default_model="mock",
            hidden=True,
        ),
    ]
