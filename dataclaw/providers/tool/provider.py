"""ToolProvider base class and ToolAvailabilityProvider protocol.

ToolProvider wraps a callable as a dataclaw tool with a JSON Schema
definition. ToolAvailabilityProvider resolves which tools are
available for a given pipeline state.
"""

from __future__ import annotations

import inspect
from typing import Any, Callable, Awaitable, Protocol, runtime_checkable

from dataclaw.state import AgentState
from dataclaw.schema import ToolDefinition

# Context params injected by OpenClaw that should be stripped before calling tool functions
_CONTEXT_PARAMS = frozenset({
    "titan_session_id", "dataclaw_session_id", "session_id",
    "openclaw_session_key", "openclaw_agent_id",
})


class ToolProvider:
    """Wraps a Python async function as a dataclaw tool."""

    def __init__(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        fn: Callable[..., Awaitable[dict[str, Any]]],
    ) -> None:
        self.name = name
        self.fn = fn
        self._definition: ToolDefinition = {
            "name": name,
            "description": description,
            "parameters": parameters,
        }
        # Check if function accepts **kwargs
        sig = inspect.signature(fn)
        self._accepts_var_keyword = any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
        )

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        """Execute the wrapped function, stripping injected context params if needed."""
        if not self._accepts_var_keyword:
            kwargs = {k: v for k, v in kwargs.items() if k not in _CONTEXT_PARAMS}
        return await self.fn(**kwargs)


@runtime_checkable
class ToolAvailabilityProvider(Protocol):
    """Resolves which tools are available for the current agent turn."""

    async def resolve_tools(
        self,
        state: AgentState,
    ) -> tuple[list[ToolDefinition], dict[str, Callable[..., Awaitable[dict[str, Any]]]]]:
        """Return (tool_definitions, name_to_callable_map) for this turn."""
        ...
