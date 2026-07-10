"""Exercises the shared PRD acceptance fixtures (structured-EDA PRD FR-38)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import dataclaw.config.paths as paths
from dataclaw.api.app import create_app

from tests.prd_fixtures import (
    CANONICAL_STRUCTURED_EDA_TOOLS,
    assert_openclaw_tool_aliases,
    assert_plan_step_identity,
    assert_preview_cap,
)


def test_openclaw_manifest_carries_canonical_tools_with_identical_schemas(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DATACLAW_HOME", tmp_path)
    with TestClient(create_app()) as client:
        listing = client.get("/api/tools").json()
    assert listing["tools"], "live registry returned no tools"
    assert_openclaw_tool_aliases(listing["tools"], tmp_path / "openclaw-plugin")


def test_openclaw_alias_fixture_detects_missing_canonical_tool(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DATACLAW_HOME", tmp_path)
    with TestClient(create_app()) as client:
        tools = client.get("/api/tools").json()["tools"]
    depleted = [t for t in tools if t["name"] != CANONICAL_STRUCTURED_EDA_TOOLS[0]]
    with pytest.raises(AssertionError, match="canonical tools missing"):
        assert_openclaw_tool_aliases(depleted, tmp_path / "depleted-plugin")


@pytest.mark.asyncio
async def test_plan_step_identity_and_preview_cap_on_real_records(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DATACLAW_HOME", tmp_path)
    from dataclaw_eda.store import fold_findings
    from dataclaw_eda.tools import record_eda_finding
    from dataclaw_plans.tools import get_plan, propose_plan

    session_id = "sess-fixture"
    proposed = await propose_plan(
        name="EDA plan",
        description="Explore the dataset",
        steps=[{"name": "EDA", "description": "Exploratory data analysis"}],
        session_id=session_id,
    )
    plan = await get_plan(proposal_id=proposed["proposal_id"])
    step_id = plan["steps"][0]["plan_step_id"]

    oversized_rows = [{"col": "x" * 100, "n": i} for i in range(500)]
    recorded = await record_eda_finding(
        title="Distribution of events",
        finding_type="distribution",
        summary="Events are right-skewed",
        evidence=[{"kind": "inline_summary", "summary": oversized_rows}],
        dataset_id="ds-1",
        session_id=session_id,
        plan_step_id=step_id,
    )
    assert recorded.get("finding_id")

    findings = fold_findings(session_id)
    assert_plan_step_identity(findings)
    for finding in findings:
        assert_preview_cap(finding.get("evidence") or [])

    with pytest.raises(AssertionError):
        assert_plan_step_identity([{"finding_id": "f-1", "plan_step_id": "My EDA Step"}])
