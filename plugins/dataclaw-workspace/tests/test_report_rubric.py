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


# Checks implemented by the quality, typed-section, and design/publish gates.
# If a rubric criterion is flipped to `live` without an evaluator (or vice
# versa), this set stops matching and the test fails — that is the point.
IMPLEMENTED_GATE_CHECKS = {
    "evidence_unresolved",
    "oversized_report",
    "unstructured_report",
    "stale_installed_skills",
    "missing_insight_sections",
    "missing_primary_insights",
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
    "visual_semantic_review",
    "creative_evidence_ledger_missing",
    "authored_evidence_coverage_missing",
    "authored_evidence_review_failed",
    "display_fact_coverage",
    "missing_methodology",
    "missing_data_quality",
    "missing_uncertainty",
    "missing_recipe",
    "plaintext_where_component_warranted",
    "contrast_below_aa",
    "advanced_visual_semantics",
    "handcrafted_claim_source_missing",
}


def test_rubric_loads_and_matches_implemented_checks():
    rubric = load_report_rubric()
    assert rubric_version() == 15
    assert set(live_criterion_ids()) == IMPLEMENTED_GATE_CHECKS
    for value in rubric_thresholds().values():
        assert isinstance(value, int)
    # The payload cap constant is sourced from the rubric, not hard-coded.
    assert report_renderer.REPORT_QUALITY_MAX_BYTES == rubric_thresholds()["max_payload_bytes"]
    axes = {criterion["axis"] for criterion in rubric["criteria"]}
    assert axes == {"rigor", "narrative", "integrity"}


def test_stale_skill_freshness_is_advisory_not_publish_blocking():
    criterion = rubric_criteria()["stale_installed_skills"]
    assert criterion["severity"] == "warn"
    assert criterion["on_fail"] == "warn"

    doc = (
        '<html data-dc-authored-document="true"><body>'
        '<script type="application/json" data-dc-section-meta>'
        '{"section_schema":3,"kind":"narrative_band","section_id":"authored",'
        '"title":"Report","caption":"Answer","payload":{"authored":true}}'
        '</script></body></html>'
    )
    quality = report_renderer.analyze_report_quality(
        doc,
        stale_skills=[{"skill": "visualization", "reason": "library changed"}],
    )
    stale = next(item for item in quality["warnings"] if item["code"] == "stale_installed_skills")
    assert stale["severity"] == "warn"
    assert quality["status"] != "fail"


def test_editorial_heuristics_are_advisory_but_evidence_and_integrity_stay_strict():
    criteria = rubric_criteria()
    advisory = {
        "missing_methodology",
        "missing_primary_insights",
        "missing_insight_sections",
    }
    strict = {
        "handcrafted_claim_source_missing",
        "advanced_visual_semantics",
        "unstructured_report",
        "oversized_report",
        "creative_evidence_ledger_missing",
        "authored_evidence_coverage_missing",
        "authored_evidence_review_failed",
    }

    assert all(criteria[criterion]["severity"] == "warn" for criterion in advisory)
    assert all(criteria[criterion]["on_fail"] == "warn" for criterion in advisory)
    assert all(criteria[criterion]["severity"] == "fail" for criterion in strict)
    assert all(criteria[criterion]["on_fail"] == "block" for criterion in strict)


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


def test_gate_rejects_report_without_typed_section_metadata():
    quality = report_renderer.analyze_report_quality("<html><body><h1>Raw report</h1></body></html>")
    assert quality["status"] == "fail"
    assert "unstructured_report" in {warning["code"] for warning in quality["warnings"]}


