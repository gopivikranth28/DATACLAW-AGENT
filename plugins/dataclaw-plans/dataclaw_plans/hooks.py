"""Plan hooks — integrates with the pipeline hook system.

Injects session_id into all plan tool calls and auto-injects the
active plan_id into update_plan calls so the agent doesn't have to
track either.
"""

from __future__ import annotations

from dataclaw.state import AgentState
from dataclaw_plans.store import get_active_plan_id

PLAN_TOOLS = {"propose_plan", "update_plan", "list_plans", "get_plan"}


async def active_plan_context_hook(state: AgentState) -> AgentState:
    """preToolCallHook: inject session_id and active plan_id into plan tool calls."""
    pending = state.get("pending_tool_calls", [])
    session_id = state.get("session_id", "")

    if not pending or not session_id:
        return state

    active_id = get_active_plan_id(session_id)

    updated = []
    for tc in pending:
        tool_name = tc.get("tool_name", "")
        tool_input = tc.get("tool_input", {})

        if tool_name in PLAN_TOOLS:
            # Always inject session_id so plans are scoped to the chat session
            if not tool_input.get("session_id") or tool_input.get("session_id") == "default":
                tool_input = {**tool_input, "session_id": session_id}
                tc = {**tc, "tool_input": tool_input}

            # Auto-inject proposal_id into update_plan
            if tool_name == "update_plan" and active_id and not tool_input.get("proposal_id"):
                tc = {**tc, "tool_input": {**tc["tool_input"], "proposal_id": active_id}}

        updated.append(tc)

    return {**state, "pending_tool_calls": updated}
