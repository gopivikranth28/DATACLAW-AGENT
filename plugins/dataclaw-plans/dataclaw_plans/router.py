"""Plans router — plan CRUD and decision endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from dataclaw_plans.store import read_proposals, find_proposal, write_proposals
from dataclaw_plans.mlflow_tools import query_mlflow_runs, query_mlflow_runs_for_project

router = APIRouter()
mlflow_router = APIRouter()


# ── Plans ───────────────────────────────────────────────────────────────────


@router.get("")
async def list_plan_proposals(session_id: str | None = None) -> list[dict[str, Any]]:
    proposals = read_proposals()
    if session_id:
        proposals = [p for p in proposals if p.get("session_id") == session_id]
    return proposals


@router.get("/{proposal_id}")
async def get_proposal(proposal_id: str) -> dict[str, Any]:
    try:
        return find_proposal(proposal_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Proposal not found")


class DecisionRequest(BaseModel):
    status: str  # "approved" | "denied" | "changes_requested"
    feedback: str = ""


@router.post("/{proposal_id}/decision")
async def submit_decision(proposal_id: str, req: DecisionRequest) -> dict[str, Any]:
    proposals = read_proposals()
    for p in proposals:
        if p["id"] == proposal_id:
            p["status"] = req.status
            p["decision"] = req.status
            p["feedback"] = req.feedback
            write_proposals(proposals)
            return {"proposal_id": proposal_id, "status": req.status}
    raise HTTPException(status_code=404, detail="Proposal not found")


# ── MLflow ──────────────────────────────────────────────────────────────────


@mlflow_router.get("/runs")
async def get_mlflow_runs(session_id: str = "") -> dict[str, Any]:
    return await query_mlflow_runs(session_id=session_id)


@mlflow_router.get("/project-runs")
async def get_project_mlflow_runs(project_id: str = "") -> list[dict[str, Any]]:
    """Get MLflow runs across all sessions in a project."""
    if not project_id:
        return []
    return await query_mlflow_runs_for_project(project_id=project_id)