def test_gate_credits_authored_disclosure_markers():
    """An authored report marks required disclosures with data-dc-disclosure; the
    quality gate must credit them instead of always reporting them missing."""
    import json as _json

    def _doc(disclosures):
        contract = {"report_contract_schema": 1, "rigor": {"methodology_required": True, "uncertainty_required": True}}
        meta = {
            "section_schema": 3, "kind": "narrative_band", "section_id": "authored",
            "title": "R", "caption": "c",
            "payload": {"semantic_role": "authored_document", "authored": True, "disclosures": disclosures},
        }
        return (
            '<html data-dc-authored-document="true"><body><h1>R</h1>'
            f'<script type="application/json" data-dc-report-contract>{_json.dumps(contract)}</script>'
            f'<script type="application/json" data-dc-section-meta>{_json.dumps(meta)}</script>'
            "</body></html>"
        )

    def _codes(doc):
        return {w["code"] for w in report_renderer.analyze_report_quality(doc)["warnings"]}

    unmarked = _codes(_doc([]))
    assert "missing_methodology" in unmarked and "missing_uncertainty" in unmarked
    marked = _codes(_doc(["methodology", "uncertainty"]))
    assert "missing_methodology" not in marked and "missing_uncertainty" not in marked


def test_rigor_contract_materializes_required_disclosures_and_recipe():
    storyboard = report_renderer.design_report_storyboard(
        report_goal="Forecast renewal risk.",
        insights=[{"title": "Risk remains elevated", "detail": "Observed cohorts retain less often.", "finding_id": "risk-1"}],
        requirements={
            "rigor": {
                "require_methodology": True,
                "require_data_quality": True,
                "require_component_semantics": True,
            },
            "methodology": [
                {"title": "Grain", "detail": "Customer-month."},
                {"title": "Denominator", "detail": "Eligible renewals."},
                {"title": "Validation", "detail": "Reconciled to invoices."},
            ],
            "data_quality": "Coverage excludes customers without a completed renewal window.",
            "analysis_review": {
                "mode": "predictive",
                "uncertainty": {"method": "Bootstrap", "result": "90% interval"},
            },
        },
    )
    # The deterministic renderer and its section furniture were removed. The
    # surviving behavior is that the declared rigor requirements are preserved in
    # source_context + analysis_contract (they flow to the author dossier and the
    # embedded report contract), and a regeneration recipe is still produced.
    requirements = storyboard["source_context"]["requirements"]
    assert requirements["methodology"]
    assert requirements["data_quality"]
    assert requirements["rigor"]["require_methodology"] is True
    assert requirements["rigor"]["require_data_quality"] is True
    # Predictive uncertainty is retained on the analysis contract.
    assert storyboard["analysis_contract"]["mode"] == "predictive"
    assert storyboard["analysis_contract"]["uncertainty"] == {"method": "Bootstrap", "result": "90% interval"}
    # A source-bound regeneration recipe is still produced.
    recipe = report_renderer.ensure_regeneration_recipe(storyboard)
    assert recipe["recipe_schema"] == 1
    assert recipe["source_context_sha256"]
    assert recipe["section_plan_sha256"]


def test_quality_reports_automated_visual_semantic_findings():
    doc = (
        '<html data-dc-authored-document="true"><body>'
        '<script type="application/json" data-dc-section-meta>'
        '{"section_schema":3,"kind":"narrative_band","section_id":"authored",'
        '"title":"Report","caption":"Answer","payload":{"authored":true}}'
        '</script></body></html>'
    )
    quality = report_renderer.analyze_report_quality(
        doc,
        runtime_smoke={
            "status": "passed",
            "checks": [],
            "semantic_visual": {
                "visual_semantic_schema": 1,
                "status": "attention_required",
                "findings": [{"id": "evidence_context_missing", "detail": "Chart has no context."}],
            },
        },
    )

    assert "visual_semantic_review" in {warning["code"] for warning in quality["warnings"]}


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
    assert critique["max_passes"] == 5
    assert critique["passes"] <= 2
    assert critique["guardrail"].startswith("No evidence identifiers")


