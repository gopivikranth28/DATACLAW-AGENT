"""Tests for the analysis review lifecycle."""

from __future__ import annotations

import json

import pytest

import dataclaw.config.paths as paths
from dataclaw.plugins.loader import discover_plugins
from dataclaw_analysis_review.tools import ReviewFindingAcceptanceGuardrail
from dataclaw_analysis_review.hooks import auto_review_completed_steps_hook
from dataclaw_analysis_review.tools import (
    get_review_gate,
    list_review_findings,
    request_analysis_review,
    resolve_review_finding,
)
from dataclaw_eda.tools import record_eda_finding, summarize_eda_readiness
from dataclaw_plans.gates import get_plan_gates
from dataclaw_plans.tools import get_plan, propose_plan, update_plan


@pytest.fixture(autouse=True)
def tmp_home(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DATACLAW_HOME", tmp_path)
    return tmp_path


async def _high_risk_plan(session_id: str = "sess-1") -> tuple[str, str]:
    proposed = await propose_plan(
        name="Model plan",
        description="Train and export a model",
        steps=[{"name": "Model", "description": "Train model and export results"}],
        session_id=session_id,
    )
    plan = await get_plan(proposal_id=proposed["proposal_id"])
    return proposed["proposal_id"], plan["steps"][0]["plan_step_id"]


def test_analysis_review_plugin_is_discoverable():
    assert "dataclaw-analysis-review" in {plugin.name for plugin in discover_plugins()}


def test_review_finding_acceptance_requires_user_approval():
    guardrail = ReviewFindingAcceptanceGuardrail()

    verdict = guardrail.evaluate(
        {
            "call_id": "call-1",
            "tool_name": "resolve_review_finding",
            "tool_input": {
                "finding_id": "rvf-test",
                "status": "accepted_with_rationale",
                "rationale": "Proceed anyway",
            },
        },
        {},
    )
    assert verdict is not None
    assert verdict.mode == "user_approval"

    assert guardrail.evaluate(
        {
            "call_id": "call-2",
            "tool_name": "resolve_review_finding",
            "tool_input": {"finding_id": "rvf-test", "status": "resolved"},
        },
        {},
    ) is None


@pytest.mark.asyncio
async def test_review_finding_blocks_ready_for_validation():
    proposal_id, step_id = await _high_risk_plan()
    await update_plan(
        proposal_id=proposal_id,
        step_patches=[{"plan_step_id": step_id, "status": "completed"}],
        session_id="sess-1",
    )

    review = await request_analysis_review(
        scope="plan_step",
        target_id=step_id,
        proposal_id=proposal_id,
        session_id="sess-1",
    )

    assert review["success"] is True
    assert review["gate"]["gate"] == "fail"
    assert review["findings_summary"]["by_severity"]["required"] == 1
    ready = await update_plan(
        proposal_id=proposal_id,
        step_patches=[{"plan_step_id": step_id, "ready_for_validation": True}],
        session_id="sess-1",
    )
    assert ready["success"] is False
    assert ready["error"]["code"] == "gate_blocked"
    assert ready["error"]["blocking_gates"][0]["name"] == "analysis_review"


@pytest.mark.asyncio
async def test_resolving_review_finding_clears_plan_gate():
    proposal_id, step_id = await _high_risk_plan()
    await update_plan(
        proposal_id=proposal_id,
        step_patches=[{"plan_step_id": step_id, "status": "completed"}],
        session_id="sess-1",
    )
    review = await request_analysis_review(
        scope="plan_step",
        target_id=step_id,
        proposal_id=proposal_id,
        session_id="sess-1",
    )

    resolved = await resolve_review_finding(
        finding_id=review["finding_ids"][0],
        status="resolved",
        rationale="Recorded a no-material-findings caveat",
        session_id="sess-1",
    )

    assert resolved["success"] is True
    assert resolved["gate"]["gate"] == "pass"
    ready = await update_plan(
        proposal_id=proposal_id,
        step_patches=[{"plan_step_id": step_id, "ready_for_validation": True}],
        session_id="sess-1",
    )
    assert ready["success"] is True


@pytest.mark.asyncio
async def test_ready_readiness_finding_does_not_block_review():
    proposal_id, step_id = await _high_risk_plan()
    for finding_type, check in [("data_quality", "data_quality"), ("missingness", "missingness")]:
        await record_eda_finding(
            title=f"{check} checked",
            finding_type=finding_type,
            summary=f"{check} complete",
            evidence={"kind": "notebook_cell", "cell_id": f"c-{check}", "source_sha256": f"hash-{check}"},
            dataset_id="ds",
            validation={
                "internal": {
                    "status": "validated",
                    "method": "recomputed",
                    "evidence_refs": [f"notebook_cell:c-{check}"],
                },
                "external": {"status": "validated", "basis": "domain_prior", "note": "plausible"},
            },
            covers_checks=[check],
            proposal_id=proposal_id,
            plan_step_id=step_id,
            session_id="sess-1",
        )
    readiness = await summarize_eda_readiness(
        dataset_id="ds",
        purpose="query",
        proposal_id=proposal_id,
        plan_step_id=step_id,
        session_id="sess-1",
    )
    assert readiness["status"] == "ready"
    await update_plan(
        proposal_id=proposal_id,
        step_patches=[{"plan_step_id": step_id, "status": "completed"}],
        session_id="sess-1",
    )

    review = await request_analysis_review(
        scope="plan_step",
        target_id=step_id,
        proposal_id=proposal_id,
        session_id="sess-1",
    )

    assert review["gate"]["gate"] == "pass"
    assert review["finding_ids"] == []


@pytest.mark.asyncio
async def test_unknown_plan_step_review_is_rejected_without_gate_write():
    proposal_id, _step_id = await _high_risk_plan()

    review = await request_analysis_review(
        scope="plan_step",
        target_id="step-deadbeef",
        proposal_id=proposal_id,
        session_id="sess-1",
    )

    assert review["success"] is False
    assert review["error"]["code"] == "unknown_review_target"
    plan = await get_plan(proposal_id=proposal_id)
    assert plan["steps"][0].get("gates", {}) == {}


@pytest.mark.asyncio
async def test_review_rerun_auto_resolves_disappeared_checklist_findings():
    proposal_id, step_id = await _high_risk_plan()
    await update_plan(
        proposal_id=proposal_id,
        step_patches=[{"plan_step_id": step_id, "status": "completed"}],
        session_id="sess-1",
    )
    first = await request_analysis_review(
        scope="plan_step",
        target_id=step_id,
        proposal_id=proposal_id,
        session_id="sess-1",
    )
    await record_eda_finding(
        title="No material findings",
        finding_type="caveat",
        summary="No material findings were produced in this draft step",
        evidence={"kind": "interpretive_note", "text": "No material findings"},
        dataset_id="ds",
        covers_checks=["no_material_findings"],
        proposal_id=proposal_id,
        plan_step_id=step_id,
        session_id="sess-1",
    )

    second = await request_analysis_review(
        scope="plan_step",
        target_id=step_id,
        proposal_id=proposal_id,
        session_id="sess-1",
    )
    findings = await list_review_findings(session_id="sess-1", scope="plan_step", target_id=step_id)

    assert second["gate"]["gate"] == "pass"
    assert second["finding_ids"] == []
    assert any(
        finding["finding_id"] == first["finding_ids"][0] and finding["status"] == "resolved"
        for finding in findings["findings"]
    )


@pytest.mark.asyncio
async def test_subagent_required_scope_stays_unknown_after_checklist_only_review():
    proposal_id, step_id = await _high_risk_plan()
    await update_plan(
        proposal_id=proposal_id,
        step_patches=[{"plan_step_id": step_id, "status": "completed"}],
        session_id="sess-1",
    )
    await record_eda_finding(
        title="No material findings",
        finding_type="caveat",
        summary="No material findings were produced in this draft step",
        evidence={"kind": "interpretive_note", "text": "No material findings"},
        dataset_id="ds",
        covers_checks=["no_material_findings"],
        proposal_id=proposal_id,
        plan_step_id=step_id,
        session_id="sess-1",
    )

    review = await request_analysis_review(
        scope="plan_step",
        target_id=step_id,
        proposal_id=proposal_id,
        session_id="sess-1",
        require_subagent=True,
    )

    assert review["gate"]["gate"] == "unknown"
    ready = await update_plan(
        proposal_id=proposal_id,
        step_patches=[{"plan_step_id": step_id, "ready_for_validation": True}],
        session_id="sess-1",
    )
    assert ready["success"] is False
    assert ready["error"]["blocking_gates"][0]["status"] == "unknown"


@pytest.mark.asyncio
async def test_auto_review_hook_runs_on_completed_high_risk_step():
    proposal_id, step_id = await _high_risk_plan()
    update = await update_plan(
        proposal_id=proposal_id,
        step_patches=[{"plan_step_id": step_id, "status": "completed"}],
        session_id="sess-1",
    )

    await auto_review_completed_steps_hook(
        {
            "session_id": "sess-1",
            "tool_results": [
                {
                    "tool_name": "update_plan",
                    "tool_input": {
                        "proposal_id": proposal_id,
                        "step_patches": [{"plan_step_id": step_id, "status": "completed"}],
                    },
                    "result": update,
                    "is_error": False,
                }
            ],
        }
    )

    gate = await get_review_gate(scope="plan_step", target_id=step_id, session_id="sess-1")
    plan_gates = await get_plan_gates(proposal_id)
    assert gate["gate"] == "fail"
    assert plan_gates["steps"][0]["gates"]["analysis_review"]["status"] == "fail"


@pytest.mark.asyncio
async def test_auto_review_hook_accepts_content_payload_shape():
    proposal_id, step_id = await _high_risk_plan()
    update = await update_plan(
        proposal_id=proposal_id,
        step_patches=[{"plan_step_id": step_id, "status": "completed"}],
        session_id="sess-1",
    )

    await auto_review_completed_steps_hook(
        {
            "session_id": "sess-1",
            "tool_results": [
                {
                    "tool_name": "update_plan",
                    "tool_input": {
                        "proposal_id": proposal_id,
                        "step_patches": [{"plan_step_id": step_id, "status": "completed"}],
                    },
                    "content": json.dumps(update),
                    "is_error": False,
                }
            ],
        }
    )

    gate = await get_review_gate(scope="plan_step", target_id=step_id, session_id="sess-1")
    assert gate["gate"] == "fail"
