"""MemoryProvider protocol.

Provides memories for prompt injection and exposes a searchable
tool interface.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from dataclaw.state import AgentState


@runtime_checkable
class MemoryProvider(Protocol):
    """Retrieves and searches agent memory."""

    async def retrieve_memories(self, state: AgentState) -> list[str]:
        """Return formatted memory strings relevant to the current conversation."""
        ...

    async def search_memory(
        self,
        query: str,
        *,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Search the memory store. Can be registered as a tool."""
        ...

    def as_tool_definition(self) -> dict[str, Any] | None:
        """Return a ToolDefinition for search_memory, or None if not exposable."""
        ...
