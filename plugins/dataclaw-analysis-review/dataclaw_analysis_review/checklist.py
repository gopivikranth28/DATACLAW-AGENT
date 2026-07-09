"""Deterministic analysis-review checklist."""

from __future__ import annotations

import json
import re
from typing import Any

from dataclaw_eda.store import fold_findings, fold_hypotheses
from dataclaw_plans.gates import step_requires_review_gate
from dataclaw_plans.store import find_proposal, read_proposals

EDA_STEP_KEYWORDS = (
    "eda",
    "exploratory",
    "explore",
    "profile",
    "profiling",
    "readiness",
    "data quality",
)


def _step_identity(step: dict[str, Any]) -> str:
    return str(step.get("plan_step_id") or step.get("id") or step.get("step_id") or "").strip()


def _step_text(step: dict[str, Any]) -> str:
    return " ".join(
        [
            str(step.get("name") or ""),
            str(step.get("description") or ""),
            str(step.get("summary") or ""),
            " ".join(str(o) for o in (step.get("outputs") or [])),
        ]
    ).lower()


def step_claims_eda(step: dict[str, Any]) -> bool:
    haystack = _step_text(step)
    return any(keyword in haystack for keyword in EDA_STEP_KEYWORDS)


def should_auto_review_step(step: dict[str, Any]) -> bool:
    return step_requires_review_gate(step) or step_claims_eda(step)


