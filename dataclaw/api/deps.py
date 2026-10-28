"""FastAPI dependency injection helpers."""

from __future__ import annotations

import logging

from fastapi import Request

from dataclaw.hooks.registry import HookRegistry
from dataclaw.plugins.registry import ProviderRegistry

from dataclaw.providers.compaction.implementations.factory import compaction_from_config
from dataclaw.providers.system_prompt.implementations.template import TemplateSystemPromptProvider
from dataclaw.providers.memory.implementations.factory import memory_from_config
from dataclaw.providers.skill.implementations.file_skill import FileSkillProvider
from dataclaw.providers.tool.implementations.registry import DefaultToolAvailability
from dataclaw.providers.tool.provider import ToolProvider
from dataclaw.providers.llm.implementations.factory import llm_from_config
from dataclaw.providers.agent.implementations.langchain_agent import LangChainAgentProvider
from dataclaw.providers.sub_agent.implementations.default import DefaultSubAgentProvider
from dataclaw.providers.decision.routing import bind_providers as bind_decision_providers
from dataclaw.providers.decision.tool import register_decide_tool

logger = logging.getLogger(__name__)


def init_providers(registry: ProviderRegistry) -> DefaultToolAvailability:
    """Initialize the provider registry with default implementations.

    Returns the tool_registry so it can be passed into PluginContext.
    """
    # The initial provider set is provisional. External runtimes register
    # factories during plugin registration and the post-registration selection
    # pass in app.py chooses the configured runtime.
    # Plugin registration needs a harmless provisional provider set. The
    # post-registration runtime selection publishes the configured utility
    # model and agent runtime as one immutable bundle.
    llm = llm_from_config(backend="mock")

    registry.llm = llm
    registry.compaction = compaction_from_config(llm)
    registry.system_prompt = TemplateSystemPromptProvider()
    memory = memory_from_config()
    registry.memory = memory
    registry.skill = FileSkillProvider()

    tool_registry = DefaultToolAvailability()
    registry.tool_availability = tool_registry

    # Register memory tools if the provider exposes them
    search_def = memory.as_tool_definition()
    if search_def is not None:
        tool_registry.register_tool(ToolProvider(
            name=search_def["name"],
            description=search_def["description"],
            parameters=search_def["parameters"],
            fn=memory.search_memory,
        ))
    save_def = memory.as_save_tool_definition()
    if save_def is not None:
        tool_registry.register_tool(ToolProvider(
            name=save_def["name"],
            description=save_def["description"],
            parameters=save_def["parameters"],
            fn=memory.save_memory,
        ))

    # Register skill tools
    skill_provider = registry.skill
    tool_registry.register_tool(ToolProvider(
        name="fetch_skill",
        description="Fetch the full content and instructions of a skill by its ID. Use this when you want to follow a skill's detailed steps.",
        parameters={
            "type": "object",
            "properties": {
                "skill_id": {"type": "string", "description": "The skill ID to fetch"},
            },
            "required": ["skill_id"],
        },
        fn=skill_provider.fetch_skill,
    ))
    tool_registry.register_tool(ToolProvider(
        name="list_skills",
        description="List all available skills with their IDs, names, and descriptions.",
        parameters={"type": "object", "properties": {}},
        fn=skill_provider.list_available_skills,
    ))

    # Decision tool: always registered (so generated tool manifests are
    # stable) but only offered while decision.backend is not "none".
    register_decide_tool(tool_registry)
    bind_decision_providers(registry)

    registry.agent = LangChainAgentProvider(llm)

    registry.sub_agent_registry.register(DefaultSubAgentProvider(llm))

    return tool_registry


def get_providers(request: Request) -> ProviderRegistry:
    """Get the provider registry from app state."""
    return request.app.state.providers


def get_hooks(request: Request) -> HookRegistry:
    """Get the hook registry from app state."""
    return request.app.state.hooks
