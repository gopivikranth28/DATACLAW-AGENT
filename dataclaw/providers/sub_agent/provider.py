"""SubAgentProvider protocol.

Sub-agents are delegated a task, receive a subset of tools and skills,
and run for a limited number of turns. They expose their config needs
to the UI via config_schema().
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from dataclaw.providers.agent.provider import ConfigField


@runtime_checkable
class SubAgentProvider(Protocol):
    """Executes a delegated task with limited turns."""

    @classmethod
    def config_schema(cls) -> list[ConfigField]:
        """Return config fields this sub-agent needs. Broadcast to UI."""
        ...

    async def run(
        self,
        task: str,
        *,
        tools: list[dict[str, Any]],
        skills: list[dict[str, Any]],
        max_turns: int = 10,
    ) -> dict[str, Any]:
        """Execute the delegated task.

        Returns a dict with at minimum:
            status: "completed" | "max_turns_reached" | "error"
            result: str  (final text output)
            turns_used: int
        """
        ...
