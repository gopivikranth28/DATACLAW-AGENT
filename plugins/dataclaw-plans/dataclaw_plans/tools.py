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
)


async def propose_plan(
    *,
    name: str,
    description: str,
    steps: list[dict[str, Any]],
    context: str = "",
    session_id: str = "default",
    **kw: Any,
) -> dict[str, Any]:
    """Create or revise a plan proposal for user approval."""
    if not name.strip():
        raise ValueError("Plan name is required")
    if not description.strip():
        raise ValueError("Plan description is required")
    if not steps:
        raise ValueError("At least one step is required")

    normalized = [
        {
            "name": str(s.get("name", "")).strip(),
            "description": str(s.get("description", "")).strip(),
            "status": str(s.get("status") or "not_started"),
            "summary": str(s.get("summary") or ""),
            "outputs": s.get("outputs") or [],
        }
        for s in steps
    ]
    for s in normalized:
        if not s["name"] or not s["description"]:
            raise ValueError("Each step requires name and description")

    proposals = read_proposals()
    now = datetime.now(timezone.utc).isoformat()

    # Auto-resolve: overwrite most recent unapproved plan for this session
    unapproved = next(
        (p for p in proposals if p.get("session_id") == session_id and p.get("status") in ("pending", "changes_requested")),
        None,
    )

    if unapproved:
        unapproved.update({
            "name": name, "description": description, "context": context,
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
            "name": name, "description": description, "context": context,
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

    write_proposals(proposals)
    return {"proposal_id": proposal["id"], "status": proposal["status"], "plan": proposal}


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
            if not step_name:
                raise ValueError("Each step update requires name")
            match = next((s for s in existing if s.get("name") == step_name), None)
            if match is None:
                match = {"name": step_name, "description": "", "status": "not_started"}
                existing.append(match)
            for key in ("description", "status", "summary", "outputs", "note"):
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

        return {"proposal_id": proposal["id"], "status": proposal["status"], "plan": proposal}

    raise KeyError(f"Plan proposal not found: {proposal_id}")


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
