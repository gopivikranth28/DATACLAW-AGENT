"""FastAPI dependency injection helpers."""

from __future__ import annotations

import logging

from fastapi import Request

from dataclaw.config.resolver import resolve
from dataclaw.hooks.registry import HookRegistry
from dataclaw.plugins.registry import ProviderRegistry

from dataclaw.providers.compaction.implementations.llm_summarizer import LLMSummarizingCompactor
from dataclaw.providers.system_prompt.implementations.template import TemplateSystemPromptProvider
from dataclaw.providers.memory.implementations.noop import NoopMemoryProvider
from dataclaw.providers.skill.implementations.file_skill import FileSkillProvider
from dataclaw.providers.tool.implementations.registry import DefaultToolAvailability
from dataclaw.providers.llm.implementations.factory import llm_from_config
from dataclaw.providers.agent.implementations.langchain_agent import LangChainAgentProvider
from dataclaw.providers.sub_agent.implementations.default import DefaultSubAgentProvider

logger = logging.getLogger(__name__)


def init_providers(registry: ProviderRegistry) -> DefaultToolAvailability:
    """Initialize the provider registry with default implementations.

    Returns the tool_registry so it can be passed into PluginContext.
    """
    llm = llm_from_config()

    registry.llm = llm
    registry.compaction = LLMSummarizingCompactor(llm)
    registry.system_prompt = TemplateSystemPromptProvider()
    registry.memory = NoopMemoryProvider()
    registry.skill = FileSkillProvider()

    tool_registry = DefaultToolAvailability()
    registry.tool_availability = tool_registry

    # Set up agent provider based on configured backend
    backend = resolve("llm.backend", "DATACLAW_LLM_BACKEND", "openclaw")
    if backend == "openclaw":
        try:
            from dataclaw_openclaw.agent_provider import OpenClawAgentProvider
            url = resolve("plugins.openclaw.url", "DATACLAW_OPENCLAW_URL", "http://127.0.0.1:18789")
            token = resolve("plugins.openclaw.frontend_token", "DATACLAW_FRONTEND_TOKEN",
                    resolve("plugins.openclaw.token", "DATACLAW_OPENCLAW_TOKEN", ""))
            wait_ms = int(resolve("plugins.openclaw.wait_ms", "DATACLAW_OPENCLAW_WAIT_MS", "0"))
            registry.agent = OpenClawAgentProvider(url=url, token=token, wait_ms=wait_ms)
            logger.info("Agent provider: OpenClaw (%s)", url)
        except ImportError:
            logger.warning("dataclaw-openclaw plugin not installed, falling back to LangChain agent")
            registry.agent = LangChainAgentProvider(llm)
    else:
        registry.agent = LangChainAgentProvider(llm)

    registry.sub_agent = DefaultSubAgentProvider(llm)

    return tool_registry


def get_providers(request: Request) -> ProviderRegistry:
    """Get the provider registry from app state."""
    return request.app.state.providers


def get_hooks(request: Request) -> HookRegistry:
    """Get the hook registry from app state."""
    return request.app.state.hooks
