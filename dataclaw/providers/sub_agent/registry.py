"""SubAgentRegistry — keyed dispatch of sub-agent providers by agent_type."""

from __future__ import annotations

from typing import Any

from dataclaw.providers.sub_agent.provider import SubAgentProvider


class SubAgentRegistry:
    """Maps agent_type strings to SubAgentProvider implementations.

    Plugins register their own providers; the delegation tool looks up
    the correct provider by reading the subagent definition's agent_type.
    """

    def __init__(self) -> None:
        self._providers: dict[str, SubAgentProvider] = {}

    def register(self, provider: SubAgentProvider) -> None:
        """Register a provider for its agent_type. Overwrites any existing provider."""
        self._providers[provider.agent_type] = provider

    def get(self, agent_type: str) -> SubAgentProvider | None:
        """Look up the provider for the given agent_type."""
        return self._providers.get(agent_type)

    def list_types(self) -> list[dict[str, Any]]:
        """Return registered agent types with their config schemas (for UI)."""
        result = []
        for agent_type, provider in self._providers.items():
            config_schema = []
            if hasattr(provider, "config_schema"):
                try:
                    schema = provider.config_schema()
                    config_schema = [
                        f.to_dict() if hasattr(f, "to_dict") else f
                        for f in schema
                    ]
                except Exception:
                    pass
            result.append({
                "agent_type": agent_type,
                "provider": type(provider).__name__,
                "config_schema": config_schema,
            })
        return result
