"""Read-only API routes for EDA ledgers."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from dataclaw_eda.store import find_finding, fold_findings, fold_hypotheses
from dataclaw_eda.readiness import evaluate_readiness

router = APIRouter()


@router.get("/hypotheses")
async def get_hypotheses(
    session_id: str = "default",
    dataset_id: str = "",
    plan_step_id: str = "",
    status: str = "",
) -> dict[str, Any]:
    records = fold_hypotheses(session_id)
    if dataset_id:
        records = [r for r in records if r.get("dataset_id") == dataset_id]
    if plan_step_id:
        records = [r for r in records if r.get("plan_step_id") == plan_step_id]
    if status:
        records = [r for r in records if r.get("status") == status]
    return {"hypotheses": records, "total": len(records)}


@router.get("/findings")
async def get_findings(
    session_id: str = "default",
    dataset_id: str = "",
    plan_step_id: str = "",
    status: str = "",
    finding_type: str = "",
    severity: str = "",
) -> dict[str, Any]:
    records = fold_findings(session_id)
    if dataset_id:
        records = [r for r in records if r.get("dataset_id") == dataset_id]
    if plan_step_id:
        records = [r for r in records if r.get("plan_step_id") == plan_step_id]
    if status:
        records = [r for r in records if r.get("status") == status]
    if finding_type:
        records = [r for r in records if r.get("finding_type") == finding_type]
    if severity:
        records = [r for r in records if r.get("severity") == severity]
    return {"findings": records, "total": len(records)}


@router.get("/findings/{finding_id}")
async def get_finding(finding_id: str, session_id: str = "default") -> dict[str, Any]:
    finding = find_finding(finding_id, session_id)
    if finding is None:
        raise HTTPException(status_code=404, detail="Finding not found")
    return finding


@router.get("/readiness")
async def get_readiness(
    dataset_id: str,
    session_id: str = "default",
    purpose: str = "dashboard",
    mode: str = "",
    plan_step_id: str = "",
) -> dict[str, Any]:
    return evaluate_readiness(
        dataset_id=dataset_id,
        session_id=session_id,
        purpose=purpose,
        mode=mode,
        plan_step_id=plan_step_id,
    )
