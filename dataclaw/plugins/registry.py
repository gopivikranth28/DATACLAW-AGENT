"""ProviderRegistry — dependency injection container for providers.

Holds the active provider instance for each slot. Plugins can swap
providers via replace().
"""

from __future__ import annotations

from typing import Any

from dataclaw.hooks.sub_agent_hooks import SubAgentHookRegistry
from dataclaw.providers.compaction.provider import CompactionProvider
from dataclaw.providers.sub_agent.registry import SubAgentRegistry


class ProviderRegistry:
    """DI container holding the active provider for each slot."""

    def __init__(self) -> None:
        self.compaction: CompactionProvider | None = None
        self.system_prompt: Any = None
        self.memory: Any = None
        self.skill: Any = None
        self.tool_availability: Any = None
        self.llm: Any = None
        self.agent: Any = None
        self.sub_agent_registry: SubAgentRegistry = SubAgentRegistry()
        self.sub_agent_hooks: SubAgentHookRegistry = SubAgentHookRegistry()

    def replace(self, slot: str, provider: Any) -> None:
        """Replace the provider in the given slot."""
        if not hasattr(self, slot):
            valid = [k for k in vars(self) if not k.startswith("_")]
            raise ValueError(
                f"Unknown provider slot: {slot!r}. Valid slots: {valid}"
            )
        setattr(self, slot, provider)

    def validate(self) -> list[str]:
        """Check that all required slots are populated. Returns error messages."""
        errors = []
        for slot in ["compaction", "system_prompt", "memory", "skill",
                      "tool_availability", "llm", "agent"]:
            if getattr(self, slot) is None:
                errors.append(f"Provider slot {slot!r} is not populated")
        return errors