def find_plan_step(
    *,
    proposal_id: str = "",
    plan_step_id: str = "",
    session_id: str = "default",
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    proposals = read_proposals()
    if proposal_id:
        try:
            proposal = find_proposal(proposal_id)
        except KeyError:
            return None, None
        step = next((s for s in proposal.get("steps", []) if _step_identity(s) == plan_step_id), None)
        return proposal, step

    for proposal in proposals:
        if session_id and proposal.get("session_id") not in {"", session_id}:
            continue
        for step in proposal.get("steps", []):
            if _step_identity(step) == plan_step_id:
                return proposal, step
    return None, None


def build_review_context(
    *,
    scope: str,
    target_id: str,
    proposal_id: str = "",
    session_id: str = "default",
) -> dict[str, Any]:
    context: dict[str, Any] = {
        "scope": scope,
        "target_id": target_id,
        "session_id": session_id,
        "proposal_id": proposal_id,
        "plan_step": None,
        "eda_findings": [],
        "eda_hypotheses": [],
        "artifact": None,
        "artifact_sections": [],
    }

    if scope == "plan_step":
        proposal, step = find_plan_step(proposal_id=proposal_id, plan_step_id=target_id, session_id=session_id)
        if proposal:
            context["proposal_id"] = proposal.get("id") or proposal_id
            context["proposal"] = proposal
        if step:
            context["plan_step"] = step
        findings = [
            finding
            for finding in fold_findings(session_id)
            if str(finding.get("plan_step_id") or "") == target_id and finding.get("status") == "active"
        ]
        linked_hypotheses = {str(f.get("hypothesis_id") or "") for f in findings if f.get("hypothesis_id")}
        hypotheses = [
            hyp
            for hyp in fold_hypotheses(session_id)
            if str(hyp.get("plan_step_id") or "") == target_id
            or str(hyp.get("hypothesis_id") or "") in linked_hypotheses
        ]
        context["eda_findings"] = findings
        context["eda_hypotheses"] = hypotheses
        return context

    if scope == "session":
        context["eda_findings"] = [f for f in fold_findings(session_id) if f.get("status") == "active"]
        context["eda_hypotheses"] = fold_hypotheses(session_id)
        return context

    if scope in {"artifact", "living_report"}:
        artifact, sections = _artifact_context(target_id, living_report=scope == "living_report")
        context["artifact"] = artifact
        context["artifact_sections"] = sections
        if artifact:
            context["proposal_id"] = proposal_id
            step_id = str(artifact.get("plan_step_id") or "")
            if step_id:
                context["target_plan_step_id"] = step_id
        return context

    return context


def run_checklist(context: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    findings.extend(_plan_step_checks(context))
    findings.extend(_hypothesis_checks(context))
    findings.extend(_finding_validation_checks(context))
    findings.extend(_artifact_checks(context))
    return findings


def _plan_step_checks(context: dict[str, Any]) -> list[dict[str, Any]]:
    step = context.get("plan_step")
    if not isinstance(step, dict):
        return []
    step_id = str(context.get("target_id") or _step_identity(step))
    findings = context.get("eda_findings") or []
    hypotheses = context.get("eda_hypotheses") or []
    completed = step.get("status") == "completed"
    results: list[dict[str, Any]] = []

    if completed and should_auto_review_step(step):
        has_no_material_caveat = any(
            f.get("finding_type") == "caveat"
            and (
                "no_material_findings" in {str(c) for c in (f.get("covers_checks") or [])}
                or "no material" in f"{f.get('title', '')} {f.get('summary', '')}".lower()
            )
            for f in findings
        )
        if not findings and not has_no_material_caveat:
            results.append(
                _finding(
                    check_id="CHK-step-no-findings",
                    severity="required",
                    category="unsupported_claim",
                    claim=f"Completed EDA step {step_id} has no EDA findings or no-material-findings caveat",
                    evidence=[step_id],
                    recommendation="Record material findings or an explicit no-material-findings caveat before validation",
                )
            )

    if completed and step_claims_eda(step):
        readiness = _latest_readiness_finding(findings)
        if readiness is None:
            results.append(
                _finding(
                    check_id="CHK-readiness-missing",
                    severity="required",
                    category="data_quality_caveat",
                    claim=f"Completed EDA step {step_id} has no readiness verdict",
                    evidence=[step_id],
                    recommendation="Call summarize_eda_readiness and address blockers before validation",
                )
            )
        else:
            status = _readiness_status(readiness)
            if status in {"blocked", "unknown"}:
                results.append(
                    _finding(
                        check_id="CHK-readiness-missing",
                        severity="required",
                        category="data_quality_caveat",
                        claim=f"Readiness verdict for {step_id} is {status}",
                        evidence=[str(readiness.get("finding_id") or step_id)],
                        recommendation="Resolve readiness blockers or record an explicit accepted risk",
                    )
                )

    if completed:
        for hyp in hypotheses:
            reason = str(hyp.get("disposition_reason") or "").lower()
            if reason.startswith("deferred: loop budget"):
                continue
            if hyp.get("priority") == "high" and hyp.get("status") in {"open", "testing"}:
                results.append(
                    _finding(
                        check_id="CHK-open-hypotheses",
                        severity="required",
                        category="hypothesis_hygiene",
                        claim="Completed step has an open high-priority hypothesis",
                        evidence=[str(hyp.get("hypothesis_id") or step_id)],
                        recommendation="Resolve, defer with rationale, or mark the hypothesis out of scope",
                    )
                )
    return results


def _hypothesis_checks(context: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for hyp in context.get("eda_hypotheses") or []:
        hyp_id = str(hyp.get("hypothesis_id") or "")
        if hyp.get("status") in {"confirmed", "rejected"} and not hyp.get("linked_finding_ids"):
            results.append(
                _finding(
                    check_id="CHK-hypothesis-no-evidence",
                    severity="required",
                    category="hypothesis_hygiene",
                    claim="Hypothesis disposition has no linked evidence finding",
                    evidence=[hyp_id],
                    recommendation="Link the confirming/rejecting finding or reopen the hypothesis",
                )
            )
        if hyp.get("needs_reevaluation"):
            results.append(
                _finding(
                    check_id="CHK-hypothesis-stale-evidence",
                    severity="required",
                    category="hypothesis_hygiene",
                    claim="Hypothesis depends on superseded evidence and needs reevaluation",
                    evidence=[hyp_id],
                    recommendation="Recompute or supersede the hypothesis disposition",
                )
            )
    return results


def _finding_validation_checks(context: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    hypotheses_by_id = {
        str(h.get("hypothesis_id") or ""): h for h in context.get("eda_hypotheses") or []
    }
    for finding in context.get("eda_findings") or []:
        finding_id = str(finding.get("finding_id") or "")
        internal = (finding.get("validation") or {}).get("internal") or {}
        external = (finding.get("validation") or {}).get("external") or {}
        if (
            finding.get("finding_type") != "readiness"
            and finding.get("disposition") == "confirmed"
            and internal.get("status") != "validated"
        ):
            results.append(
                _finding(
                    check_id="CHK-unvalidated-confirmed",
                    severity="required",
                    category="reproducibility_gap",
                    claim="Confirmed EDA finding is not internally validated",
                    evidence=[finding_id],
                    recommendation="Recompute the claim and attach evidence refs or weaken the finding",
                )
            )
        if external.get("status") == "unverified":
            caveat = str(finding.get("caveat") or "").lower()
            if finding.get("confidence") == "high" or "unverified against external evidence" not in caveat:
                results.append(
                    _finding(
                        check_id="CHK-overconfident-unverified",
                        severity="warning",
                        category="data_quality_caveat",
                        claim="Externally unverified finding is overconfident or missing the mandatory caveat",
                        evidence=[finding_id],
                        recommendation="Cap confidence and include the external-validation caveat",
                    )
                )
        hyp = hypotheses_by_id.get(str(finding.get("hypothesis_id") or ""))
        if _multiplicity_warning_needed(finding, hyp):
            results.append(
                _finding(
                    check_id="CHK-multiplicity",
                    severity="warning",
                    category="hypothesis_hygiene",
                    claim="Confirmed screened finding is missing multiplicity metadata or correction",
                    evidence=[finding_id or str((hyp or {}).get("hypothesis_id") or "")],
                    recommendation="Record screened_n, selection_rule, and fdr_bh, bonferroni, or holdout_confirmed",
                )
            )
    return results


def _artifact_checks(context: dict[str, Any]) -> list[dict[str, Any]]:
    artifact = context.get("artifact")
    sections = context.get("artifact_sections") or []
    if not artifact and not sections:
        return []
    results: list[dict[str, Any]] = []
    artifact_id = str((artifact or {}).get("id") or context.get("target_id") or "")
    validation_errors = (artifact or {}).get("validation_errors") or []
    if validation_errors:
        results.append(
            _finding(
                check_id="CHK-artifact-validation",
                severity="required",
                category="security_export_risk",
                claim="Artifact has unresolved validation errors",
                evidence=[artifact_id],
                recommendation="Republish after resolving artifact validation errors",
            )
        )
    for section in sections:
        kind = str(section.get("kind") or "")
        section_id = str(section.get("section_id") or artifact_id)
        section_schema = int(section.get("section_schema") or 0)
        if kind == "findings" and section_schema >= 2:
            for item in ((section.get("payload") or {}).get("items") or []):
                if isinstance(item, dict) and not item.get("finding_id"):
                    results.append(
                        _finding(
                            check_id="CHK-unsupported-claims",
                            severity="required",
                            category="unsupported_claim",
                            claim="Findings artifact section item lacks a finding_id evidence link",
                            evidence=[section_id],
                            recommendation="Cite an EDA finding_id or remove the unsupported claim",
                        )
                    )
                    break
        if kind == "chart" and (not section.get("title") or not section.get("caption")):
            results.append(
                _finding(
                    check_id="CHK-chart-metadata",
                    severity="warning",
                    category="misleading_visualization",
                    claim="Chart section is missing title or caption metadata",
                    evidence=[section_id],
                    recommendation="Add title and caption metadata that states the measure, grain, and caveat",
                )
            )
    return results


def _artifact_context(
    artifact_id: str,
    *,
    living_report: bool = False,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    try:
        from dataclaw_artifacts.store import latest_version, read_meta, read_source

        meta = read_meta(artifact_id)
        if living_report:
            from dataclaw_artifacts.compiler import compile_living_report

            html = compile_living_report(artifact_id)
        else:
            html = read_source(artifact_id, latest_version(artifact_id))
    except Exception:
        return None, []
    return meta, _extract_section_metadata(html)


def _extract_section_metadata(html: str) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    pattern = re.compile(r"<script[^>]*data-dc-section-meta[^>]*>(.*?)</script>", re.IGNORECASE | re.DOTALL)
    for match in pattern.finditer(html or ""):
        raw = match.group(1).replace("<\\/", "</")
        try:
            section = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(section, dict):
            sections.append(section)
    return sections


def _latest_readiness_finding(findings: list[dict[str, Any]]) -> dict[str, Any] | None:
    readiness = [f for f in findings if f.get("finding_type") == "readiness"]
    return readiness[-1] if readiness else None


def _readiness_status(finding: dict[str, Any]) -> str:
    summary = str(finding.get("summary") or "")
    try:
        parsed = json.loads(summary)
    except json.JSONDecodeError:
        return "unknown"
    return str(parsed.get("status") or "unknown") if isinstance(parsed, dict) else "unknown"


def _multiplicity_warning_needed(finding: dict[str, Any], hypothesis: dict[str, Any] | None) -> bool:
    if finding.get("disposition") != "confirmed":
        return False
    selection = finding.get("selection") if isinstance(finding.get("selection"), dict) else {}
    hyp_selection = hypothesis.get("selection") if isinstance((hypothesis or {}).get("selection"), dict) else {}
    source = str((hypothesis or {}).get("source") or "")
    effective = selection or hyp_selection or {}
    try:
        screened_n = int(effective.get("screened_n") or 0)
    except (TypeError, ValueError):
        screened_n = 0
    correction = str(effective.get("correction") or "none")
    if screened_n > 5 and correction == "none":
        return True
    if source == "data_signal" and not effective:
        return True
    return False


def _finding(
    *,
    check_id: str,
    severity: str,
    category: str,
    claim: str,
    evidence: list[str],
    recommendation: str,
) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "source": f"checklist:{check_id}",
        "severity": severity,
        "category": category,
        "claim": claim,
        "evidence": [str(item) for item in evidence if str(item).strip()],
        "recommendation": recommendation,
        "status": "open",
    }