def test_storyboard_preserves_supplied_custom_chart_context():
    # The retired story-context engine no longer mints chart interpretations from
    # adjacent insights or synthesizes data notes, but a supplied custom_context
    # is still carried onto the chart section and into the regeneration sidecar.
    analyses = [{
        "title": "Player style map",
        "figure": {"data": [{"type": "scatter", "x": [1], "y": [2]}]},
        "evidence": [{"kind": "notebook_cell", "ref": "cell-style-map"}],
        "custom_context": {"palette": ["#dc2626", "#2563eb"]},
    }]
    storyboard = report_renderer.design_report_storyboard(
        report_goal="Explain player archetypes.",
        insights=[{
            "title": "Creative midfielders separate from the field",
            "detail": "The upper-right cluster combines progressive passing and chance creation.",
            "evidence": [{"kind": "notebook_cell", "ref": "cell-style-map"}],
        }],
        analyses=analyses,
        requirements={"kicker": "World Cup 2026"},
    )

    chart = next(item["data"] for item in storyboard["section_plan"] if item["section_type"] == "chart_interpretation")
    assert storyboard["source_context"]["analyses"][0]["custom_context"] == analyses[0]["custom_context"]
    assert chart["custom_context"] == analyses[0]["custom_context"]


def _handcrafted_storyboard(**overrides):
    analysis = {
        "section_type": "advanced_visual",
        "title": "Movement",
        "caption": "Validated aggregate movement.",
        "records": [
            {"name": "A", "before": 1, "after": 2, "private_email": "secret@example.com", "raw_script": "</script><script>alert(1)</script>"},
            {"name": "B", "before": 2, "after": 1, "private_email": "other@example.com"},
        ],
        "visual": {"type": "slopegraph", "label": "name", "start": "before", "end": "after"},
        "interpretation": "A moves ahead of B in the supplied aggregate.",
        "story_arc": "movement",
        "finding_id": "finding-movement",
        "evidence": [{"ref": "cell-movement", "kind": "notebook_cell"}],
    }
    analysis.update(overrides.pop("analysis", {}))
    requirements = {
        "presentation": {"mode": "handcrafted"},
        "publication": {"require_visual_review": False},
        "story_arcs": [{
            "id": "movement", "title": "What changed?",
            "reader_question": "Which supplied aggregate movement changes the ordering?",
        }],
    }
    requirements.update(overrides.pop("requirements", {}))
    return report_renderer.design_report_storyboard(
        report_goal="Explain the validated movement.",
        insights=[{
            "finding_id": "finding-movement",
            "title": "The ordering changed",
            "detail": "A moves ahead of B in the supplied aggregate.",
            "evidence": [{"ref": "cell-movement", "kind": "notebook_cell"}],
        }],
        analyses=[analysis],
        requirements=requirements,
        **overrides,
    )


def test_handcrafted_payload_is_minimized_and_source_bound():
    storyboard = _handcrafted_storyboard()
    advanced = next(item for item in storyboard["section_plan"] if item["section_type"] == "advanced_visual")

    assert "secret@example.com" not in repr(storyboard["source_context"])
    assert set(advanced["data"]["records"][0]) == {"name", "before", "after"}
    assert advanced["data"]["claim_source"]["finding_id"] == "finding-movement"
    assert storyboard["source_context"]["requirements"]["publication"]["require_visual_review"] is False


def test_handcrafted_mode_normalizes_visuals_and_allows_faithful_conventional_charts():
    # A supplied records+visual mapping is still normalized to an advanced_visual
    # section even though the retired story-arc compiler no longer runs.
    inferred = _handcrafted_storyboard()
    assert any(item["section_type"] == "advanced_visual" for item in inferred["section_plan"])

    conventional = report_renderer.design_report_storyboard(
        report_goal="Explain the supplied aggregate.",
        insights=[{"title": "Result", "detail": "The supplied aggregate has a result."}],
        analyses=[{
            "section_type": "chart_interpretation", "title": "Familiar comparison", "caption": "Comparison.",
            "figure": {"data": [{"type": "bar", "x": ["A"], "y": [1]}]},
            "interpretation": "The supplied aggregate has a result.",
        }],
        requirements={"presentation": {"mode": "handcrafted"}},
    )
    assert any(item["section_type"] == "chart_interpretation" for item in conventional["section_plan"])


