"""No-op memory provider — placeholder for future implementations."""

from __future__ import annotations

from typing import Any

from dataclaw.state import AgentState


class NoopMemoryProvider:
    """Returns empty results for all memory operations."""

    @classmethod
    def config_schema(cls) -> list:
        return []

    async def retrieve_memories(self, state: AgentState) -> list[str]:
        return []

    async def search_memory(
        self,
        query: str,
        *,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        return []

    def as_tool_definition(self) -> dict[str, Any] | None:
        return None

    async def save_memory(
        self,
        content: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {}

    def as_save_tool_definition(self) -> dict[str, Any] | None:
        return None
