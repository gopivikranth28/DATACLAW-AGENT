"""LangGraph StateGraph definition for the agent pipeline.

Builds the complete agent loop as a directed graph:

  START → userQueryHook → compaction → postCompactionHook →
  systemPrompt → postSystemPromptHook → memory → postMemoryHook →
  skill → postSkillHook → toolAvailability → postToolAvailabilityHook →
  callAgent → [conditional] →
    tool_call: preToolCallHook → executeTools → postToolCallHook → compaction (loop)
    message:   postAgentMessageHook → END
    max_turns: END
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import StateGraph, START, END

from dataclaw.hooks.registry import HookRegistry
from dataclaw.loop.nodes import (
    make_agent_node,
    make_compaction_node,
    make_hook_node,
    make_memory_node,
    make_skill_node,
    make_system_prompt_node,
    make_tool_availability_node,
    make_tool_execution_node,
)
from dataclaw.plugins.registry import ProviderRegistry
from dataclaw.state import AgentState


def route_after_agent(state: AgentState) -> str:
    """Decide what happens after the agent node."""
    if state.get("pending_tool_calls"):
        return "tool_call"
    if state.get("turn", 0) >= state.get("max_turns", 30):
        return "max_turns"
    return "message"


def build_agent_graph(
    providers: ProviderRegistry,
    hooks: HookRegistry,
    *,
    max_messages: int = 30,
    keep_recent: int = 8,
) -> Any:
    """Build and compile the agent pipeline graph."""
    graph = StateGraph(AgentState)

    # ── Pipeline nodes ──────────────────────────────────────────────────
    graph.add_node("user_query_hook", make_hook_node(hooks, "userQueryHook"))
    graph.add_node("compaction", make_compaction_node(
        providers.compaction, max_messages=max_messages, keep_recent=keep_recent
    ))
    graph.add_node("post_compaction_hook", make_hook_node(hooks, "postCompactionHook"))
    graph.add_node("system_prompt", make_system_prompt_node(providers.system_prompt))
    graph.add_node("post_system_prompt_hook", make_hook_node(hooks, "postSystemPromptHook"))
    graph.add_node("memory", make_memory_node(providers.memory))
    graph.add_node("post_memory_hook", make_hook_node(hooks, "postMemoryHook"))
    graph.add_node("skill", make_skill_node(providers.skill))
    graph.add_node("post_skill_hook", make_hook_node(hooks, "postSkillHook"))
    graph.add_node("tool_availability", make_tool_availability_node(providers.tool_availability))
    graph.add_node("post_tool_availability_hook", make_hook_node(hooks, "postToolAvailabilityHook"))
    graph.add_node("call_agent", make_agent_node(providers.agent))
    graph.add_node("pre_tool_call_hook", make_hook_node(hooks, "preToolCallHook"))
    graph.add_node("execute_tools", make_tool_execution_node())
    graph.add_node("post_tool_call_hook", make_hook_node(hooks, "postToolCallHook"))
    graph.add_node("post_agent_message_hook", make_hook_node(hooks, "postAgentMessageHook"))

    # ── Linear pipeline edges ───────────────────────────────────────────
    graph.add_edge(START, "user_query_hook")
    graph.add_edge("user_query_hook", "compaction")
    graph.add_edge("compaction", "post_compaction_hook")
    graph.add_edge("post_compaction_hook", "system_prompt")
    graph.add_edge("system_prompt", "post_system_prompt_hook")
    graph.add_edge("post_system_prompt_hook", "memory")
    graph.add_edge("memory", "post_memory_hook")
    graph.add_edge("post_memory_hook", "skill")
    graph.add_edge("skill", "post_skill_hook")
    graph.add_edge("post_skill_hook", "tool_availability")
    graph.add_edge("tool_availability", "post_tool_availability_hook")
    graph.add_edge("post_tool_availability_hook", "call_agent")

    # ── Conditional routing after agent call ─────────────────────────────
    graph.add_conditional_edges(
        "call_agent",
        route_after_agent,
        {
            "tool_call": "pre_tool_call_hook",
            "message": "post_agent_message_hook",
            "max_turns": END,
        },
    )

    # ── Tool execution loop ─────────────────────────────────────────────
    graph.add_edge("pre_tool_call_hook", "execute_tools")
    graph.add_edge("execute_tools", "post_tool_call_hook")
    graph.add_edge("post_tool_call_hook", "compaction")  # loop back

    # ── Final message → done ────────────────────────────────────────────
    graph.add_edge("post_agent_message_hook", END)

    return graph.compile()