def test_default_handcrafted_mode_promotes_clear_aggregate_relationships():
    storyboard = report_renderer.design_report_storyboard(
        report_goal="Explain the supplied before-and-after movement.",
        insights=[{
            "finding_id": "finding-movement",
            "title": "The ordering changed",
            "detail": "A moves ahead of B in the supplied aggregate.",
        }],
        analyses=[{
            "title": "Movement",
            "caption": "Before and after values from the supplied aggregate.",
            "records": [
                {"name": "A", "before": 1, "after": 3, "unused_private": "discard"},
                {"name": "B", "before": 2, "after": 1, "unused_private": "discard"},
            ],
            "interpretation": "A moves ahead of B in the supplied aggregate.",
            "finding_id": "finding-movement",
        }],
    )

    assert storyboard["presentation"]["mode"] == "handcrafted"
    advanced = next(item for item in storyboard["section_plan"] if item["section_type"] == "advanced_visual")
    assert advanced["data"]["visual"]["type"] == "slopegraph"
    assert set(advanced["data"]["records"][0]) == {"name", "before", "after"}
    assert "unused_private" not in repr(storyboard["source_context"])


def test_analysis_router_supports_more_semantic_asset_shapes():
    storyboard = report_renderer.design_report_storyboard(
        report_goal="Explain the supplied operational review.",
        insights=[{"title": "Review complete", "detail": "The supplied review contains decision-ready assets."}],
        analyses=[
            {"title": "Scorecard", "semantic_role": "kpi", "metrics": [{"label": "Coverage", "value": "94%"}]},
            {"title": "Conclusions", "semantic_role": "conclusions", "findings": [{"title": "Coverage is high"}]},
            {"title": "Hypotheses", "semantic_role": "hypotheses", "hypotheses": [{"title": "Coverage threshold", "status": "supported"}]},
            {"title": "Process", "semantic_role": "process", "steps": [{"title": "Validate"}, {"title": "Publish"}]},
            {"title": "Lookup", "semantic_role": "lookup", "records": [{"segment": "A", "value": 1}, {"segment": "B", "value": 2}]},
        ],
    )

    types = {item["section_type"] for item in storyboard["section_plan"]}
    assert {"metric_row", "findings", "hypothesis_ledger", "explanation", "interactive_table"}.issubset(types)


def test_critique_requires_a_path_visual_for_a_customer_journey_forecast():
    storyboard = report_renderer.design_report_storyboard(
        report_goal="Forecast next-quarter renewal along the customer journey.",
        insights=[{
            "title": "Guided onboarding leads",
            "detail": "The guided journey has the highest predicted renewal.",
        }],
        requirements={"editorial_archetype": "path_dependent_forecast"},
    )

    _critiqued, critique = report_renderer.critique_report_storyboard(storyboard)
    findings = {finding["id"]: finding for finding in critique["analytical_review"]["findings"]}

    assert "missing_decision_path_visual" in findings
    assert "path-dependent forecast" in findings["missing_decision_path_visual"]["claim"]


def test_critique_keeps_path_language_as_advisory_without_an_explicit_contract():
    storyboard = report_renderer.design_report_storyboard(
        report_goal="Forecast the remaining stages of the onboarding funnel and conversion probabilities.",
        insights=[{
            "title": "Enterprise accounts lead the conversion projection",
            "detail": "Enterprise accounts have a 28% projected conversion from an inferred mid-funnel stage.",
            "evidence": [{"kind": "notebook_cell", "ref": "cell-projection"}],
        }],
        analyses=[{
            "title": "Conversion probabilities",
            "figure": {"data": [{"type": "bar", "x": ["Enterprise"], "y": [0.28]}]},
            "interpretation": "Enterprise accounts lead the projected conversion odds.",
        }],
        requirements={},
    )

    critiqued, critique = report_renderer.critique_report_storyboard(storyboard)
    findings = {finding["id"]: finding for finding in critique["analytical_review"]["findings"]}

    assert critique["analytical_review"]["status"] == "attention_required"
    assert critiqued["analytical_review"] == critique["analytical_review"]
    assert findings["missing_baseline_comparison"]["severity"] == "required"
    assert "missing_uncertainty_quantification" in findings
    assert "missing_assumption_sensitivity" in findings
    assert "missing_decision_path_visual" not in findings
    assert "missing_outcome_distribution" not in findings
    assert findings["possible_path_dependent_forecast"]["severity"] == "info"
    unresolved_refs = findings["unresolved_evidence_anchors"]["evidence"]
    assert {entry["ref"] for entry in unresolved_refs} == {"cell-projection"}
    assert {entry["section_id"] for entry in unresolved_refs} == {"sec-primary-insights"}


