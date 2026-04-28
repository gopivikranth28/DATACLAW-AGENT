"""Node functions for the LangGraph agent pipeline.

Each node is an async function that takes AgentState and returns
a partial state update dict. Providers are injected via closures.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Awaitable

from dataclaw.hooks.registry import HookRegistry
from dataclaw.providers.llm.provider import PendingToolCall, TextDeltaEvent, ToolUseStartEvent, TurnCompleteEvent
from dataclaw.schema import Message
from dataclaw.state import AgentState

logger = logging.getLogger(__name__)


def make_hook_node(
    hooks: HookRegistry,
    point: str,
) -> Callable[[AgentState], Awaitable[dict[str, Any]]]:
    """Create a node that runs all hooks at the given point."""

    async def hook_node(state: AgentState) -> dict[str, Any]:
        updated = await hooks.run(point, state)
        # Return only changed keys
        changes: dict[str, Any] = {}
        for key in updated:
            if key in state and updated[key] != state[key]:
                changes[key] = updated[key]
            elif key not in state:
                changes[key] = updated[key]
        return changes if changes else {}

    hook_node.__name__ = f"hook_{point}"
    return hook_node


def make_compaction_node(
    compaction_provider: Any,
    max_messages: int = 30,
    keep_recent: int = 8,
) -> Callable[[AgentState], Awaitable[dict[str, Any]]]:
    """Create the compaction node."""

    async def compaction_node(state: AgentState) -> dict[str, Any]:
        messages = list(state.get("messages", []))
        compacted = await compaction_provider.compact(
            messages, max_messages=max_messages, keep_recent=keep_recent
        )
        if len(compacted) != len(messages):
            return {"messages": compacted}
        return {}

    return compaction_node


def make_system_prompt_node(
    system_prompt_provider: Any,
) -> Callable[[AgentState], Awaitable[dict[str, Any]]]:
    """Create the system prompt node."""

    async def system_prompt_node(state: AgentState) -> dict[str, Any]:
        prompt = await system_prompt_provider.build_system_prompt(state)
        return {"system_prompt": prompt}

    return system_prompt_node


def make_memory_node(
    memory_provider: Any,
) -> Callable[[AgentState], Awaitable[dict[str, Any]]]:
    """Create the memory node."""

    async def memory_node(state: AgentState) -> dict[str, Any]:
        memories = await memory_provider.retrieve_memories(state)
        return {"memories": memories}

    return memory_node


def make_skill_node(
    skill_provider: Any,
) -> Callable[[AgentState], Awaitable[dict[str, Any]]]:
    """Create the skill resolution node."""

    async def skill_node(state: AgentState) -> dict[str, Any]:
        skills = await skill_provider.resolve_skills(state)
        fragments = await skill_provider.format_for_prompt(skills)
        return {"skills": skills, "skill_prompt_fragments": fragments}

    return skill_node


def make_tool_availability_node(
    tool_availability_provider: Any,
) -> Callable[[AgentState], Awaitable[dict[str, Any]]]:
    """Create the tool availability resolution node."""

    async def tool_availability_node(state: AgentState) -> dict[str, Any]:
        tool_defs, callables = await tool_availability_provider.resolve_tools(state)
        return {"tools": tool_defs, "tool_callables": callables}

    return tool_availability_node


def make_agent_node(
    agent_provider: Any,
) -> Callable[[AgentState], Awaitable[dict[str, Any]]]:
    """Create the agent call node.

    Collects all streaming events and returns the accumulated state:
    - pending_tool_calls if the agent made tool calls
    - updated turn counter
    - agent text is accumulated for message building
    """

    async def agent_node(state: AgentState) -> dict[str, Any]:
        pending: list[dict[str, Any]] = []
        text_chunks: list[str] = []

        async for event in agent_provider.stream_turn(state):
            if isinstance(event, TextDeltaEvent):
                text_chunks.append(event.text)
            elif isinstance(event, PendingToolCall):
                pending.append({
                    "call_id": event.call_id,
                    "tool_name": event.tool_name,
                    "tool_input": event.tool_input,
                })

        turn = state.get("turn", 0) + 1
        result: dict[str, Any] = {
            "turn": turn,
            "pending_tool_calls": pending,
        }

        # If the agent produced text (final message), store it in metadata
        if text_chunks and not pending:
            result["metadata"] = {
                **state.get("metadata", {}),
                "agent_text": "".join(text_chunks),
            }

        return result

    return agent_node


def make_tool_execution_node() -> Callable[[AgentState], Awaitable[dict[str, Any]]]:
    """Create the tool execution node.

    Executes all pending tool calls and appends the results
    as canonical messages to the conversation.
    """

    async def tool_execution_node(state: AgentState) -> dict[str, Any]:
        pending = state.get("pending_tool_calls", [])
        callables = state.get("tool_callables", {})

        if not pending:
            return {}

        # Build assistant message with tool calls
        assistant_content: list[dict[str, Any]] = []
        agent_text = state.get("metadata", {}).get("agent_text", "")
        if agent_text:
            assistant_content.append({"type": "text", "text": agent_text})
        for tc in pending:
            assistant_content.append({
                "type": "tool_call",
                "id": tc["call_id"],
                "name": tc["tool_name"],
                "input": tc["tool_input"],
            })

        # Execute tools
        tool_results: list[dict[str, Any]] = []
        for tc in pending:
            fn = callables.get(tc["tool_name"])
            if fn is None:
                tool_results.append({
                    "type": "tool_result",
                    "call_id": tc["call_id"],
                    "content": f'{{"error": "Unknown tool: {tc["tool_name"]}"}}',
                    "is_error": True,
                })
                continue
            try:
                import json
                result = await fn(**tc["tool_input"])
                tool_results.append({
                    "type": "tool_result",
                    "call_id": tc["call_id"],
                    "content": json.dumps(result, default=str),
                    "is_error": False,
                })
            except Exception as e:
                import json
                logger.exception("Tool %s failed", tc["tool_name"])
                tool_results.append({
                    "type": "tool_result",
                    "call_id": tc["call_id"],
                    "content": json.dumps({"error": str(e)}),
                    "is_error": True,
                })

        new_messages = [
            Message(role="assistant", content=assistant_content),
            Message(role="user", content=tool_results),
        ]

        return {
            "messages": new_messages,
            "tool_results": tool_results,
            "pending_tool_calls": [],
        }

    return tool_execution_node
