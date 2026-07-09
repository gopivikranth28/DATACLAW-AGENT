"""Analysis review lifecycle tools."""

from __future__ import annotations

import json
from typing import Any

from dataclaw.guardrails.base import GuardrailVerdict
from dataclaw.state import AgentState
from dataclaw_analysis_review.checklist import build_review_context, find_plan_step, run_checklist
from dataclaw_analysis_review.store import (
    CATEGORIES,
    FINAL_FINDING_STATUSES,
    FINDING_STATUSES,
    GATE_STATUSES,
    REVIEWER_TYPES,
    SEVERITIES,
    append_finding_resolution,
    append_review_finding,
    append_review_run,
    filter_findings,
    filter_runs,
    find_review_finding,
    fold_review_findings,
    fold_review_runs,
    latest_review_run,
    new_finding_id,
    new_review_id,
    normalize_scope,
    normalize_severity,
    normalize_target,
    now_iso,
    open_required_findings,
    severity_at_least,
)


def _error(code: str, message: str, **details: Any) -> dict[str, Any]:
    return {"success": False, "error": {"code": code, "message": message, **details}}


def _emit(name: str, value: dict[str, Any]) -> None:
    try:
        from dataclaw.api.context import current_emitter, current_thread_id
        from dataclaw.api.run_tracker import get_run_tracker

        emitter = current_emitter.get()
        thread_id = current_thread_id.get()
        get_run_tracker().append_event(thread_id, emitter.custom(name, value))
    except LookupError:
        return
    except Exception:
        return


async def request_analysis_review(
    *,
    scope: str,
    target_id: str | None = None,
    plan_step_id: str = "",
    severity_floor: str = "warning",
    require_subagent: bool = False,
    proposal_id: str = "",
    session_id: str = "default",
    **_: Any,
) -> dict[str, Any]:
    """Run deterministic review checks for a scope and update its gate."""
    try:
        normalized_scope = normalize_scope(scope)
        normalized_target = normalize_target(
            normalized_scope,
            target_id,
            plan_step_id=plan_step_id,
            session_id=session_id,
        )
    except ValueError as exc:
        return _error("invalid_review_scope", str(exc))

    floor = normalize_severity(severity_floor)
    review_id = new_review_id()
    context = build_review_context(
        scope=normalized_scope,
        target_id=normalized_target,
        proposal_id=proposal_id,
        session_id=session_id,
    )
    target_error = _review_target_error(normalized_scope, normalized_target, context)
    if target_error:
        return target_error
    proposal_id = str(context.get("proposal_id") or proposal_id or "")
    candidates = [
        finding
        for finding in run_checklist(context)
        if severity_at_least(str(finding.get("severity") or "warning"), floor)
    ]

    _emit(
        "analysis_review_started",
        {
            "review_id": review_id,
            "scope": normalized_scope,
            "target_id": normalized_target,
            "reviewer_type": "checklist",
        },
    )
    finding_ids = _persist_checklist_findings(
        review_id=review_id,
        candidates=candidates,
        scope=normalized_scope,
        target_id=normalized_target,
        proposal_id=proposal_id,
        plan_step_id=normalized_target if normalized_scope == "plan_step" else plan_step_id,
        session_id=session_id,
    )

    run_record = {
        "review_id": review_id,
        "scope": normalized_scope,
        "target_id": normalized_target,
        "proposal_id": proposal_id,
        "plan_step_id": normalized_target if normalized_scope == "plan_step" else plan_step_id,
        "session_id": session_id,
        "status": "completed",
        "reviewer_type": "checklist",
        "require_subagent": bool(require_subagent),
        "severity_floor": floor,
        "finding_ids": finding_ids,
        "findings_summary": _findings_summary(
            [
                finding
                for finding in fold_review_findings(session_id)
                if finding.get("finding_id") in set(finding_ids)
            ]
        ),
        "created_at": now_iso(),
        "actor": "agent",
    }
    append_review_run(run_record, session_id)
    gate = _compute_review_gate(scope=normalized_scope, target_id=normalized_target, session_id=session_id)
    _sync_plan_gate(
        scope=normalized_scope,
        target_id=normalized_target,
        session_id=session_id,
        proposal_id=proposal_id,
        gate=gate,
    )

    result = {
        "success": True,
        "review_id": review_id,
        "status": run_record["status"],
        "reviewer_type": run_record["reviewer_type"],
        "finding_ids": finding_ids,
        "findings_summary": run_record["findings_summary"],
        "gate": gate,
    }
    _emit("analysis_review_updated", result)
    return result


