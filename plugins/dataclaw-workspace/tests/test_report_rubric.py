"""Tests for the report rubric — the versioned config behind the quality gate."""

import copy

import pytest

from dataclaw_workspace import report_renderer
from dataclaw_workspace.config import WorkspaceConfig
from dataclaw_workspace.report_rubric import (
    RubricError,
    _validate,
    live_criterion_ids,
    load_report_rubric,
    rubric_criteria,
    rubric_thresholds,
    rubric_version,
)
from dataclaw_workspace.tools import report_add_section

import dataclaw.config.paths as paths


@pytest.fixture(autouse=True)
def tmp_workspaces(tmp_path, monkeypatch):
    ws_dir = tmp_path / "workspaces"
    ws_dir.mkdir()
    monkeypatch.setattr(paths, "DATACLAW_HOME", tmp_path)
    return ws_dir


@pytest.fixture
def cfg():
    return WorkspaceConfig()


# The gate checks implemented in analyze_report_quality, by criterion id. If a
# rubric criterion is flipped to `live` without adding an evaluator (or vice
# versa), this set stops matching and the test fails — that is the point.
IMPLEMENTED_GATE_CHECKS = {
    "evidence_unresolved",
    "oversized_report",
    "unstructured_report",
    "stale_installed_skills",
    "consecutive_plain_charts",
    "chart_dump",
    "plain_chart_overuse",
    "missing_insight_sections",
    "missing_primary_insights",
    "missing_interactive_explorer",
    "missing_table_caption",
    "unsourced_claim",
    "chart_interpretation_missing_evidence",
    "chart_missing_conclusion",
    "missing_narrative_answer",
    "bare_bullet_findings",
    "missing_section_dek",
    "unpaired_insights",
    "chart_theme_defeated",
    "runtime_smoke_failed",
    "not_self_contained",
    "contrast_below_aa",
}


def test_rubric_loads_and_matches_implemented_checks():
    rubric = load_report_rubric()
    assert rubric_version() == 3
    assert set(live_criterion_ids()) == IMPLEMENTED_GATE_CHECKS
    for value in rubric_thresholds().values():
        assert isinstance(value, int)
    # The payload cap constant is sourced from the rubric, not hard-coded.
    assert report_renderer.REPORT_QUALITY_MAX_BYTES == rubric_thresholds()["max_payload_bytes"]
    axes = {criterion["axis"] for criterion in rubric["criteria"]}
    assert axes == {"rigor", "narrative", "integrity"}


def test_rubric_rename_is_recorded():
    criteria = rubric_criteria()
    assert criteria["unsourced_claim"]["replaces"] == "missing_evidence_ids"
    # The original presence-only check remains a warning while v3 introduces
    # registered-target resolution at warning severity.
    assert criteria["unsourced_claim"]["severity"] == "warn"
    assert criteria["evidence_unresolved"]["status"] == "live"
    assert criteria["evidence_unresolved"]["severity"] == "warn"
    assert criteria["evidence_unresolved"]["since_version"] == 3


def test_validate_rejects_malformed_rubrics():
    rubric = copy.deepcopy(load_report_rubric())

    duplicated = copy.deepcopy(rubric)
    duplicated["criteria"].append(dict(duplicated["criteria"][0]))
    with pytest.raises(RubricError, match="duplicate criterion id"):
        _validate(duplicated)

    bad_severity = copy.deepcopy(rubric)
    bad_severity["criteria"][0]["severity"] = "catastrophic"
    with pytest.raises(RubricError, match="invalid severity"):
        _validate(bad_severity)

    bad_status = copy.deepcopy(rubric)
    bad_status["criteria"][0]["status"] = "someday"
    with pytest.raises(RubricError, match="invalid status"):
        _validate(bad_status)

    missing_field = copy.deepcopy(rubric)
    missing_field["criteria"][0].pop("remediation")
    with pytest.raises(RubricError, match="missing fields"):
        _validate(missing_field)

    with pytest.raises(RubricError, match="rubric_version"):
        _validate({"thresholds": {}, "criteria": []})


async def test_gate_result_cites_rubric_version(cfg):
    result = await report_add_section(
        cfg=cfg,
        section_type="callout",
        report_path="reports/rubric-version.html",
        quality_gate="warn",
        data={"title": "Note", "text": "Just one section."},
    )
    assert result["quality"]["rubric_version"] == 3


def test_gate_rejects_report_without_typed_section_metadata():
    quality = report_renderer.analyze_report_quality("<html><body><h1>Raw report</h1></body></html>")
    assert quality["status"] == "fail"
    assert "unstructured_report" in {warning["code"] for warning in quality["warnings"]}


