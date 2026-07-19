"""Regression tests for notebook-backed EDA evidence defaults."""

from __future__ import annotations

import json

import pytest

import dataclaw.config.paths as paths
from dataclaw_eda.evidence import source_sha256
from dataclaw_eda.hooks import eda_evidence_hook
from dataclaw_eda.tools import record_eda_finding


@pytest.fixture(autouse=True)
def tmp_home(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DATACLAW_HOME", tmp_path)
    return tmp_path


@pytest.mark.asyncio
async def test_read_cell_hook_supplies_validated_finding_anchor_and_derives_ref():
    session_id = "read-cell-anchor-session"
    source = "summary = df.groupby('segment').size()"
    cell_id = "cell-segment-summary"
    await eda_evidence_hook({
        "session_id": session_id,
        "tool_results": [{
            "tool_name": "dataclaw_read_cell",
            "is_error": False,
            "result": json.dumps({
                "cell_id": cell_id,
                "cell_index": 7,
                "source": source,
                "source_sha256": source_sha256(source),
            }),
        }],
    })

    recorded = await record_eda_finding(
        title="Segment coverage differs",
        finding_type="segment_difference",
        summary="The supplied summary shows differing segment coverage.",
        evidence={"kind": "interpretive_note", "text": "Review the completed segment summary."},
        dataset_id="dataset-1",
        session_id=session_id,
        validation={
            "internal": {"status": "validated", "method": "recomputed", "evidence_refs": []},
            "external": {"status": "not_checked"},
        },
    )

    assert recorded["success"] is True
    finding = recorded["finding"]
    assert finding["evidence"][0] == {
        "kind": "notebook_cell",
        "cell_id": cell_id,
        "cell_index": 7,
        "source_sha256": source_sha256(source),
        "stale": False,
    }
    assert finding["validation"]["internal"]["evidence_refs"] == [f"notebook_cell:{cell_id}"]


@pytest.mark.asyncio
async def test_validated_missing_anchor_returns_actionable_evidence_diagnostic():
    recorded = await record_eda_finding(
        title="Unanchored validation",
        finding_type="distribution",
        summary="No non-prose evidence was attached.",
        evidence={"kind": "interpretive_note", "text": "Only prose is available."},
        dataset_id="dataset-1",
        session_id="no-anchor-session",
        validation={"internal": {"status": "validated", "evidence_refs": []}},
    )

    assert recorded["success"] is False
    assert recorded["error"]["code"] == "validated_requires_evidence_refs"
    assert recorded["error"]["expected_refs"] == []
    assert "notebook_cell:<cell_id>" in recorded["error"]["hint"]
