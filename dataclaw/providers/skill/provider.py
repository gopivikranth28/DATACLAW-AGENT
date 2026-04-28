"""SkillProvider protocol.

Resolves skills for the current conversation, formats them for
prompt injection, and fetches individual skills as tools.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from dataclaw.state import AgentState


@runtime_checkable
class SkillProvider(Protocol):
    """Resolves, formats, and fetches skills."""

    async def resolve_skills(self, state: AgentState) -> list[dict[str, Any]]:
        """Return skill metadata dicts relevant to the current conversation."""
        ...

    async def format_for_prompt(self, skills: list[dict[str, Any]]) -> list[str]:
        """Format skill bodies for system prompt injection."""
        ...

    async def fetch_skill(self, skill_id: str) -> dict[str, Any] | None:
        """Fetch a specific skill by ID. Usable as a tool callable."""
        ...
