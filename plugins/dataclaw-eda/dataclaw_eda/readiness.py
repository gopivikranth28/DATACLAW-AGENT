"""Readiness policies for structured EDA."""

from __future__ import annotations

from collections import Counter
from typing import Any

from dataclaw_eda.store import active_findings, fold_hypotheses

PURPOSE_REQUIRED_CHECKS: dict[str, set[str]] = {
    "query": {"data_quality", "missingness"},
    "dashboard": {"distribution", "missingness", "segment_comparison"},
    "modeling": {"data_quality", "missingness", "distribution", "leakage_risk"},
}

MODE_CHECK_OVERLAY: dict[str, set[str]] = {
    "modeling-readiness": {"target_distribution", "leakage_risk", "feature_availability"},
    "modeling": {"target_distribution", "leakage_risk", "feature_availability"},
    "dashboard/kpi": {"denominator_grain", "time_coverage"},
    "dashboard": {"denominator_grain", "time_coverage"},
    "data-quality": {"data_quality", "missingness", "duplicates"},
    "time-series": {"time_coverage", "temporal_leakage"},
    "event/log/funnel": {"identity_resolution", "event_order", "duplicates"},
    "survey/research": {"sample_size", "missingness", "segment_comparison"},
}

FINDING_TYPE_CHECKS: dict[str, set[str]] = {
    "distribution": {"distribution"},
    "missingness": {"missingness"},
    "outlier": {"outliers"},
    "segment_difference": {"segment_comparison"},
    "correlation_candidate": {"relationship_check"},
    "leakage_risk": {"leakage_risk"},
    "rejected_hypothesis": set(),
    "data_quality": {"data_quality"},
    "caveat": {"no_material_findings"},
    "readiness": {"readiness"},
}


def required_checks_for(purpose: str, mode: str = "", required_checks: list[str] | None = None) -> set[str]:
    checks = set(PURPOSE_REQUIRED_CHECKS.get((purpose or "dashboard").lower(), PURPOSE_REQUIRED_CHECKS["dashboard"]))
    normalized_mode = (mode or "").strip().lower()
    if normalized_mode in MODE_CHECK_OVERLAY:
        checks |= MODE_CHECK_OVERLAY[normalized_mode]
    if required_checks:
        checks |= {str(check) for check in required_checks if str(check).strip()}
    return checks


def covered_checks(finding: dict[str, Any]) -> set[str]:
    checks = set(FINDING_TYPE_CHECKS.get(str(finding.get("finding_type") or ""), set()))
    checks |= {str(check) for check in (finding.get("covers_checks") or []) if str(check).strip()}
    return checks


def evaluate_readiness(
    *,
    dataset_id: str,
    session_id: str = "default",
    purpose: str = "dashboard",
    mode: str = "",
    required_checks: list[str] | None = None,
) -> dict[str, Any]:
    findings = [
        finding
        for finding in active_findings(session_id)
        if str(finding.get("dataset_id") or "") == str(dataset_id)
    ]
    hypotheses = [
        hyp
        for hyp in fold_hypotheses(session_id)
        if not dataset_id or str(hyp.get("dataset_id") or "") == str(dataset_id)
    ]

    required = required_checks_for(purpose, mode, required_checks)
    satisfied: set[str] = set()
    hypotheses_by_id = {str(h.get("hypothesis_id") or ""): h for h in hypotheses}
    for finding in findings:
        satisfied |= covered_checks(finding)
        if finding.get("finding_type") == "rejected_hypothesis":
            hyp = hypotheses_by_id.get(str(finding.get("hypothesis_id") or ""))
            if hyp:
                satisfied |= {str(check) for check in (hyp.get("covers_checks") or []) if str(check).strip()}
    missing = sorted(required - satisfied)

    blockers: list[dict[str, Any]] = []
    caveats: list[dict[str, Any]] = []
    questions: list[dict[str, Any]] = []

    for finding in findings:
        if finding.get("severity") == "blocker" and finding.get("finding_type") != "readiness":
            blockers.append(
                {
                    "kind": "blocker_finding",
                    "finding_id": finding.get("finding_id"),
                    "title": finding.get("title", ""),
                }
            )

    for check in missing:
        blockers.append({"kind": "missing_check", "check": check})

    for hyp in hypotheses:
        status = str(hyp.get("status") or "open")
        priority = str(hyp.get("priority") or "medium")
        reason = str(hyp.get("disposition_reason") or "")
        if status in {"open", "testing"} and reason.lower().startswith("deferred: loop budget"):
            caveats.append(
                {
                    "kind": "deferred_hypothesis",
                    "hypothesis_id": hyp.get("hypothesis_id"),
                    "statement": hyp.get("statement", ""),
                    "next_action": reason,
                }
            )
            continue
        if status in {"open", "testing"} and priority == "high":
            blockers.append(
                {
                    "kind": "open_hypothesis",
                    "hypothesis_id": hyp.get("hypothesis_id"),
                    "statement": hyp.get("statement", ""),
                    "priority": priority,
                }
            )
        if status == "unresolved_needs_domain_input":
            item = {
                "kind": "domain_input",
                "hypothesis_id": hyp.get("hypothesis_id"),
                "statement": hyp.get("statement", ""),
                "question": hyp.get("disposition_reason") or hyp.get("statement", ""),
            }
            questions.append(item)
            blockers.append(item)

    if blockers:
        status = "blocked"
    elif not findings and not hypotheses:
        status = "unknown"
    elif caveats:
        status = "ready_with_caveats"
    else:
        status = "ready"

    counts = Counter(str(h.get("status") or "open") for h in hypotheses)
    return {
        "status": status,
        "purpose": purpose,
        "mode": mode,
        "dataset_id": dataset_id,
        "required_checks": sorted(required),
        "satisfied_checks": sorted(satisfied),
        "missing_checks": missing,
        "blockers": blockers,
        "caveats": caveats,
        "questions": questions,
        "hypotheses": {
            "counts": dict(counts),
            "cited": [
                {
                    "hypothesis_id": h.get("hypothesis_id"),
                    "statement": h.get("statement", ""),
                    "status": h.get("status"),
                    "priority": h.get("priority"),
                }
                for h in hypotheses
                if h.get("status") in {"confirmed", "rejected", "unresolved_needs_domain_input"}
                or h.get("priority") == "high"
            ],
            "deferred": caveats,
        },
        "evidence_links": [f.get("finding_id") for f in findings if f.get("finding_id")],
    }