async def list_review_runs(
    *,
    scope: str | None = None,
    target_id: str | None = None,
    status: str | None = None,
    session_id: str = "default",
    limit: int = 50,
    **_: Any,
) -> dict[str, Any]:
    normalized_scope = normalize_scope(scope) if scope else None
    runs = filter_runs(fold_review_runs(session_id), scope=normalized_scope, target_id=target_id, status=status)
    runs = list(reversed(runs))[: max(int(limit or 50), 0)]
    return {"success": True, "runs": runs, "total": len(runs)}


async def list_review_findings(
    *,
    scope: str | None = None,
    target_id: str | None = None,
    status: str | None = None,
    severity: str | None = None,
    category: str | None = None,
    session_id: str = "default",
    **_: Any,
) -> dict[str, Any]:
    try:
        normalized_scope = normalize_scope(scope) if scope else None
    except ValueError as exc:
        return _error("invalid_review_scope", str(exc))
    if status and status not in FINDING_STATUSES:
        return _error("invalid_review_finding_status", f"Unsupported finding status: {status}", allowed=sorted(FINDING_STATUSES))
    if severity and severity not in SEVERITIES:
        return _error("invalid_review_severity", f"Unsupported review severity: {severity}", allowed=sorted(SEVERITIES))
    if category and category not in CATEGORIES:
        return _error("invalid_review_category", f"Unsupported review category: {category}", allowed=sorted(CATEGORIES))
    findings = filter_findings(
        fold_review_findings(session_id),
        scope=normalized_scope,
        target_id=target_id,
        status=status,
        severity=severity,
        category=category,
    )
    return {"success": True, "findings": findings, "total": len(findings)}


async def resolve_review_finding(
    *,
    finding_id: str,
    status: str,
    rationale: str = "",
    evidence_link: str | None = None,
    session_id: str = "default",
    **_: Any,
) -> dict[str, Any]:
    if status not in FINAL_FINDING_STATUSES:
        return _error(
            "invalid_review_resolution_status",
            f"Unsupported resolution status: {status}",
            allowed=sorted(FINAL_FINDING_STATUSES),
        )
    if status == "accepted_with_rationale" and not rationale.strip():
        return _error("rationale_required", "accepted_with_rationale requires a rationale")
    finding = find_review_finding(finding_id, session_id)
    if finding is None:
        return _error("unknown_review_finding", f"Review finding not found: {finding_id}")
    append_finding_resolution(
        {
            "finding_id": finding_id,
            "status": status,
            "rationale": rationale,
            "evidence_link": evidence_link or "",
            "created_at": now_iso(),
            "actor": "agent",
        },
        session_id,
    )
    updated = find_review_finding(finding_id, session_id) or {}
    scope = str(updated.get("scope") or finding.get("scope") or "")
    target_id = str(updated.get("target_id") or finding.get("target_id") or "")
    gate = _compute_review_gate(scope=scope, target_id=target_id, session_id=session_id)
    _sync_plan_gate(
        scope=scope,
        target_id=target_id,
        session_id=session_id,
        proposal_id=str(updated.get("proposal_id") or finding.get("proposal_id") or ""),
        gate=gate,
    )
    result = {
        "success": True,
        "finding_id": finding_id,
        "status": updated.get("status", status),
        "updated_at": updated.get("resolved_at", ""),
        "gate": gate,
    }
    _emit("analysis_review_updated", result)
    return result


async def get_review_gate(
    *,
    scope: str,
    target_id: str | None = None,
    plan_step_id: str = "",
    session_id: str = "default",
    **_: Any,
) -> dict[str, Any]:
    try:
        normalized_scope = normalize_scope(scope)
        normalized_target = normalize_target(
            normalized_scope,
            target_id,
            plan_step_id=plan_step_id,
            session_id=session_id,
        )
    except ValueError as exc:
        return _error("invalid_review_scope", str(exc))
    gate = _compute_review_gate(scope=normalized_scope, target_id=normalized_target, session_id=session_id)
    return {"success": True, **gate}


