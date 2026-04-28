"""Project and subagent tools for the agent."""

from __future__ import annotations

from typing import Any

from dataclaw_projects.subagents import list_subagent_definitions


async def list_subagents_tool(**kw: Any) -> dict[str, Any]:
    """List available subagent definitions."""
    return {"subagents": list_subagent_definitions()}


async def delegate_to_subagent(
    *,
    subagent_name: str,
    task: str,
    **kw: Any,
) -> dict[str, Any]:
    """Delegate a task to a subagent. (Stub — full runner to be implemented.)"""
    # TODO: wire to SubAgentProvider for actual execution
    return {
        "status": "not_implemented",
        "subagent": subagent_name,
        "task": task,
        "message": "Subagent delegation is not yet fully wired. Define subagents via /subagents API.",
    }
