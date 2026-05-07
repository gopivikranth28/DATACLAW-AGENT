"""LLM factory — instantiates an LLMProvider from config."""

from __future__ import annotations

import logging

from dataclaw.config.resolver import resolve

logger = logging.getLogger(__name__)


def llm_from_config(
    backend: str | None = None,
    model: str | None = None,
):
    """Create an LLMProvider from the current configuration.

    Args:
        backend: Override the configured backend (mock|anthropic|openai|gemini|codex).
        model: Override the configured model ID.

    If backend is "mock" or no API key is configured for the selected
    backend, returns a MockLLM for development/testing.
    """
    backend = backend or resolve("llm.backend", "DATACLAW_LLM_BACKEND", "openclaw")

    if backend == "mock":
        from dataclaw.providers.llm.implementations.mock_llm import MockLLM
        logger.info("Using mock LLM backend")
        return MockLLM()

    if backend == "anthropic":
        api_key = resolve("llm.anthropic.api_key", "ANTHROPIC_API_KEY", "")
        if not api_key:
            logger.warning("No Anthropic API key configured, falling back to mock LLM")
            from dataclaw.providers.llm.implementations.mock_llm import MockLLM
            return MockLLM()

        from langchain_anthropic import ChatAnthropic
        from dataclaw.providers.llm.implementations.langchain_llm import LangChainLLM

        model_id = model or resolve("llm.anthropic.model", "ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
        return LangChainLLM(ChatAnthropic(model=model_id, api_key=api_key))  # type: ignore[arg-type]

    elif backend == "openai":
        api_key = resolve("llm.openai.api_key", "OPENAI_API_KEY", "")
        if not api_key:
            logger.warning("No OpenAI API key configured, falling back to mock LLM")
            from dataclaw.providers.llm.implementations.mock_llm import MockLLM
            return MockLLM()

        from langchain_openai import ChatOpenAI
        from dataclaw.providers.llm.implementations.langchain_llm import LangChainLLM

        model_id = model or resolve("llm.openai.model", "OPENAI_MODEL", "gpt-4o")
        base_url = resolve("llm.openai.base_url", "OPENAI_BASE_URL", "") or None
        return LangChainLLM(ChatOpenAI(model=model_id, api_key=api_key, base_url=base_url))  # type: ignore[arg-type]

    elif backend == "gemini":
        api_key = resolve("llm.gemini.api_key", "GOOGLE_API_KEY", "")
        if not api_key:
            logger.warning("No Gemini API key configured, falling back to mock LLM")
            from dataclaw.providers.llm.implementations.mock_llm import MockLLM
            return MockLLM()

        from langchain_google_genai import ChatGoogleGenerativeAI
        from dataclaw.providers.llm.implementations.langchain_llm import LangChainLLM

        model_id = model or resolve("llm.gemini.model", "GEMINI_MODEL", "gemini-2.5-flash")
        return LangChainLLM(ChatGoogleGenerativeAI(model=model_id, google_api_key=api_key))  # type: ignore[arg-type]

    elif backend == "codex":
        from dataclaw.auth.codex_bridge import resolve_codex_credentials
        from dataclaw.providers.llm.implementations.openai_responses import OpenAIResponsesLLM

        auth_mode = resolve("llm.codex.auth_mode", "CODEX_AUTH_MODE", "default")
        api_key = resolve("llm.codex.api_key", "OPENAI_API_KEY", "")
        model_id = model or resolve("llm.codex.model", "CODEX_MODEL", "gpt-5.5")

        creds = resolve_codex_credentials(auth_mode=auth_mode, api_key=api_key)
        logger.info("Using Codex LLM backend (model=%s, auth=%s, base_url=%s)", model_id, auth_mode, creds.base_url)
        return OpenAIResponsesLLM(
            api_key=creds.api_key,
            base_url=creds.base_url,
            model=model_id,
            default_headers=creds.headers,
        )

    elif backend == "openclaw":
        # OpenClaw handles its own LLM — provide a mock for compaction/sub-agents
        from dataclaw.providers.llm.implementations.mock_llm import MockLLM
        logger.info("LLM backend is 'openclaw' — using mock LLM for internal providers")
        return MockLLM()

    else:
        raise ValueError(f"Unknown LLM backend: {backend!r}")
