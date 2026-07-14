"""Hooks for structured EDA tools and notebook evidence capture."""

from __future__ import annotations

import json
from typing import Any

from dataclaw.state import AgentState
from dataclaw_eda.evidence import stash_notebook_anchor

EDA_TOOLS = {
    "propose_eda_hypotheses",
    "update_eda_hypothesis",
    "list_eda_hypotheses",
    "record_eda_finding",
    "supersede_eda_finding",
    "list_eda_findings",
    "read_eda_finding",
    "summarize_eda_readiness",
}
NOTEBOOK_EVIDENCE_TOOLS = {
    "execute_cell",
    "read_cell",
    # OpenClaw exposes the same notebook operations with this prefix while
    # the in-process tool registry uses the short names.
    "dataclaw_execute_cell",
    "dataclaw_read_cell",
}


async def eda_context_hook(state: AgentState) -> AgentState:
    """Inject session/proposal/plan-step context into EDA tool calls."""
    pending = state.get("pending_tool_calls", [])
    if not pending:
        return state
    session_id = state.get("session_id", "")
    proposal_id = ""
    if session_id:
        try:
            from dataclaw_plans.store import get_active_plan_id

            proposal_id = get_active_plan_id(session_id) or ""
        except Exception:
            proposal_id = ""
    plan_step_id = state.get("active_plan_step_id", "")

    updated = []
    for tc in pending:
        tool_name = str(tc.get("tool_name") or "")
        if tool_name not in EDA_TOOLS:
            updated.append(tc)
            continue
        tool_input = dict(tc.get("tool_input") or {})
        if session_id and (not tool_input.get("session_id") or tool_input.get("session_id") == "default"):
            tool_input["session_id"] = session_id
        if proposal_id and not tool_input.get("proposal_id"):
            tool_input["proposal_id"] = proposal_id
        if plan_step_id and not tool_input.get("plan_step_id"):
            tool_input["plan_step_id"] = plan_step_id
        updated.append({**tc, "tool_input": tool_input})
    return {**state, "pending_tool_calls": updated}


async def eda_evidence_hook(state: AgentState) -> AgentState:
    """Capture a successfully executed or read notebook cell as an anchor."""
    session_id = state.get("session_id", "default")
    for result in state.get("tool_results", []) or []:
        if result.get("tool_name") not in NOTEBOOK_EVIDENCE_TOOLS or result.get("is_error"):
            continue
        payload: Any = result.get("result")
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                payload = {}
        if isinstance(payload, dict):
            stash_notebook_anchor(session_id, payload)
    return state