def review_gate_resolver(proposal: dict[str, Any], step: dict[str, Any]) -> dict[str, Any]:
    """Live resolver used by dataclaw-plans without importing this plugin there."""
    plan_step_id = str(step.get("plan_step_id") or "")
    session_id = str(proposal.get("session_id") or "default")
    if not plan_step_id:
        return {"status": "unknown", "required": False, "reason": "Missing plan_step_id", "actor": "analysis_review"}
    gate = _compute_review_gate(scope="plan_step", target_id=plan_step_id, session_id=session_id)
    latest = latest_review_run(scope="plan_step", target_id=plan_step_id, session_id=session_id)
    required = bool(gate.get("blocking_findings")) or (latest is not None and gate.get("gate") != "pass")
    return {
        "status": gate["gate"],
        "required": required,
        "reason": gate["reason"],
        "actor": "analysis_review",
        "details": {
            "review_id": gate.get("review_id", ""),
            "reviewer_type": gate.get("reviewer_type", ""),
            "blocking_findings": gate.get("blocking_findings", []),
        },
    }


def _persist_checklist_findings(
    *,
    review_id: str,
    candidates: list[dict[str, Any]],
    scope: str,
    target_id: str,
    proposal_id: str,
    plan_step_id: str,
    session_id: str,
) -> list[str]:
    existing_open = filter_findings(
        fold_review_findings(session_id),
        scope=scope,
        target_id=target_id,
        status="open",
    )
    existing_checklist = [
        finding
        for finding in existing_open
        if str(finding.get("source") or "").startswith("checklist:")
    ]
    existing_by_signature = {
        str(finding.get("signature") or _signature(finding)): finding
        for finding in existing_checklist
    }
    candidate_signatures = {_signature(candidate) for candidate in candidates}
    finding_ids: list[str] = []

    for finding in existing_checklist:
        signature = str(finding.get("signature") or _signature(finding))
        if signature in candidate_signatures:
            continue
        append_finding_resolution(
            {
                "finding_id": finding["finding_id"],
                "status": "resolved",
                "rationale": "Checklist condition no longer observed on rerun",
                "evidence_link": review_id,
                "created_at": now_iso(),
                "actor": "analysis_review",
            },
            session_id,
        )

    for candidate in candidates:
        signature = _signature(candidate)
        existing = existing_by_signature.get(signature)
        if existing:
            finding_ids.append(str(existing["finding_id"]))
            continue
        finding_id = new_finding_id()
        record = {
            **candidate,
            "finding_id": finding_id,
            "review_id": review_id,
            "scope": scope,
            "target_id": target_id,
            "proposal_id": proposal_id,
            "plan_step_id": plan_step_id,
            "session_id": session_id,
            "signature": signature,
            "status": "open",
            "created_at": now_iso(),
            "actor": "analysis_review",
        }
        append_review_finding(record, session_id)
        finding_ids.append(finding_id)
    return finding_ids


def _compute_review_gate(*, scope: str, target_id: str, session_id: str = "default") -> dict[str, Any]:
    if scope not in {"plan_step", "artifact", "living_report", "session"}:
        return {
            "gate": "unknown",
            "status": "unknown",
            "scope": scope,
            "target_id": target_id,
            "blocking_findings": [],
            "reason": f"Unsupported review scope: {scope}",
            "reviewer_type": "",
            "review_id": "",
        }
    latest = latest_review_run(scope=scope, target_id=target_id, session_id=session_id)
    blockers = open_required_findings(scope=scope, target_id=target_id, session_id=session_id)
    if blockers:
        status = "fail"
        reason = "Open required review findings block validation"
    elif latest is None:
        status = "unknown"
        reason = "No analysis review run exists for this scope"
    elif latest.get("require_subagent") and latest.get("reviewer_type") == "checklist":
        status = "unknown"
        reason = "Checklist-only review cannot pass a sub-agent-required scope"
    else:
        status = "pass"
        reason = "No open required review findings"
    assert status in GATE_STATUSES
    return {
        "gate": status,
        "status": status,
        "scope": scope,
        "target_id": target_id,
        "review_id": latest.get("review_id", "") if latest else "",
        "reviewer_type": latest.get("reviewer_type", "") if latest else "",
        "require_subagent": bool(latest.get("require_subagent")) if latest else False,
        "blocking_findings": [
            {
                "finding_id": finding.get("finding_id"),
                "severity": finding.get("severity"),
                "category": finding.get("category"),
                "claim": finding.get("claim"),
                "recommendation": finding.get("recommendation"),
            }
            for finding in blockers
        ],
        "reason": reason,
    }


