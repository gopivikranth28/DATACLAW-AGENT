"""Read-only API routes for analysis reviews."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from dataclaw_analysis_review.store import find_review_finding
from dataclaw_analysis_review.tools import get_review_gate, list_review_findings, list_review_runs

router = APIRouter()


@router.get("/runs")
async def get_review_runs(
    session_id: str = "default",
    scope: str = "",
    target_id: str = "",
    status: str = "",
    limit: int = 50,
) -> dict[str, Any]:
    return await list_review_runs(
        session_id=session_id,
        scope=scope or None,
        target_id=target_id or None,
        status=status or None,
        limit=limit,
    )


@router.get("/findings")
async def get_findings(
    session_id: str = "default",
    scope: str = "",
    target_id: str = "",
    status: str = "",
    severity: str = "",
    category: str = "",
) -> dict[str, Any]:
    return await list_review_findings(
        session_id=session_id,
        scope=scope or None,
        target_id=target_id or None,
        status=status or None,
        severity=severity or None,
        category=category or None,
    )


@router.get("/findings/{finding_id}")
async def get_finding(finding_id: str, session_id: str = "default") -> dict[str, Any]:
    finding = find_review_finding(finding_id, session_id)
    if finding is None:
        raise HTTPException(status_code=404, detail="Review finding not found")
    return finding


@router.get("/gate")
async def get_gate(
    scope: str,
    target_id: str = "",
    plan_step_id: str = "",
    session_id: str = "default",
) -> dict[str, Any]:
    return await get_review_gate(
        scope=scope,
        target_id=target_id or None,
        plan_step_id=plan_step_id,
        session_id=session_id,
    )
