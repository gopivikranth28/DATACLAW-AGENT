"""Tests for structured EDA ledger tools."""

from __future__ import annotations

import pytest

import dataclaw.config.paths as paths
from dataclaw_eda.store import find_hypothesis, fold_findings
from dataclaw_eda.tools import (
    propose_eda_hypotheses,
    record_eda_finding,
    summarize_eda_readiness,
    supersede_eda_finding,
    update_eda_hypothesis,
)


@pytest.fixture(autouse=True)
def tmp_home(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DATACLAW_HOME", tmp_path)
    return tmp_path


def _validated_internal(cell_id: str = "cell-a") -> dict:
    return {
        "internal": {
            "status": "validated",
            "method": "recomputed",
            "evidence_refs": [f"notebook_cell:{cell_id}"],
        },
        "external": {"status": "validated", "basis": "domain_prior", "note": "plausible"},
    }


@pytest.mark.asyncio
async def test_hypothesis_batch_caps_are_enforced():
    too_many = [
        {"statement": f"H{i}", "rationale": "r", "source": "user_goal", "priority": "low"}
        for i in range(8)
    ]
    result = await propose_eda_hypotheses(hypotheses=too_many, dataset_id="ds")
    assert result["success"] is False
    assert result["error"]["code"] == "hypothesis_batch_too_large"

    too_many_high = [
        {"statement": f"H{i}", "rationale": "r", "source": "user_goal", "priority": "high"}
        for i in range(4)
    ]
    result = await propose_eda_hypotheses(hypotheses=too_many_high, dataset_id="ds")
    assert result["success"] is False
    assert result["error"]["code"] == "too_many_high_priority_hypotheses"


@pytest.mark.asyncio
async def test_data_signal_requires_rationale():
    result = await propose_eda_hypotheses(
        hypotheses=[{"statement": "Spike in churn", "rationale": "", "source": "data_signal"}],
        dataset_id="ds",
    )
    assert result["success"] is False
    assert result["error"]["code"] == "data_signal_requires_rationale"


@pytest.mark.asyncio
async def test_high_confidence_requires_internal_validation_evidence():
    result = await record_eda_finding(
        title="Pattern",
        finding_type="distribution",
        summary="A pattern",
        evidence={"kind": "interpretive_note", "text": "not enough"},
        dataset_id="ds",
        confidence="high",
        validation={"internal": {"status": "not_checked"}},
    )
    assert result["success"] is False
    assert result["error"]["code"] == "high_confidence_requires_internal_validation"


@pytest.mark.asyncio
async def test_validated_internal_status_requires_evidence_refs():
    result = await record_eda_finding(
        title="Pattern",
        finding_type="distribution",
        summary="A pattern",
        evidence={"kind": "interpretive_note", "text": ""},
        dataset_id="ds",
        validation={"internal": {"status": "validated", "method": "self report", "evidence_refs": []}},
    )
    assert result["success"] is False
    assert result["error"]["code"] == "validated_requires_evidence_refs"


@pytest.mark.asyncio
async def test_external_unverified_caps_confidence_and_adds_caveat():
    result = await record_eda_finding(
        title="Distribution",
        finding_type="distribution",
        summary="Distribution is skewed",
        evidence={"kind": "notebook_cell", "cell_id": "abc", "source_sha256": "hash"},
        dataset_id="ds",
        confidence="medium",
        validation={
            "internal": {"status": "validated", "method": "describe", "evidence_refs": ["notebook_cell:abc"]},
            "external": {"status": "unverified", "basis": "none", "note": ""},
        },
    )
    assert result["success"] is True
    finding = result["finding"]
    assert finding["confidence"] == "medium"
    assert "unverified against external evidence" in finding["caveat"]


@pytest.mark.asyncio
async def test_record_finding_can_confirm_hypothesis_atomically():
    proposed = await propose_eda_hypotheses(
        hypotheses=[
            {
                "statement": "Revenue is negative for refunds",
                "rationale": "Money fields may include reversals",
                "source": "domain_prior",
                "priority": "medium",
                "covers_checks": ["data_quality"],
            }
        ],
        dataset_id="ds",
    )
    hyp_id = proposed["hypothesis_ids"][0]
    result = await record_eda_finding(
        title="Negative revenue explained",
        finding_type="data_quality",
        summary="Negative revenue rows align with refund events",
        evidence={"kind": "notebook_cell", "cell_id": "c1", "source_sha256": "hash1"},
        dataset_id="ds",
        hypothesis_id=hyp_id,
        hypothesis_status="confirmed",
        disposition="confirmed",
        confidence="high",
        validation=_validated_internal("c1"),
        covers_checks=["data_quality"],
    )

    assert result["success"] is True
    hyp = find_hypothesis(hyp_id)
    assert hyp is not None
    assert hyp["status"] == "confirmed"
    assert result["finding_id"] in hyp["linked_finding_ids"]


@pytest.mark.asyncio
async def test_rejected_hypothesis_auto_sets_finding_type():
    proposed = await propose_eda_hypotheses(
        hypotheses=[{"statement": "All users churn", "rationale": "Check target", "source": "user_goal", "priority": "low"}],
        dataset_id="ds",
    )
    hyp_id = proposed["hypothesis_ids"][0]
    result = await record_eda_finding(
        title="Not all users churn",
        finding_type="distribution",
        summary="The churn target has both classes",
        evidence={"kind": "notebook_cell", "cell_id": "c2", "source_sha256": "hash2"},
        dataset_id="ds",
        hypothesis_id=hyp_id,
        hypothesis_status="rejected",
        validation=_validated_internal("c2"),
    )

    assert result["success"] is True
    assert result["finding"]["finding_type"] == "rejected_hypothesis"
    assert find_hypothesis(hyp_id)["status"] == "rejected"


@pytest.mark.asyncio
async def test_rejected_hypothesis_covers_required_check_in_readiness():
    proposed = await propose_eda_hypotheses(
        hypotheses=[
            {
                "statement": "No leakage fields are present",
                "rationale": "Modeling-readiness check",
                "source": "mode_expected_risk",
                "priority": "high",
                "covers_checks": ["leakage_risk"],
            }
        ],
        dataset_id="ds",
    )
    hyp_id = proposed["hypothesis_ids"][0]
    await record_eda_finding(
        title="Leakage hypothesis rejected",
        finding_type="distribution",
        summary="No post-outcome fields were found",
        evidence={"kind": "notebook_cell", "cell_id": "c-leak", "source_sha256": "hash-leak"},
        dataset_id="ds",
        hypothesis_id=hyp_id,
        hypothesis_status="rejected",
        validation=_validated_internal("c-leak"),
    )
    for finding_type, check in [
        ("data_quality", "data_quality"),
        ("missingness", "missingness"),
        ("distribution", "distribution"),
    ]:
        await record_eda_finding(
            title=f"{check} checked",
            finding_type=finding_type,
            summary=f"{check} complete",
            evidence={"kind": "notebook_cell", "cell_id": f"cell-{check}", "source_sha256": f"hash-{check}"},
            dataset_id="ds",
            validation=_validated_internal(f"cell-{check}"),
            covers_checks=[check],
        )

    verdict = await summarize_eda_readiness(dataset_id="ds", purpose="modeling")
    assert "leakage_risk" not in verdict["missing_checks"]


@pytest.mark.asyncio
async def test_supersede_flags_linked_hypothesis_for_reevaluation():
    proposed = await propose_eda_hypotheses(
        hypotheses=[{"statement": "Missingness is segment-specific", "rationale": "Data-quality risk", "source": "mode_expected_risk", "priority": "high"}],
        dataset_id="ds",
    )
    hyp_id = proposed["hypothesis_ids"][0]
    finding = await record_eda_finding(
        title="Missingness differs by segment",
        finding_type="missingness",
        summary="Segment A has higher missingness",
        evidence={"kind": "notebook_cell", "cell_id": "c3", "source_sha256": "hash3"},
        dataset_id="ds",
        hypothesis_id=hyp_id,
        hypothesis_status="confirmed",
        disposition="confirmed",
        confidence="high",
        validation=_validated_internal("c3"),
        covers_checks=["missingness"],
    )
    result = await supersede_eda_finding(finding_id=finding["finding_id"], reason="Recomputed after filter")

    assert result["success"] is True
    hyp = find_hypothesis(hyp_id)
    assert hyp["needs_reevaluation"] is True


@pytest.mark.asyncio
async def test_modeling_readiness_blocks_on_unresolved_domain_input():
    proposed = await propose_eda_hypotheses(
        hypotheses=[
            {
                "statement": "Post-outcome fields may leak target information",
                "rationale": "Modeling-readiness leakage risk",
                "source": "mode_expected_risk",
                "priority": "high",
                "covers_checks": ["leakage_risk"],
            }
        ],
        dataset_id="ds",
    )
    hyp_id = proposed["hypothesis_ids"][0]
    await update_eda_hypothesis(
        hypothesis_id=hyp_id,
        status="unresolved_needs_domain_input",
        disposition_reason="Which timestamp defines feature availability?",
    )
    for finding_type, check in [
        ("data_quality", "data_quality"),
        ("missingness", "missingness"),
        ("distribution", "distribution"),
    ]:
        result = await record_eda_finding(
            title=f"{check} checked",
            finding_type=finding_type,
            summary=f"{check} complete",
            evidence={"kind": "notebook_cell", "cell_id": f"cell-{check}", "source_sha256": f"hash-{check}"},
            dataset_id="ds",
            validation=_validated_internal(f"cell-{check}"),
            covers_checks=[check],
        )
        assert result["success"] is True

    verdict = await summarize_eda_readiness(dataset_id="ds", purpose="modeling", mode="modeling-readiness")
    assert verdict["success"] is True
    assert verdict["status"] == "blocked"
    assert any(blocker["kind"] == "domain_input" for blocker in verdict["blockers"])
    assert any(f["finding_type"] == "readiness" for f in fold_findings())
