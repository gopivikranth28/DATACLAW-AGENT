"""LLM factory — instantiates an LLMProvider from config."""

from __future__ import annotations

from dataclaw.config.resolver import resolve_utility_backend
from dataclaw.providers.llm.registry import build_llm


def llm_from_config(
    backend: str | None = None,
    model: str | None = None,
):
    """Create an LLMProvider from the current configuration.

    Args:
        backend: Override the configured backend (any registered LLM backend
            id, e.g. anthropic|openai|gemini|codex|openai_compatible|mock).
        model: Override the configured model ID.

    Backends are resolved through ``dataclaw.providers.llm.registry``. A
    missing API key raises ``LLMConfigurationError`` naming the env var and
    config path, unless the backend (or its preset) is keyless.
    """
    return build_llm(backend or resolve_utility_backend(), model)
