"""Structured EDA tool implementations."""

from __future__ import annotations

import json
from typing import Any

from dataclaw_eda import evidence as evidence_helpers
from dataclaw_eda.readiness import covered_checks, evaluate_readiness
from dataclaw_eda.store import (
    CONFIDENCES,
    EXTERNAL_VALIDATION_BASES,
    EXTERNAL_VALIDATION_STATUSES,
    FINDING_DISPOSITIONS,
    FINDING_TYPES,
    HYPOTHESIS_PRIORITIES,
    HYPOTHESIS_SOURCES,
    HYPOTHESIS_STATUSES,
    INTERNAL_VALIDATION_STATUSES,
    SEVERITIES,
    active_findings,
    append_finding,
    append_hypothesis,
    filter_records,
    find_finding,
    find_hypothesis,
    fold_findings,
    fold_hypotheses,
    new_finding_id,
    new_hypothesis_id,
    now_iso,
)

MANDATORY_EXTERNAL_CAVEAT = "unverified against external evidence"


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


def _normalize_validation(validation: dict[str, Any] | None, evidence: list[dict[str, Any]]) -> dict[str, Any]:
    validation = validation if isinstance(validation, dict) else {}
    internal = validation.get("internal") if isinstance(validation.get("internal"), dict) else {}
    external = validation.get("external") if isinstance(validation.get("external"), dict) else {}
    internal_status = str(internal.get("status") or "not_checked")
    external_status = str(external.get("status") or "not_checked")
    basis = str(external.get("basis") or "none")
    if internal_status not in INTERNAL_VALIDATION_STATUSES:
        internal_status = "not_checked"
    if external_status not in EXTERNAL_VALIDATION_STATUSES:
        external_status = "not_checked"
    if basis not in EXTERNAL_VALIDATION_BASES:
        basis = "none"
    evidence_refs = internal.get("evidence_refs")
    if not isinstance(evidence_refs, list):
        evidence_refs = evidence_helpers.evidence_refs(evidence)
    return {
        "internal": {
            "status": internal_status,
            "method": str(internal.get("method") or ""),
            "evidence_refs": [str(ref) for ref in evidence_refs if str(ref).strip()],
        },
        "external": {
            "status": external_status,
            "basis": basis,
            "note": str(external.get("note") or ""),
        },
    }


def _finding_is_internal_validated(finding: dict[str, Any]) -> bool:
    internal = (finding.get("validation") or {}).get("internal") or {}
    return internal.get("status") == "validated" and bool(internal.get("evidence_refs"))


def _append_hypothesis_update(
    *,
    hypothesis_id: str,
    status: str | None = None,
    disposition_reason: str = "",
    linked_finding_ids: list[str] | None = None,
    priority: str | None = None,
    needs_reevaluation: bool = False,
    session_id: str = "default",
    actor: str = "agent",
) -> None:
    append_hypothesis(
        {
            "record_type": "hypothesis_update",
            "hypothesis_id": hypothesis_id,
            "status": status,
            "priority": priority,
            "disposition_reason": disposition_reason,
            "linked_finding_ids": linked_finding_ids or [],
            "needs_reevaluation": needs_reevaluation,
            "actor": actor,
            "created_at": now_iso(),
        },
        session_id,
    )