def _sync_plan_gate(
    *,
    scope: str,
    target_id: str,
    session_id: str,
    proposal_id: str,
    gate: dict[str, Any],
) -> None:
    if scope != "plan_step":
        return
    resolved_proposal_id = proposal_id
    if not resolved_proposal_id:
        proposal, _step = find_plan_step(plan_step_id=target_id, session_id=session_id)
        resolved_proposal_id = str((proposal or {}).get("id") or "")
    if not resolved_proposal_id:
        return
    try:
        from dataclaw_plans.gates import set_step_gate

        result = set_step_gate(
            proposal_id=resolved_proposal_id,
            plan_step_id=target_id,
            gate_name="analysis_review",
            status=str(gate.get("gate") or "unknown"),
            required=True,
            reason=str(gate.get("reason") or ""),
            actor="analysis_review",
            details={
                "review_id": gate.get("review_id", ""),
                "reviewer_type": gate.get("reviewer_type", ""),
                "blocking_findings": gate.get("blocking_findings", []),
                "require_subagent": gate.get("require_subagent", False),
            },
        )
    except Exception:
        return
    _emit(
        "analysis_review_gate_changed",
        {
            "proposal_id": resolved_proposal_id,
            "plan_step_id": target_id,
            "gate": result.get("gate", gate),
        },
    )


def _signature(finding: dict[str, Any]) -> str:
    payload = {
        "source": finding.get("source") or "",
        "claim": finding.get("claim") or "",
        "evidence": finding.get("evidence") or [],
    }
    return json.dumps(payload, sort_keys=True, default=str)


def _findings_summary(findings: list[dict[str, Any]]) -> dict[str, Any]:
    by_severity = {severity: 0 for severity in sorted(SEVERITIES)}
    by_status = {status: 0 for status in sorted(FINDING_STATUSES)}
    for finding in findings:
        severity = str(finding.get("severity") or "warning")
        status = str(finding.get("status") or "open")
        if severity in by_severity:
            by_severity[severity] += 1
        if status in by_status:
            by_status[status] += 1
    return {
        "total": len(findings),
        "by_severity": by_severity,
        "by_status": by_status,
    }


def _review_target_error(scope: str, target_id: str, context: dict[str, Any]) -> dict[str, Any] | None:
    if scope == "session":
        return None
    if scope == "plan_step" and not isinstance(context.get("plan_step"), dict):
        return _error("unknown_review_target", f"Plan step not found: {target_id}", scope=scope, target_id=target_id)
    if scope in {"artifact", "living_report"} and not isinstance(context.get("artifact"), dict):
        return _error("unknown_review_target", f"Artifact not found: {target_id}", scope=scope, target_id=target_id)
    return None


class ReviewFindingAcceptanceGuardrail:
    """Require user approval before an agent accepts a review finding risk."""

    id = "review_finding_acceptance"
    phase = "pre"
    mode = "user_approval"

    def evaluate(self, tool_call: dict[str, Any], state: AgentState) -> GuardrailVerdict | None:
        if tool_call.get("tool_name") != "resolve_review_finding":
            return None
        tool_input = tool_call.get("tool_input", {})
        if tool_input.get("status") != "accepted_with_rationale":
            return None
        finding_id = tool_input.get("finding_id", "review finding")
        rationale = tool_input.get("rationale", "")
        return GuardrailVerdict(
            tool_call_id=tool_call.get("call_id", ""),
            guardrail_id=self.id,
            message=(
                f"The agent wants to accept unresolved analysis-review risk for `{finding_id}`.\n\n"
                f"Rationale: {rationale or '(none provided)'}\n\n"
                "Approve only if you explicitly want to proceed despite this unresolved review finding."
            ),
            mode=self.mode,
            phase=self.phase,
            severity="warning",
        )
