"""Default tool availability provider — registry-based resolver."""

from __future__ import annotations

from typing import Any, Callable, Awaitable

from dataclaw.state import AgentState
from dataclaw.providers.tool.provider import ToolProvider
from dataclaw.schema import ToolDefinition


class DefaultToolAvailability:
    """Resolves tools from a registry of ToolProvider instances."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolProvider] = {}

    def register_tool(self, tool: ToolProvider) -> None:
        """Register a tool provider."""
        self._tools[tool.name] = tool

    def unregister_tool(self, name: str) -> None:
        """Remove a tool by name."""
        self._tools.pop(name, None)

    async def resolve_tools(
        self,
        state: AgentState,
    ) -> tuple[list[ToolDefinition], dict[str, Callable[..., Awaitable[dict[str, Any]]]]]:
        definitions = [t.definition for t in self._tools.values()]
        callables = {name: t.execute for name, t in self._tools.items()}
        return definitions, callables