async def propose_eda_hypotheses(
    *,
    hypotheses: list[dict[str, Any]],
    dataset_id: str | None = None,
    version_id: str | None = None,
    session_id: str = "default",
    proposal_id: str = "",
    plan_step_id: str = "",
    **_: Any,
) -> dict[str, Any]:
    if len(hypotheses) > 7:
        return _error("hypothesis_batch_too_large", "Initial hypothesis batches are capped at 7", max_count=7)
    high_count = sum(1 for h in hypotheses if str(h.get("priority") or "medium") == "high")
    if high_count > 3:
        return _error("too_many_high_priority_hypotheses", "At most 3 hypotheses may be high priority", max_high=3)

    ids: list[str] = []
    for raw in hypotheses:
        statement = str(raw.get("statement") or "").strip()
        rationale = str(raw.get("rationale") or "").strip()
        source = str(raw.get("source") or "").strip()
        priority = str(raw.get("priority") or "medium").strip()
        if not statement:
            return _error("invalid_hypothesis", "Hypothesis statement is required")
        if source not in HYPOTHESIS_SOURCES:
            return _error("invalid_hypothesis_source", f"Unsupported hypothesis source: {source}", allowed=sorted(HYPOTHESIS_SOURCES))
        if priority not in HYPOTHESIS_PRIORITIES:
            return _error("invalid_hypothesis_priority", f"Unsupported priority: {priority}", allowed=sorted(HYPOTHESIS_PRIORITIES))
        if source == "data_signal" and not rationale:
            return _error("data_signal_requires_rationale", "source='data_signal' hypotheses must cite the prompting observation")
        hypothesis_id = new_hypothesis_id()
        ids.append(hypothesis_id)
        append_hypothesis(
            {
                "record_type": "hypothesis",
                "hypothesis_id": hypothesis_id,
                "statement": statement,
                "rationale": rationale,
                "source": source,
                "priority": priority,
                "covers_checks": [str(c) for c in (raw.get("covers_checks") or []) if str(c).strip()],
                "status": "open",
                "dataset_id": dataset_id or "",
                "version_id": version_id or "",
                "session_id": session_id,
                "proposal_id": proposal_id,
                "plan_step_id": plan_step_id,
                "created_at": now_iso(),
                "actor": "agent",
            },
            session_id,
        )

    open_count = sum(
        1
        for h in fold_hypotheses(session_id)
        if (not dataset_id or h.get("dataset_id") == dataset_id) and h.get("status") in {"open", "testing"}
    )
    result = {"success": True, "hypothesis_ids": ids, "count": len(ids), "open_hypothesis_count": open_count}
    if open_count > 10:
        result["warning"] = "Open hypothesis count exceeds 10; prioritize before adding more."
    _emit("eda_hypothesis_proposed", result)
    return result


async def update_eda_hypothesis(
    *,
    hypothesis_id: str,
    status: str,
    disposition_reason: str = "",
    linked_finding_ids: list[str] | None = None,
    priority: str | None = None,
    session_id: str = "default",
    **_: Any,
) -> dict[str, Any]:
    if status not in HYPOTHESIS_STATUSES:
        return _error("invalid_hypothesis_status", f"Unsupported status: {status}", allowed=sorted(HYPOTHESIS_STATUSES))
    if priority and priority not in HYPOTHESIS_PRIORITIES:
        return _error("invalid_hypothesis_priority", f"Unsupported priority: {priority}", allowed=sorted(HYPOTHESIS_PRIORITIES))
    hypothesis = find_hypothesis(hypothesis_id, session_id)
    if hypothesis is None:
        return _error("unknown_hypothesis", f"Hypothesis not found: {hypothesis_id}")

    linked_finding_ids = linked_finding_ids or []
    linked_findings = [find_finding(fid, session_id) for fid in linked_finding_ids]
    linked_findings = [f for f in linked_findings if f is not None]
    if status == "confirmed" and not any(_finding_is_internal_validated(f) for f in linked_findings):
        return _error("confirmed_requires_validated_finding", "Confirmed hypotheses require a linked finding with internal validation evidence")
    if status == "rejected" and not linked_findings:
        return _error("rejected_requires_finding", "Rejected hypotheses require linked rejecting evidence")

    previous_status = hypothesis.get("status")
    warning = ""
    if previous_status in {"confirmed", "rejected"} and previous_status != status:
        warning = f"Odd transition recorded: {previous_status} -> {status}"
    _append_hypothesis_update(
        hypothesis_id=hypothesis_id,
        status=status,
        disposition_reason=disposition_reason,
        linked_finding_ids=linked_finding_ids,
        priority=priority,
        session_id=session_id,
    )
    updated = find_hypothesis(hypothesis_id, session_id) or {}
    result = {
        "success": True,
        "hypothesis_id": hypothesis_id,
        "status": updated.get("status", status),
        "history_len": len(updated.get("history") or []),
    }
    if warning:
        result["warning"] = warning
    _emit("eda_hypothesis_updated", result)
    return result


async def list_eda_hypotheses(
    *,
    dataset_id: str | None = None,
    plan_step_id: str | None = None,
    status: str | None = None,
    source: str | None = None,
    priority: str | None = None,
    session_id: str = "default",
    **_: Any,
) -> dict[str, Any]:
    records = filter_records(
        fold_hypotheses(session_id),
        dataset_id=dataset_id,
        plan_step_id=plan_step_id,
        status=status,
        source=source,
        priority=priority,
    )
    return {"success": True, "hypotheses": records, "total": len(records)}