def test_evidence_registry_resolves_only_registered_targets():
    inputs = {
        "report_goal": "Explain the result",
        "insights": [{"title": "Result", "detail": "A completed finding.", "finding_id": "finding-1"}],
        "analyses": [{
            "title": "Supporting chart",
            "figure": {"data": [{"x": [1], "y": [2]}]},
            "interpretation": "The aggregate supports the reported result.",
            "evidence": [{"kind": "notebook_cell", "ref": "cell-1"}],
        }],
        "requirements": {"evidence_registry": {"targets": [{"id": "cell-1", "kind": "notebook_cell", "present": True}]}},
    }
    storyboard = report_renderer.design_report_storyboard(**inputs)
    storyboard, _ = report_renderer.critique_report_storyboard(storyboard)
    resolved = report_renderer.analyze_report_quality(report_renderer.render_report_from_storyboard(storyboard))
    assert "evidence_unresolved" not in {warning["code"] for warning in resolved["warnings"]}

    inputs["requirements"] = {}
    unresolved_storyboard = report_renderer.design_report_storyboard(**inputs)
    unresolved_storyboard, _ = report_renderer.critique_report_storyboard(unresolved_storyboard)
    unresolved = report_renderer.analyze_report_quality(report_renderer.render_report_from_storyboard(unresolved_storyboard))
    assert "evidence_unresolved" in {warning["code"] for warning in unresolved["warnings"]}


def test_critique_adds_safe_context_without_minting_evidence():
    storyboard = {
        "section_plan": [
            {
                "section_type": "interactive_table",
                "data": {"title": "Rows", "columns": ["team"], "rows": [{"team": "A"}]},
            },
            {
                "section_type": "insight_grid",
                "data": {"title": "Findings", "items": [{"title": "Claim", "detail": "No source supplied."}]},
            },
        ]
    }
    critiqued, critique = report_renderer.critique_report_storyboard(storyboard)
    table = critiqued["section_plan"][0]["data"]
    finding = critiqued["section_plan"][1]["data"]["items"][0]
    assert table["caption"]
    assert finding["caveat"] == "Evidence reference was not supplied in the source material."
    assert "finding_id" not in finding
    assert critique["passes"] <= 2
    assert critique["guardrail"].startswith("No evidence identifiers")


def test_static_runtime_and_contrast_checks_detect_broken_shell_wiring():
    storyboard = report_renderer.design_report_storyboard(
        report_goal="Explain the result",
        insights=[{"title": "Result", "detail": "A completed finding.", "finding_id": "finding-1"}],
    )
    storyboard, _ = report_renderer.critique_report_storyboard(storyboard)
    doc = report_renderer.render_report_from_storyboard(storyboard)

    broken_runtime = report_renderer.analyze_report_quality(doc.replace("data-dc-report-shell-script", "data-dc-runtime-missing"))
    assert "runtime_smoke_failed" in {warning["code"] for warning in broken_runtime["warnings"]}

    broken_contrast = report_renderer.analyze_report_quality(doc.replace("--dc-muted: #667085", "--dc-muted: #eeeeee", 1))
    assert "contrast_below_aa" in {warning["code"] for warning in broken_contrast["warnings"]}


async def test_unsourced_claim_replaces_missing_evidence_ids(cfg):
    result = await report_add_section(
        cfg=cfg,
        section_type="findings",
        report_path="reports/unsourced.html",
        quality_gate="warn",
        data={
            "title": "Findings",
            "items": [{"title": "Claim without a trace", "detail": "No evidence ref."}],
        },
    )
    warnings = {w["code"]: w for w in result["quality"]["warnings"]}
    assert "unsourced_claim" in warnings
    assert "missing_evidence_ids" not in warnings
    entry = warnings["unsourced_claim"]
    assert entry["severity"] == "warn"
    assert entry["replaces"] == "missing_evidence_ids"


async def test_deferred_criteria_are_never_emitted(cfg):
    report_path = "reports/deferred-check.html"
    result = None
    for i in range(4):
        result = await report_add_section(
            cfg=cfg,
            section_type="chart",
            report_path=report_path,
            quality_gate="warn",
            data={"title": f"Chart {i}", "figure": {"data": [{"x": [1], "y": [i]}]}},
        )
    codes = {w["code"] for w in result["quality"]["warnings"]}
    assert codes
    assert codes <= set(live_criterion_ids())


def test_gate_check_without_rubric_criterion_raises(monkeypatch):
    monkeypatch.setattr(report_renderer, "rubric_criteria", lambda: {})
    with pytest.raises(KeyError, match="no criterion in the report rubric"):
        report_renderer.analyze_report_quality(
            "<html><body></body></html>",
            stale_skills=[{"skill": "example", "reason": "stale"}],
        )


def test_storyboard_quality_plan_derives_from_rubric():
    storyboard = report_renderer.design_report_storyboard(
        report_goal="Test goal",
        insights=[{"title": "An insight", "detail": "Detail", "finding_id": "f1"}],
        analyses=[],
        audience="ds",
        title="T",
        requirements={},
    )
    plan = storyboard["quality_plan"]
    assert plan["rubric_version"] == 3
    assert plan["checks"] == live_criterion_ids()