def test_critique_clears_declared_predictive_review_work_without_false_claims():
    storyboard = report_renderer.design_report_storyboard(
        report_goal="Forecast the remaining World Cup knockout matches and champion probabilities.",
        insights=[{
            "title": "Spain and France are statistically tied",
            "detail": "Block-bootstrap intervals overlap after bracket sensitivity analysis.",
            "finding_id": "finding-title-odds",
            "evidence": [{"kind": "notebook_cell", "ref": "cell-bootstrap"}],
        }],
        analyses=[
            {
                "title": "Bracket decision path",
                "figure": {"data": [{"type": "scatter", "x": [0, 1], "y": [0, 1]}]},
                "interpretation": "The bracket tree shows advance probabilities for each matchup.",
                "evidence": [{"kind": "notebook_cell", "ref": "cell-bracket"}],
            },
            {
                "title": "Quarter-final scoreline heatmaps",
                "figure": {"data": [{"type": "heatmap", "z": [[1]]}]},
                "interpretation": "The outcome distribution shows draw and leading-scoreline probabilities.",
                "evidence": [{"kind": "notebook_cell", "ref": "cell-scorelines"}],
            },
        ],
        requirements={
            "evidence_registry": {
                "targets": [
                    {"id": "cell-ablation", "kind": "notebook_cell", "present": True},
                    {"id": "cell-bootstrap", "kind": "notebook_cell", "present": True},
                    {"id": "cell-bracket", "kind": "notebook_cell", "present": True},
                    {"id": "cell-pairing-scenarios", "kind": "notebook_cell", "present": True},
                    {"id": "cell-scorelines", "kind": "notebook_cell", "present": True},
                ]
            },
            "analysis_review": {
                "mode": "predictive",
                "baseline": {
                    "status": "complete",
                    "method": "Shared-holdout log loss against Elo-only baseline",
                    "result": "Full model improves log loss by 0.04",
                    "evidence": {"kind": "notebook_cell", "ref": "cell-ablation"},
                },
                "uncertainty": {"method": "block bootstrap", "result": "90% intervals"},
                "assumptions": ["One bracket pairing is inferred"],
                "sensitivity": {"status": "complete", "evidence": "cell-pairing-scenarios"},
                "decision_path": {"status": "complete", "summary": "Bracket visual"},
                "outcome_distribution": {"status": "complete", "summary": "Scoreline heatmap"},
                "export_runtime": "local",
            },
        },
    )

    critiqued, critique = report_renderer.critique_report_storyboard(storyboard)

    assert critique["analytical_review"]["status"] == "pass"
    assert critique["analytical_review"]["findings"] == []
    assert critiqued["analysis_contract"]["mode"] == "predictive"


def test_critique_requires_resolvable_baseline_evidence_and_results():
    storyboard = report_renderer.design_report_storyboard(
        report_goal="Forecast next-quarter demand.",
        insights=[{"title": "Demand forecast", "detail": "Demand is forecast to rise."}],
        requirements={
            "analysis_review": {
                "mode": "predictive",
                "baseline": {"status": "complete", "evidence": "made-up-cell"},
            },
        },
    )

    _critiqued, critique = report_renderer.critique_report_storyboard(storyboard)
    findings = {finding["id"] for finding in critique["analytical_review"]["findings"]}

    assert "missing_baseline_comparison" in findings


def test_critique_does_not_apply_forecast_checks_to_a_descriptive_report():
    storyboard = report_renderer.design_report_storyboard(
        report_goal="Explain observed customer retention by cohort.",
        insights=[{"title": "Onboarding improved retention", "detail": "Retention rose in the new cohort."}],
        requirements={},
    )

    _critiqued, critique = report_renderer.critique_report_storyboard(storyboard)

    assert critique["analytical_review"]["status"] == "pass"
    assert critique["analytical_review"]["findings"] == []


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
    assert plan["rubric_version"] == 15
    assert plan["checks"] == live_criterion_ids()
