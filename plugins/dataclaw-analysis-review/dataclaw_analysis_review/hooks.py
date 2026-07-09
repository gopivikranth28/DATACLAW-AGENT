"""Hooks for automatic checklist review."""

from __future__ import annotations

import json
from typing import Any

from dataclaw.state import AgentState
from dataclaw_analysis_review.checklist import _step_identity, should_auto_review_step
from dataclaw_analysis_review.tools import request_analysis_review
from dataclaw_plans.store import find_proposal, get_active_plan_id

REVIEW_TOOLS = {
    "request_analysis_review",
    "list_review_runs",
    "list_review_findings",
    "resolve_review_finding",
    "get_review_gate",
}


async def review_context_hook(state: AgentState) -> AgentState:
    """Inject session and active plan context into review tool calls."""
    pending = state.get("pending_tool_calls", [])
    session_id = str(state.get("session_id") or "")
    if not pending or not session_id:
        return state
    proposal_id = get_active_plan_id(session_id) or ""
    plan_step_id = str(state.get("active_plan_step_id") or "")

    updated = []
    for tc in pending:
        tool_name = str(tc.get("tool_name") or "")
        if tool_name not in REVIEW_TOOLS:
            updated.append(tc)
            continue
        tool_input = dict(tc.get("tool_input") or {})
        if not tool_input.get("session_id") or tool_input.get("session_id") == "default":
            tool_input["session_id"] = session_id
        if proposal_id and not tool_input.get("proposal_id"):
            tool_input["proposal_id"] = proposal_id
        if plan_step_id and not tool_input.get("plan_step_id"):
            tool_input["plan_step_id"] = plan_step_id
        updated.append({**tc, "tool_input": tool_input})
    return {**state, "pending_tool_calls": updated}


async def auto_review_completed_steps_hook(state: AgentState) -> AgentState:
    """Run checklist review after relevant steps are marked completed."""
    session_id = str(state.get("session_id") or "default")
    for tool_result in state.get("tool_results", []) or []:
        if tool_result.get("is_error") or tool_result.get("tool_name") != "update_plan":
            continue
        result = _parse_payload(tool_result.get("result", tool_result.get("content")))
        if result.get("success") is not True:
            continue
        tool_input = tool_result.get("tool_input") if isinstance(tool_result.get("tool_input"), dict) else {}
        proposal_id = str(tool_input.get("proposal_id") or result.get("proposal_id") or "")
        if not proposal_id:
            continue
        try:
            proposal = find_proposal(proposal_id)
        except KeyError:
            continue
        for patch in tool_input.get("step_patches") or []:
            if not isinstance(patch, dict) or patch.get("status") != "completed":
                continue
            step = _resolve_step(proposal, patch)
            if not step or not should_auto_review_step(step):
                continue
            await request_analysis_review(
                scope="plan_step",
                target_id=_step_identity(step),
                proposal_id=proposal_id,
                session_id=session_id,
                severity_floor="warning",
                require_subagent=False,
            )
    return state


def _parse_payload(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _resolve_step(proposal: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any] | None:
    step_id = str(patch.get("plan_step_id") or patch.get("id") or patch.get("step_id") or "").strip()
    if step_id:
        return next((step for step in proposal.get("steps", []) if _step_identity(step) == step_id), None)
    name = str(patch.get("name") or "").strip()
    matches = [step for step in proposal.get("steps", []) if step.get("name") == name]
    return matches[0] if len(matches) == 1 else None
