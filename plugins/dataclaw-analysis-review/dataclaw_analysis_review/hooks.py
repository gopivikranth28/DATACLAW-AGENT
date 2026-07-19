"""Hooks for automatic checklist review."""

from __future__ import annotations

import json
from typing import Any

from dataclaw.state import AgentState
from dataclaw_analysis_review.checklist import _step_identity, find_plan_step, should_auto_review_step
from dataclaw_analysis_review.store import fold_review_findings
from dataclaw_analysis_review.tools import request_analysis_review
from dataclaw_plans.store import find_proposal, get_active_plan_id

REVIEW_TOOLS = {
    "request_analysis_review",
    "list_review_runs",
    "list_review_findings",
    "resolve_review_finding",
    "get_review_gate",
}

PUBLISH_TOOLS = {"publish_artifact", "dataclaw_publish_artifact"}


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
            review = await request_analysis_review(
                scope="plan_step",
                target_id=_step_identity(step),
                proposal_id=proposal_id,
                session_id=session_id,
                severity_floor="warning",
                require_subagent=False,
            )
            # A completion and its automatic review are separate tool events.  If
            # a step was marked ready in the completion patch, reconcile that
            # optimistic flag with the review that just finished.  This also
            # protects older step names that predate the review-keyword policy.
            review_gate = str((review.get("gate") or {}).get("gate") or "unknown")
            if review_gate == "pass":
                continue
            try:
                refreshed = find_proposal(proposal_id)
                refreshed_step = _resolve_step(refreshed, patch)
                if refreshed_step and refreshed_step.get("ready_for_validation"):
                    from dataclaw_plans.tools import update_plan

                    await update_plan(
                        proposal_id=proposal_id,
                        step_patches=[{
                            "plan_step_id": _step_identity(refreshed_step),
                            "ready_for_validation": False,
                            "note": "Automatic analysis review has unresolved findings.",
                        }],
                        session_id=session_id,
                    )
            except (KeyError, ValueError):
                continue
    return state


async def surface_unreviewed_publish_hook(state: AgentState) -> AgentState:
    """FR-30a: label publishes that happen while required review findings are open.

    Appends an "unresolved review risk" living-report event naming the finding
    ids — unless every open required finding sits on a step whose gate risk was
    explicitly accepted (accepted_with_rationale resolutions are already closed
    and never counted). Unreviewed exports are never silently clean.
    """
    session_id = str(state.get("session_id") or "default")
    for tool_result in state.get("tool_results", []) or []:
        if tool_result.get("is_error") or str(tool_result.get("tool_name") or "") not in PUBLISH_TOOLS:
            continue
        result = _parse_payload(tool_result.get("result", tool_result.get("content")))
        artifact_id = str(result.get("artifact_id") or "")
        if not artifact_id or result.get("success") is False:
            continue
        blockers = _unaccepted_required_findings(session_id)
        if not blockers:
            continue
        finding_ids = [str(f.get("finding_id") or "") for f in blockers]
        listed = ", ".join(f"`{fid}`" for fid in finding_ids if fid)
        try:
            from dataclaw_artifacts.store import append_living_report_event

            append_living_report_event(
                session_id=session_id,
                event={
                    "kind": "note",
                    "page": "log",
                    "plan_step_id": str(result.get("plan_step_id") or ""),
                    "status": "active",
                    "session_id": session_id,
                    "payload": {
                        "md": (
                            f"**Unresolved review risk:** artifact `{artifact_id}` was published with "
                            f"{len(finding_ids)} open required review finding(s): {listed}. "
                            "Resolve them or accept the risk explicitly via the review tools."
                        )
                    },
                },
            )
        except Exception:
            continue
    return state


def _unaccepted_required_findings(session_id: str) -> list[dict[str, Any]]:
    open_required = [
        finding
        for finding in fold_review_findings(session_id)
        if finding.get("status") == "open" and finding.get("severity") == "required"
    ]
    return [
        finding
        for finding in open_required
        if not _gate_risk_accepted(str(finding.get("plan_step_id") or ""), session_id)
    ]


def _gate_risk_accepted(plan_step_id: str, session_id: str) -> bool:
    if not plan_step_id:
        return False
    _proposal, step = find_plan_step(plan_step_id=plan_step_id, session_id=session_id)
    gate = ((step or {}).get("gates") or {}).get("analysis_review") or {}
    if not isinstance(gate, dict):
        return False
    return bool(gate.get("accepted")) or str(gate.get("status") or "") == "accepted"


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
