"""Plan tools — propose, update, query plans."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

from dataclaw_plans.store import (
    read_proposals,
    write_proposals,
    find_proposal,
    get_active_plan_id,
    append_snapshot,
)


def _new_step_id() -> str:
    return f"step-{uuid.uuid4().hex[:8]}"


def _step_identity(step: dict[str, Any]) -> str:
    explicit = str(step.get("plan_step_id") or step.get("id") or step.get("step_id") or "").strip()
    if explicit:
        return explicit
    return ""


def _normalize_steps(steps: list[dict[str, Any]], previous_steps: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    previous = previous_steps or []
    previous_by_id = {_step_identity(s): s for s in previous if _step_identity(s)}
    previous_by_name: dict[str, list[dict[str, Any]]] = {}
    for step in previous:
        name_key = str(step.get("name") or "").strip().lower()
        if name_key:
            previous_by_name.setdefault(name_key, []).append(step)

    normalized: list[dict[str, Any]] = []
    for raw in steps:
        name = str(raw.get("name", "")).strip()
        description = str(raw.get("description", "")).strip()
        provided_id = _step_identity(raw)
        prior = previous_by_id.get(provided_id) if provided_id else None
        if prior is None and name:
            name_matches = previous_by_name.get(name.lower(), [])
            if len(name_matches) == 1:
                prior = name_matches[0]
        prior_id = _step_identity(prior) if prior else ""
        step_id = provided_id or prior_id or _new_step_id()
        normalized.append({
            "plan_step_id": step_id,
            "name": name,
            "description": description,
            "status": str(raw.get("status") or "not_started"),
            "summary": str(raw.get("summary") or ""),
            "outputs": raw.get("outputs") or [],
        })
    return normalized


async def propose_plan(
    *,
    name: str,
    description: str,
    steps: list[dict[str, Any]],
    context: str = "",
    plan_markdown: str = "",
    session_id: str = "default",
    _auto_approve: bool = False,
    **kw: Any,
) -> dict[str, Any]:
    """Create or revise a plan proposal for user approval."""
    if not name.strip():
        raise ValueError("Plan name is required")
    if not description.strip():
        raise ValueError("Plan description is required")
    if not steps:
        raise ValueError("At least one step is required")

    proposals = read_proposals()

    # Auto-resolve: overwrite most recent unapproved plan for this session.
    # Grab it before normalizing so revised plans can keep stable step ids.
    unapproved = next(
        (p for p in proposals if p.get("session_id") == session_id and p.get("status") in ("pending", "changes_requested")),
        None,
    )

    normalized = _normalize_steps(steps, unapproved.get("steps", []) if unapproved else None)
    for s in normalized:
        if not s["name"] or not s["description"]:
            raise ValueError("Each step requires name and description")

    now = datetime.now(timezone.utc).isoformat()
    previous_snapshot = None
    previous_feedback = ""

    if unapproved:
        previous_feedback = str(unapproved.get("feedback") or "")
        previous_snapshot = append_snapshot(unapproved, trigger="pre_revise")
        unapproved.update({
            "name": name, "description": description, "context": context, "plan_markdown": plan_markdown,
            "steps": normalized, "status": "pending",
            "updated_at": now, "decision": None, "feedback": "",
            "revision": int(unapproved.get("revision", 1)) + 1,
        })
        proposal = unapproved
    else:
        iteration = sum(1 for p in proposals if p.get("session_id") == session_id) + 1
        proposal = {
            "id": f"plan-{uuid.uuid4().hex[:8]}",
            "iteration": iteration,
            "name": name, "description": description, "context": context, "plan_markdown": plan_markdown,
            "session_id": session_id,
            "steps": normalized,
            "status": "pending",
            "created_at": now, "updated_at": now,
            "decision": None, "feedback": "", "revision": 1,
        }
        proposals.insert(0, proposal)

    # Auto-create MLflow experiment for this session
    try:
        from dataclaw_plans.mlflow_tools import get_or_create_experiment
        exp_id = get_or_create_experiment(session_id)
        proposal["mlflow_experiment_id"] = exp_id
    except Exception:
        logger.debug("MLflow experiment creation skipped", exc_info=True)

    # Auto-approve when auto mode is active
    if _auto_approve:
        proposal["status"] = "approved"
        proposal["decision"] = "approved"

    write_proposals(proposals)
    snapshot = append_snapshot(proposal, trigger="propose")
    result = {
        "proposal_id": proposal["id"],
        "snapshot_id": snapshot["id"],
        "status": proposal["status"],
        "revision": proposal["revision"],
        "message": (
            "Plan auto-approved." if proposal["status"] == "approved"
            else "Plan submitted — awaiting user decision."
        ),
    }
    if previous_snapshot:
        result["previous_snapshot_id"] = previous_snapshot["id"]
    if previous_feedback:
        result["previous_feedback"] = previous_feedback
    return result


async def update_plan(
    *,
    proposal_id: str,
    step_patches: list[dict[str, Any]] | None = None,
    status: str | None = None,
    summary: str = "",
    session_id: str = "default",
    **kw: Any,
) -> dict[str, Any]:
    """Update progress for one or more steps on an existing plan."""
    patches = step_patches or []
    proposals = read_proposals()

    for proposal in proposals:
        if proposal["id"] != proposal_id:
            continue

        existing = proposal.get("steps", [])
        for update in patches:
            step_name = str(update.get("name", "")).strip()
            step_id = _step_identity(update)
            if not step_id and not step_name:
                raise ValueError("Each step update requires plan_step_id or name")
            match = next((s for s in existing if step_id and _step_identity(s) == step_id), None)
            if match is None and not step_id:
                matches = [s for s in existing if s.get("name") == step_name]
                if len(matches) > 1:
                    raise ValueError(f"Step name is ambiguous; use plan_step_id: {step_name}")
                match = matches[0] if matches else None
            if match is None:
                if step_id and not step_name:
                    raise ValueError(f"Unknown plan_step_id requires name: {step_id}")
                match = {"plan_step_id": step_id or _new_step_id(), "name": step_name, "description": "", "status": "not_started"}
                existing.append(match)
            if step_id:
                match["plan_step_id"] = step_id
            elif not match.get("plan_step_id"):
                match["plan_step_id"] = _step_identity(match) or _new_step_id()
            match.pop("id", None)
            match.pop("step_id", None)
            for key in ("name", "description", "status", "summary", "outputs", "note", "ready_for_validation", "gates"):
                if key in update:
                    match[key] = update[key]
            match["updated_at"] = datetime.now(timezone.utc).isoformat()

        proposal["steps"] = existing
        if status:
            proposal["status"] = status
        if summary:
            proposal["progress_summary"] = summary
        proposal["updated_at"] = datetime.now(timezone.utc).isoformat()
        write_proposals(proposals)

        snapshot = append_snapshot(proposal, trigger="update")
        return {
            "proposal_id": proposal["id"],
            "snapshot_id": snapshot["id"],
            "status": proposal["status"],
            "steps_updated": len(patches),
            "success": True,
        }

    return {
        "success": False,
        "proposal_id": proposal_id,
        "error": "Plan proposal not found",
    }


async def get_plan_decision(
    *,
    proposal_id: str,
    **kw: Any,
) -> dict[str, Any]:
    """Return the current decision for a plan."""
    proposal = find_proposal(proposal_id)
    return {
        "proposal_id": proposal["id"],
        "status": proposal["status"],
        "decision": proposal.get("decision"),
        "feedback": proposal.get("feedback", ""),
    }


async def list_plans(
    *,
    session_id: str = "",
    limit: int = 10,
    **kw: Any,
) -> dict[str, Any]:
    """List plan proposals, optionally filtered by session."""
    proposals = read_proposals()
    if session_id:
        proposals = [p for p in proposals if p.get("session_id") == session_id]
    items = [
        {
            "id": p["id"], "name": p.get("name", ""),
            "status": p.get("status"), "iteration": p.get("iteration"),
            "steps_total": len(p.get("steps", [])),
            "steps_completed": sum(1 for s in p.get("steps", []) if s.get("status") == "completed"),
        }
        for p in proposals[:limit]
    ]
    return {"plans": items, "total": len(proposals)}


async def get_plan(
    *,
    proposal_id: str,
    **kw: Any,
) -> dict[str, Any]:
    """Get a plan by ID."""
    return find_proposal(proposal_id)
