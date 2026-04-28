"""Agent loop runner — entry point for executing the pipeline.

Builds the LangGraph graph, invokes it with the initial state,
and yields events for the API layer to stream.

This is the boundary where raw dicts from the API are converted
to Message objects.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator

from dataclaw.hooks.registry import HookRegistry
from dataclaw.loop.graph import build_agent_graph
from dataclaw.plugins.registry import ProviderRegistry
from dataclaw.schema import Message
from dataclaw.state import AgentState

logger = logging.getLogger(__name__)


def _to_messages(raw: list[dict[str, Any]]) -> list[Message]:
    """Convert raw dicts from the API into Message objects."""
    return [Message.from_dict(m) if isinstance(m, dict) else m for m in raw]


async def run_loop(
    *,
    session_id: str,
    user_query: str,
    messages: list[dict[str, Any]],
    providers: ProviderRegistry,
    hooks: HookRegistry,
    project_id: str | None = None,
    max_turns: int = 30,
    max_messages: int = 30,
    keep_recent: int = 8,
) -> dict[str, Any]:
    """Run the full agent pipeline and return the final state."""
    graph = build_agent_graph(
        providers, hooks,
        max_messages=max_messages, keep_recent=keep_recent,
    )

    initial_state: AgentState = {
        "session_id": session_id,
        "project_id": project_id,
        "user_query": user_query,
        "messages": _to_messages(messages),
        "system_prompt": "",
        "memories": [],
        "skills": [],
        "skill_prompt_fragments": [],
        "tools": [],
        "tool_callables": {},
        "pending_tool_calls": [],
        "tool_results": [],
        "turn": 0,
        "max_turns": max_turns,
        "metadata": {},
    }

    final_state = await graph.ainvoke(initial_state)
    return final_state


async def run_loop_streaming(
    *,
    session_id: str,
    user_query: str,
    messages: list[dict[str, Any]],
    providers: ProviderRegistry,
    hooks: HookRegistry,
    project_id: str | None = None,
    max_turns: int = 30,
    max_messages: int = 30,
    keep_recent: int = 8,
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """Run the agent pipeline with LangGraph streaming.

    Yields (node_name, state_update) tuples as each node completes.
    """
    graph = build_agent_graph(
        providers, hooks,
        max_messages=max_messages, keep_recent=keep_recent,
    )

    initial_state: AgentState = {
        "session_id": session_id,
        "project_id": project_id,
        "user_query": user_query,
        "messages": _to_messages(messages),
        "system_prompt": "",
        "memories": [],
        "skills": [],
        "skill_prompt_fragments": [],
        "tools": [],
        "tool_callables": {},
        "pending_tool_calls": [],
        "tool_results": [],
        "turn": 0,
        "max_turns": max_turns,
        "metadata": {},
    }

    async for event in graph.astream(initial_state):
        for node_name, state_update in event.items():
            yield node_name, state_update
