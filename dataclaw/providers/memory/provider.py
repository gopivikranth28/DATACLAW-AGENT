"""MemoryProvider protocol.

Provides memories for prompt injection and exposes searchable
and writable tool interfaces.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from dataclaw.providers.config_field import ConfigField
from dataclaw.state import AgentState


@runtime_checkable
class MemoryProvider(Protocol):
    """Retrieves, searches, and persists agent memory."""

    # ── Config ─────────────────────────────────────────────────────────

    @classmethod
    def config_schema(cls) -> list[ConfigField]:
        """Return config fields this provider needs. Broadcast to UI."""
        ...

    # ── Read ───────────────────────────────────────────────────────────

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

    # ── Write ──────────────────────────────────────────────────────────

    async def save_memory(
        self,
        content: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Persist a memory entry. Returns {"id": ..., "status": "saved"}."""
        ...

    def as_save_tool_definition(self) -> dict[str, Any] | None:
        """Return a ToolDefinition for save_memory, or None if not exposable."""
        ...