async def record_eda_finding(
    *,
    title: str,
    finding_type: str,
    summary: str,
    evidence: Any,
    dataset_id: str,
    version_id: str | None = None,
    severity: str = "info",
    caveat: str = "",
    next_action: str = "",
    confidence: str = "medium",
    hypothesis_id: str = "",
    hypothesis_status: str | None = None,
    disposition: str = "unresolved",
    validation: dict[str, Any] | None = None,
    covers_checks: list[str] | None = None,
    session_id: str = "default",
    proposal_id: str = "",
    plan_step_id: str = "",
    **_: Any,
) -> dict[str, Any]:
    if hypothesis_status == "rejected":
        finding_type = "rejected_hypothesis"
        disposition = "rejected"
    if finding_type not in FINDING_TYPES:
        return _error("invalid_finding_type", f"Unsupported finding_type: {finding_type}", allowed=sorted(FINDING_TYPES))
    if severity not in SEVERITIES:
        return _error("invalid_severity", f"Unsupported severity: {severity}", allowed=sorted(SEVERITIES))
    if confidence not in CONFIDENCES:
        return _error("invalid_confidence", f"Unsupported confidence: {confidence}", allowed=sorted(CONFIDENCES))
    if disposition not in FINDING_DISPOSITIONS:
        return _error("invalid_disposition", f"Unsupported disposition: {disposition}", allowed=sorted(FINDING_DISPOSITIONS))
    if hypothesis_status and hypothesis_status not in HYPOTHESIS_STATUSES:
        return _error("invalid_hypothesis_status", f"Unsupported hypothesis_status: {hypothesis_status}", allowed=sorted(HYPOTHESIS_STATUSES))
    if hypothesis_id and find_hypothesis(hypothesis_id, session_id) is None:
        return _error("unknown_hypothesis", f"Hypothesis not found: {hypothesis_id}")

    anchors = evidence_helpers.normalize_evidence(evidence, session_id=session_id)
    normalized_validation = _normalize_validation(validation, anchors)
    internal = normalized_validation["internal"]
    external = normalized_validation["external"]
    if internal["status"] == "validated" and not internal["evidence_refs"]:
        return _error("validated_requires_evidence_refs", "Internal validation requires non-empty evidence_refs")
    if confidence == "high" and (internal["status"] != "validated" or not internal["evidence_refs"]):
        return _error("high_confidence_requires_internal_validation", "High confidence requires internal validated status with evidence_refs")

    caveats: list[str] = [caveat.strip()] if caveat.strip() else []
    if external["status"] == "unverified":
        if not any(MANDATORY_EXTERNAL_CAVEAT in c for c in caveats):
            caveats.append(MANDATORY_EXTERNAL_CAVEAT)
        if confidence == "high":
            confidence = "medium"

    finding_id = new_finding_id()
    attribution_status = "attributed" if plan_step_id else "unattributed_step"
    record = {
        "record_type": "finding",
        "finding_id": finding_id,
        "title": title.strip(),
        "finding_type": finding_type,
        "summary": summary.strip(),
        "evidence": anchors,
        "dataset_id": dataset_id,
        "version_id": version_id or "",
        "severity": severity,
        "caveat": " ".join(caveats),
        "next_action": next_action,
        "confidence": confidence,
        "hypothesis_id": hypothesis_id,
        "hypothesis_status": hypothesis_status or "",
        "disposition": disposition,
        "validation": normalized_validation,
        "covers_checks": [str(c) for c in (covers_checks or []) if str(c).strip()],
        "session_id": session_id,
        "proposal_id": proposal_id,
        "plan_step_id": plan_step_id,
        "attribution_status": attribution_status,
        "status": "active",
        "created_at": now_iso(),
        "actor": "agent",
    }

    if hypothesis_status == "confirmed" and (internal["status"] != "validated" or not internal["evidence_refs"]):
        return _error("confirmed_requires_internal_validation", "Confirmed findings require internal validation evidence")

    append_finding(record, session_id)
    if hypothesis_id and hypothesis_status:
        _append_hypothesis_update(
            hypothesis_id=hypothesis_id,
            status=hypothesis_status,
            disposition_reason=summary,
            linked_finding_ids=[finding_id],
            session_id=session_id,
        )
    result = {
        "success": True,
        "finding_id": finding_id,
        "status": "active",
        "anchors": anchors,
        "hypothesis_id": hypothesis_id,
        "attribution_status": attribution_status,
        "finding": record,
    }
    _emit("eda_finding_recorded", result)
    return result


