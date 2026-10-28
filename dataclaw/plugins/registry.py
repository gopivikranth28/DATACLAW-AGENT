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
        self._runtime_factories: dict[str, Any] = {}
        self.runtime_manager: Any = None

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

    def register_runtime_factory(self, runtime: str, factory: Any) -> None:
        """Register an external runtime constructor without selecting it."""
        name = runtime.strip().lower()
        if not name:
            raise ValueError("runtime name is required")
        if name in self._runtime_factories:
            raise ValueError(f"Runtime factory already registered: {name}")
        self._runtime_factories[name] = factory

    def register_llm_backend(self, spec: Any) -> None:
        """Register an ``LLMBackendSpec`` with the LLM backend registry.

        LLM backends are process-wide (``llm_from_config`` and the config
        resolver have no ProviderRegistry), so this forwards to
        ``dataclaw.providers.llm.registry``. Built-in ids cannot be replaced.
        """
        from dataclaw.providers.llm.registry import register_llm_backend

        register_llm_backend(spec)

    def register_decision_backend(self, spec: Any) -> None:
        """Register a ``DecisionBackendSpec`` (process-wide, like LLM backends)."""
        from dataclaw.providers.decision.registry import register_decision_backend

        register_decision_backend(spec)

    def get_runtime_factory(self, runtime: str) -> Any | None:
        return self._runtime_factories.get(runtime.strip().lower())

    def list_runtime_factories(self) -> tuple[str, ...]:
        return tuple(sorted(self._runtime_factories))

    def publish_bundle(self, bundle: Any) -> None:
        """Publish a bundle through legacy provider slots atomically enough for
        synchronous readers.

        New run code captures ``RuntimeManager.active_bundle``. These aliases
        remain for existing routes and plugins that inspect the registry.
        """
        self.agent = bundle.agent
        self.llm = bundle.utility_llm
        self.compaction = bundle.compaction
        self.tool_availability = bundle.tool_availability
        self.sub_agent_registry = bundle.sub_agent_registry
        self.sub_agent_hooks = bundle.sub_agent_hooks
        self.memory = bundle.memory
        self.system_prompt = bundle.system_prompt
        self.skill = bundle.skill