async def supersede_eda_finding(
    *,
    finding_id: str,
    reason: str,
    replacement_id: str | None = None,
    session_id: str = "default",
    **_: Any,
) -> dict[str, Any]:
    finding = find_finding(finding_id, session_id)
    if finding is None:
        return _error("unknown_finding", f"Finding not found: {finding_id}")
    if replacement_id and find_finding(replacement_id, session_id) is None:
        return _error("unknown_replacement", f"Replacement finding not found: {replacement_id}")

    append_finding(
        {
            "record_type": "supersede",
            "finding_id": finding_id,
            "reason": reason,
            "replacement_id": replacement_id or "",
            "created_at": now_iso(),
            "actor": "agent",
        },
        session_id,
    )
    hypothesis_id = str(finding.get("hypothesis_id") or "")
    if hypothesis_id:
        hypothesis = find_hypothesis(hypothesis_id, session_id)
        if hypothesis and hypothesis.get("status") in {"confirmed", "rejected"}:
            _append_hypothesis_update(
                hypothesis_id=hypothesis_id,
                status=str(hypothesis.get("status") or ""),
                disposition_reason=f"Linked finding superseded: {reason}",
                linked_finding_ids=[],
                needs_reevaluation=True,
                session_id=session_id,
            )
    result = {"success": True, "finding_id": finding_id, "status": "superseded", "replacement_id": replacement_id or ""}
    _emit("eda_finding_superseded", result)
    return result


async def list_eda_findings(
    *,
    dataset_id: str | None = None,
    plan_step_id: str | None = None,
    status: str | None = None,
    severity: str | None = None,
    finding_type: str | None = None,
    hypothesis_id: str | None = None,
    session_id: str = "default",
    **_: Any,
) -> dict[str, Any]:
    records = filter_records(
        fold_findings(session_id),
        dataset_id=dataset_id,
        plan_step_id=plan_step_id,
        status=status,
        severity=severity,
        finding_type=finding_type,
        hypothesis_id=hypothesis_id,
    )
    return {"success": True, "findings": records, "total": len(records)}


async def read_eda_finding(*, finding_id: str, session_id: str = "default", **_: Any) -> dict[str, Any]:
    finding = find_finding(finding_id, session_id)
    if finding is None:
        return _error("unknown_finding", f"Finding not found: {finding_id}")
    return {"success": True, "finding": finding}


async def summarize_eda_readiness(
    *,
    dataset_id: str,
    version_id: str | None = None,
    purpose: str = "dashboard",
    required_checks: list[str] | None = None,
    mode: str = "",
    session_id: str = "default",
    proposal_id: str = "",
    plan_step_id: str = "",
    **_: Any,
) -> dict[str, Any]:
    verdict = evaluate_readiness(
        dataset_id=dataset_id,
        session_id=session_id,
        purpose=purpose,
        mode=mode,
        required_checks=required_checks,
    )
    severity = "blocker" if verdict["status"] == "blocked" else "warning" if verdict["status"] in {"unknown", "ready_with_caveats"} else "info"
    validation = {
        "internal": {"status": "not_checked", "method": "readiness_policy", "evidence_refs": verdict["evidence_links"]},
        "external": {"status": "not_checked", "basis": "none", "note": ""},
    }
    result = await record_eda_finding(
        title=f"EDA readiness for {purpose}",
        finding_type="readiness",
        summary=json.dumps(verdict, default=str),
        evidence={"kind": "interpretive_note", "text": f"Readiness policy evaluated for {purpose}"},
        dataset_id=dataset_id,
        version_id=version_id,
        severity=severity,
        caveat="; ".join(c.get("next_action") or c.get("question") or "" for c in verdict["caveats"] + verdict["questions"]).strip(),
        next_action="Resolve blockers before proceeding" if verdict["status"] == "blocked" else "",
        confidence="medium",
        disposition="blocked" if verdict["status"] == "blocked" else "confirmed",
        validation=validation,
        covers_checks=["readiness"],
        session_id=session_id,
        proposal_id=proposal_id,
        plan_step_id=plan_step_id,
    )
    verdict["finding_id"] = result.get("finding_id")
    final = {"success": True, **verdict}
    _emit("eda_summary_ready", final)
    return final
