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
    "visual_semantic_review",
    "visual_author_fallback",
    "visual_plan_budget",
    "display_fact_coverage",
    "missing_methodology",
    "missing_data_quality",
    "missing_uncertainty",
    "missing_recipe",
    "plaintext_where_component_warranted",
    "not_self_contained",
    "contrast_below_aa",
}


def test_rubric_loads_and_matches_implemented_checks():
    rubric = load_report_rubric()
    assert rubric_version() == 7
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
    assert result["quality"]["rubric_version"] == 7


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


def test_display_fact_evidence_uses_the_same_registry_resolution():
    inputs = {
        "report_goal": "Explain the result",
        "insights": [{"title": "Result", "detail": "A completed finding.", "finding_id": "finding-1"}],
        "analyses": [{
            "title": "Supporting chart",
            "figure": {"data": [{"x": [1], "y": [2]}]},
            "interpretation": "The aggregate supports the reported result.",
            "display_facts": [{
                "fact_id": "observed-result",
                "text": "Observed aggregate result",
                "uses": ["annotation"],
                "evidence": {"kind": "notebook_cell", "ref": "cell-display-result"},
            }],
        }],
        "requirements": {
            "evidence_registry": {
                "targets": [{"id": "cell-display-result", "kind": "notebook_cell", "present": True}],
            },
        },
    }
    storyboard = report_renderer.design_report_storyboard(**inputs)
    resolved = report_renderer.analyze_report_quality(report_renderer.render_report_from_storyboard(storyboard))
    assert "evidence_unresolved" not in {warning["code"] for warning in resolved["warnings"]}

    inputs["requirements"] = {}
    unresolved_storyboard = report_renderer.design_report_storyboard(**inputs)
    unresolved = report_renderer.analyze_report_quality(report_renderer.render_report_from_storyboard(unresolved_storyboard))
    assert "evidence_unresolved" in {warning["code"] for warning in unresolved["warnings"]}


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
    rendered = report_renderer.render_report_from_storyboard(storyboard)
    quality = report_renderer.analyze_report_quality(rendered)
    codes = {warning["code"] for warning in quality["warnings"]}

    assert "data-dc-regeneration-recipe" in rendered
    assert "missing_recipe" not in codes
    assert {"missing_methodology", "missing_data_quality", "missing_uncertainty"}.isdisjoint(codes)
    roles = {item["layout_role"] for item in storyboard["section_plan"]}
    assert {"data_quality", "uncertainty"}.issubset(roles)


def test_rigor_contract_only_blocks_explicit_missing_methodology():
    storyboard = report_renderer.design_report_storyboard(
        report_goal="Explain the result.",
        insights=[{"title": "Result", "detail": "The observed outcome changed."}],
        requirements={"rigor": {"require_methodology": True}},
    )
    quality = report_renderer.analyze_report_quality(report_renderer.render_report_from_storyboard(storyboard))
    failures = {warning["code"] for warning in quality["warnings"] if warning["severity"] == "fail"}

    assert failures == {"missing_methodology"}


def test_semantic_component_contract_flags_an_explicit_mismatch():
    storyboard = report_renderer.design_report_storyboard(
        report_goal="Explain the operational sequence.",
        insights=[{"title": "Sequence changed", "detail": "The supplied events occur in a new order."}],
        analyses=[{
            "section_type": "text",
            "title": "Event sequence",
            "text": "The source supplied a dated event sequence.",
            "semantic_role": "timeline",
        }],
        requirements={"rigor": {"require_component_semantics": True}},
    )
    quality = report_renderer.analyze_report_quality(report_renderer.render_report_from_storyboard(storyboard))

    assert "plaintext_where_component_warranted" in {warning["code"] for warning in quality["warnings"]}


def test_quality_reports_automated_visual_semantic_findings():
    storyboard = report_renderer.design_report_storyboard(
        report_goal="Explain the result.",
        insights=[{"title": "Result", "detail": "A completed finding."}],
    )
    quality = report_renderer.analyze_report_quality(
        report_renderer.render_report_from_storyboard(storyboard),
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


def test_storyboard_design_keeps_local_context_without_duplicate_insights():
    insights = [{
        "title": "Creative midfielders separate from the field",
        "detail": "The upper-right cluster combines progressive passing and chance creation.",
        "caveat": "Projection is based on standardized per-90 metrics.",
        "evidence": [{"kind": "notebook_cell", "ref": "cell-style-map"}],
    }]
    analyses = [{
        "title": "Player style map",
        "figure": {"data": [{"type": "scatter", "x": [1], "y": [2]}]},
        "evidence": [{"kind": "notebook_cell", "ref": "cell-style-map"}],
        "custom_context": {"palette": ["#dc2626", "#2563eb"]},
    }]
    storyboard = report_renderer.design_report_storyboard(
        report_goal="Explain player archetypes.",
        insights=insights,
        analyses=analyses,
        requirements={"kicker": "World Cup 2026"},
        max_design_passes=5,
    )

    chart = next(item["data"] for item in storyboard["section_plan"] if item["section_type"] == "chart_interpretation")
    assert storyboard["design_iterations"]["max_passes"] == 5
    assert storyboard["design_iterations"]["passes"] == 5
    assert storyboard["source_context"]["analyses"][0]["custom_context"] == analyses[0]["custom_context"]
    assert chart["story_context"][0]["title"] == insights[0]["title"]
    assert "adjacent_insights" not in chart
    assert chart["interpretation"] == insights[0]["detail"]
    assert chart["caveat"] == insights[0]["caveat"]
    assert chart["data_note"].startswith("Data note:")
    rendered = report_renderer.render_report_from_storyboard(storyboard)
    assert '<div class="r-adjacent-insights">' not in rendered
    assert "Evidence 01" not in rendered
    assert "Evidence for:" not in rendered
    assert "notebook cell: cell-style-map" not in rendered
    assert "Data note:" in rendered


def test_taxonomy_explorer_architecture_sequences_evidence_before_findings():
    figure = lambda title: {
        "data": [{"type": "bar", "x": ["A", "B"], "y": [2, 1]}],
        "layout": {"title": {"text": title}},
    }
    storyboard = report_renderer.design_report_storyboard(
        report_goal="Explain player archetypes and let readers inspect their evidence.",
        title="Player Archetypes",
        insights=[{
            "title": "Creative profiles lead the chance-creation distribution",
            "detail": "The leading archetype creates more chances per 90 than the other supplied categories.",
            "status": "confirmed",
        }],
        analyses=[
            {
                "section_type": "entity_card_grid",
                "title": "Player archetypes",
                "caption": "The supplied category cards orient the reader before the evidence.",
                "items": [
                    {"title": "Creator", "detail": "High chance creation", "accent_color": "#2563eb"},
                    {"title": "Runner", "detail": "High ball progression", "accent_color": "#0f766e"},
                ],
            },
            {"section_type": "chart_interpretation", "title": "Chance creation landscape", "caption": "Chance creation by supplied archetype.", "figure": figure("Landscape"), "interpretation": "The categories separate on chance creation.", "evidence": [{"kind": "notebook_cell", "ref": "cell-landscape"}]},
            {"section_type": "chart_interpretation", "title": "Progression diagnostic", "caption": "Progression by supplied archetype.", "figure": figure("Progression"), "interpretation": "Progression distinguishes the runner profile.", "evidence": [{"kind": "notebook_cell", "ref": "cell-progression"}]},
            {"section_type": "chart_interpretation", "title": "Finishing diagnostic", "caption": "Finishing by supplied archetype.", "figure": figure("Finishing"), "interpretation": "Finishing is more evenly distributed.", "evidence": [{"kind": "notebook_cell", "ref": "cell-finishing"}]},
            {
                "section_type": "interactive_table",
                "title": "Archetype explorer",
                "caption": "Sort the supplied aggregate rows to inspect each archetype.",
                "columns": ["archetype", "chances_created"],
                "rows": [
                    {"archetype": "Creator", "chances_created": 12},
                    {"archetype": "Runner", "chances_created": 7},
                ],
            },
        ],
        requirements={
            "editorial_archetype": "taxonomy_explorer",
            "metrics": [{"label": "Archetypes", "value": "2"}],
            "methodology": [{"title": "Grain", "detail": "Supplied aggregate player-archetype rows."}],
        },
    )

    roles = [item["layout_role"] for item in storyboard["section_plan"]]
    assert storyboard["editorial_architecture"]["archetype"] == "taxonomy_explorer"
    assert roles == [
        "opening_context",
        "executive_kpis",
        "analysis_1_entity_card_grid",
        "analysis_2_chart_interpretation",
        "analysis_3_chart_interpretation",
        "analysis_4_chart_interpretation",
        "primary_insights",
        "analysis_5_interactive_table",
        "methodology",
        "report_epilogue",
    ]
    by_role = {item["layout_role"]: item for item in storyboard["section_plan"]}
    assert by_role["opening_context"]["data"]["visual_treatment"] == "editorial_dark"
    assert by_role["executive_kpis"]["data"]["layout_variant"] == "floating_kpis"
    assert by_role["analysis_2_chart_interpretation"]["data"]["layout_variant"] == "hero_visual"
    assert by_role["analysis_3_chart_interpretation"]["layout_group"] == "diagnostic_pair_1"
    assert by_role["analysis_4_chart_interpretation"]["layout_group"] == "diagnostic_pair_1"

    rendered = report_renderer.render_report_from_storyboard(storyboard)
    assert 'class="r-hero is-full-width is-editorial-dark"' in rendered
    assert "r-section is-full-width is-floating-kpis" in rendered
    assert 'class="sr-only">Headline metrics</h2>' in rendered
    assert ">At a glance<" not in rendered
    assert 'class="r-diagnostic-pair"' in rendered
    assert rendered.index("Player archetypes") < rendered.index("Chance creation landscape")
    assert rendered.index("Finishing diagnostic") < rendered.index("Primary insights") < rendered.index("Archetype explorer")
    assert '<span class="r-chip good">confirmed</span>' not in rendered.lower()
    assert by_role["report_epilogue"]["data"]["title"] == "Notes & limits"

    # Simulate a caller editing the generated JSON into a visually weak order.
    # The bounded design critique should restore the supplied editorial grammar
    # without adding an asset, claim, number, or evidence reference.
    by_role["opening_context"]["data"].pop("visual_treatment")
    by_role["executive_kpis"]["data"].pop("layout_variant")
    by_role["analysis_3_chart_interpretation"].pop("layout_group")
    by_role["analysis_4_chart_interpretation"].pop("layout_group")
    storyboard["section_plan"] = [
        by_role["opening_context"],
        by_role["executive_kpis"],
        by_role["analysis_1_entity_card_grid"],
        by_role["analysis_2_chart_interpretation"],
        by_role["primary_insights"],
        by_role["analysis_3_chart_interpretation"],
        by_role["analysis_4_chart_interpretation"],
        by_role["analysis_5_interactive_table"],
        by_role["methodology"],
        by_role["report_epilogue"],
    ]
    critiqued, critique = report_renderer.critique_report_storyboard(storyboard)
    repaired_roles = [item["layout_role"] for item in critiqued["section_plan"]]
    repaired = {item["layout_role"]: item for item in critiqued["section_plan"]}
    design_review = critique["design_review"]

    assert design_review["passes"] == 5
    assert [stage["action"] for stage in design_review["stages"]] == [
        "restore_editorial_sequence",
        "complete_visual_hierarchy",
        "anchor_visuals_to_local_context",
        "recheck_evidence_and_explorer_pacing",
        "audit_page_architecture",
    ]
    assert design_review["status"] == "pass"
    assert repaired_roles == roles
    assert repaired["opening_context"]["data"]["visual_treatment"] == "editorial_dark"
    assert repaired["executive_kpis"]["data"]["layout_variant"] == "floating_kpis"
    assert repaired["analysis_3_chart_interpretation"]["layout_group"] == "diagnostic_pair_1"
    assert repaired["analysis_4_chart_interpretation"]["layout_group"] == "diagnostic_pair_1"
    assert repaired_roles.count("report_epilogue") == 1


def test_editorial_architecture_materializes_selector_cards_and_honors_story_controls():
    figure = lambda title: {
        "data": [{"type": "bar", "x": ["A", "B"], "y": [2, 1]}],
        "layout": {"title": {"text": title}},
    }
    storyboard = report_renderer.design_report_storyboard(
        report_goal="Explain player archetypes with guided evidence and a player-level explorer.",
        insights=[{"title": "Creators lead chance creation", "detail": "The creator category leads the supplied aggregate measure."}],
        analyses=[
            {
                "title": "Supporting diagnostic",
                "figure": figure("Supporting"),
                "caption": "A supporting aggregate diagnostic.",
                "interpretation": "This supports the category comparison.",
                "evidence": [{"kind": "notebook_cell", "ref": "cell-supporting"}],
                "story_priority": 10,
            },
            {
                "title": "Central landscape",
                "figure": figure("Central"),
                "caption": "The supplied central comparison.",
                "interpretation": "This is the report's central visual argument.",
                "evidence": [{"kind": "notebook_cell", "ref": "cell-central"}],
                "editorial_role": "hero",
            },
            {
                "title": "Chance diagnostic",
                "figure": figure("Chance"),
                "caption": "A comparable chance-creation view.",
                "interpretation": "The creator advantage persists in the diagnostic.",
                "evidence": [{"kind": "notebook_cell", "ref": "cell-chance"}],
                "diagnostic_group": "chance_creation",
            },
            {
                "title": "Progression diagnostic",
                "figure": figure("Progression"),
                "caption": "A comparable progression view.",
                "interpretation": "The same categories remain distinguishable.",
                "evidence": [{"kind": "notebook_cell", "ref": "cell-progression"}],
                "diagnostic_group": "chance_creation",
            },
            {
                "title": "Archetype selector",
                "items": [
                    {"name": "Creator", "archetype": "Creator", "team": "A", "metrics": {"players": 2}},
                    {"name": "Runner", "archetype": "Runner", "team": "B", "metrics": {"players": 2}},
                ],
            },
        ],
        requirements={
            "methodology": [{"title": "Grain", "detail": "Supplied aggregate archetype and player rows."}],
        },
    )

    roles = [item["layout_role"] for item in storyboard["section_plan"]]
    by_role = {item["layout_role"]: item for item in storyboard["section_plan"]}
    hero = next(item for item in storyboard["section_plan"] if item["data"].get("layout_variant") == "hero_visual")
    diagnostics = [item for item in storyboard["section_plan"] if item["data"].get("layout_variant") == "diagnostic"]
    taxonomy = next(item for item in storyboard["section_plan"] if item["section_type"] == "entity_card_grid")
    selector = next(item for item in storyboard["section_plan"] if item["section_type"] == "selector_panel")

    assert storyboard["editorial_architecture"]["archetype"] == "taxonomy_explorer"
    assert taxonomy["data"]["derived_from_section"] == selector["layout_role"]
    assert roles.index(taxonomy["layout_role"]) < roles.index(hero["layout_role"]) < roles.index("primary_insights") < roles.index(selector["layout_role"])
    assert hero["data"]["title"] == "Central landscape"
    assert hero["data"]["hero_selection"] == "explicit"
    assert [item["data"]["title"] for item in diagnostics[:2]] == ["Chance diagnostic", "Progression diagnostic"]
    assert all(item["data"]["diagnostic_pair_source"] == "explicit_group" for item in diagnostics[:2])

    rendered = report_renderer.render_report_from_storyboard(storyboard)
    assert 'class="sr-only">Headline metrics</h2>' not in rendered  # no metrics were supplied
    assert "r-hero-scope" in rendered
    assert by_role["opening_context"]["data"]["subtitle"] in rendered


def test_design_review_requires_interpretation_for_guided_visuals():
    storyboard = report_renderer.design_report_storyboard(
        report_goal="Explain the report.",
        insights=[{"title": "Result", "detail": "A supplied result."}],
        analyses=[
            {
                "section_type": "entity_card_grid",
                "title": "Categories",
                "items": [{"title": "A"}, {"title": "B"}],
            },
            {
                "title": "Landscape",
                "figure": {"data": [{"type": "bar", "x": ["A"], "y": [1]}]},
                "caption": "A chart with only a data note after design refinement.",
                "evidence": [{"kind": "notebook_cell", "ref": "cell-landscape"}],
            },
            {
                "title": "Explorer",
                "rows": [{"category": "A", "value": 1}],
                "columns": ["category", "value"],
            },
        ],
        requirements={"editorial_archetype": "taxonomy_explorer"},
    )
    _critiqued, critique = report_renderer.critique_report_storyboard(storyboard)
    findings = {finding["id"] for finding in critique["design_review"]["findings"]}

    assert "visual_context_incomplete" in findings


def test_guided_explorer_reorders_visual_evidence_before_findings_without_taxonomy():
    storyboard = report_renderer.design_report_storyboard(
        report_goal="Explain the central comparison before readers inspect the data.",
        insights=[{"title": "A leads", "detail": "A is highest in the supplied aggregate."}],
        analyses=[
            {
                "title": "Central comparison",
                "figure": {"data": [{"type": "bar", "x": ["A", "B"], "y": [2, 1]}]},
                "caption": "The supplied central comparison.",
                "interpretation": "A is highest in the supplied aggregate.",
                "evidence": [{"kind": "notebook_cell", "ref": "cell-central"}],
                "editorial_role": "hero",
            },
            {
                "title": "Comparison explorer",
                "rows": [{"category": "A", "value": 2}, {"category": "B", "value": 1}],
                "columns": ["category", "value"],
            },
        ],
        requirements={"methodology": [{"title": "Grain", "detail": "Supplied aggregate rows."}]},
    )

    roles = [item["layout_role"] for item in storyboard["section_plan"]]
    hero = next(item for item in storyboard["section_plan"] if item["data"].get("layout_variant") == "hero_visual")
    explorer = next(item for item in storyboard["section_plan"] if item["data"].get("layout_variant") == "reader_explorer")

    assert storyboard["editorial_architecture"]["archetype"] == "guided_explorer"
    assert roles.index(hero["layout_role"]) < roles.index("primary_insights") < roles.index(explorer["layout_role"])


def test_path_dependent_forecast_uses_generic_roles_not_tournament_terms():
    storyboard = report_renderer.design_report_storyboard(
        report_goal="Forecast which customer onboarding path will produce the highest renewal rate.",
        insights=[
            {"title": "Guided onboarding leads", "detail": "The guided path has the highest renewal forecast.", "story_role": "thesis"},
            {"title": "Activation is the pivot", "detail": "A delayed activation step changes the expected path."},
        ],
        analyses=[
            {
                "section_type": "chart_interpretation",
                "story_role": "decision_path",
                "title": "Projected onboarding paths",
                "caption": "The staged routes from signup to renewal.",
                "figure": {"data": [{"type": "scatter", "x": [0, 1], "y": [0, 1]}]},
                "interpretation": "The guided route has the highest expected renewal.",
                "evidence": [{"kind": "notebook_cell", "ref": "cell-path"}],
            },
            {
                "section_type": "chart_table_explorer",
                "story_role": "outcome_race",
                "title": "Renewal outcome comparison",
                "caption": "Expected renewal by onboarding route.",
                "records": [{"route": "Guided", "renewal": 0.7}, {"route": "Self-serve", "renewal": 0.5}],
                "chart": {"type": "bar", "x": "route", "y": "renewal"},
                "columns": ["route", "renewal"],
            },
            {
                "section_type": "comparison",
                "story_role": "mechanism",
                "title": "Why guided onboarding leads",
                "caption": "Activation timing drives the gap.",
                "groups": [{"title": "Guided", "metrics": {"Activation": "Earlier"}}],
            },
            {
                "section_type": "chart_table_explorer",
                "story_role": "outcome_distribution",
                "title": "Renewal distribution",
                "caption": "Likely renewal outcomes for the leading path.",
                "records": [{"outcome": "Renew", "probability": 70}],
                "chart": {"type": "bar", "x": "outcome", "y": "probability"},
                "columns": ["outcome", "probability"],
            },
            {
                "section_type": "interactive_table",
                "story_role": "complete_lookup",
                "title": "All path forecasts",
                "caption": "The full route-level lookup.",
                "rows": [{"route": "Guided", "renewal": 0.7}],
                "columns": ["route", "renewal"],
            },
        ],
        requirements={
            "editorial_archetype": "path_dependent_forecast",
            "methodology": [{"title": "Grain", "detail": "Customer-level aggregates."}],
        },
    )

    roles = [item["layout_role"] for item in storyboard["section_plan"]]

    assert storyboard["editorial_architecture"]["archetype"] == "path_dependent_forecast"
    assert roles.index("analysis_1_chart_interpretation") < roles.index("analysis_2_chart_table_explorer")
    assert roles.index("analysis_4_chart_table_explorer") < roles.index("primary_insights")
    assert roles.index("primary_insights") < roles.index("analysis_5_interactive_table")


def test_path_dependent_forecast_falls_back_without_a_decision_path():
    storyboard = report_renderer.design_report_storyboard(
        report_goal="Forecast next-quarter retention.",
        insights=[{"title": "Retention rises", "detail": "Retention is forecast to rise."}],
        analyses=[{
            "section_type": "interactive_table",
            "story_role": "complete_lookup",
            "title": "Forecast detail",
            "caption": "The supplied forecast rows.",
            "rows": [{"period": "Q2", "retention": 0.7}],
            "columns": ["period", "retention"],
        }],
        requirements={"editorial_archetype": "path_dependent_forecast"},
    )

    assert storyboard["editorial_architecture"]["archetype"] == "standard"
    assert "decision-path visual" in storyboard["editorial_architecture"]["reason"]


def test_editorial_insight_list_hides_routine_governance_and_can_link_a_supporting_view():
    html = report_renderer.render_report_section("insight_grid", {
        "title": "Primary insights",
        "caption": "The conclusions readers should scan before the supporting evidence.",
        "layout_variant": "editorial_list",
        "evidence_presentation": "linked",
        "items": [{
            "title": "Guided onboarding leads renewal",
            "detail": "The guided route has the highest projected renewal.",
            "status": "validated",
            "pills": [
                {"label": "70% projected renewal", "tone": "accent", "color": "#0f766e"},
                {"label": "Highest route", "tone": "neutral"},
            ],
            "scan_points": ["Activation occurs earlier.", "The first-week completion rate remains the key sensitivity."],
            "evidence": [{"kind": "notebook_cell", "ref": "cell-guided-route"}],
            "evidence_anchor": "sec-guided-route",
        }],
    })

    assert "r-insight-grid is-editorial_list" in html
    assert 'r-insight-index">01</span>' in html
    assert "r-chip accent" in html
    assert "--chip-accent:#0f766e" in html
    assert "Activation occurs earlier." in html
    assert "notebook cell: cell-guided-route" not in html
    assert ">validated<" not in html
    assert "See the evidence" not in html
    assert "Open supporting view" in html
    assert 'href="#sec-guided-route"' in html


def test_long_evidence_trace_defaults_to_a_disclosure():
    html = report_renderer.render_report_section("evidence_trace", {
        "title": "Evidence trace",
        "caption": "Registered evidence behind the report.",
        "presentation": "disclosure",
        "evidence": [
            {"kind": "notebook_cell", "ref": f"cell-{index}", "summary": "Completed analysis"}
            for index in range(7)
        ],
    })

    assert '<details class="r-evidence-disclosure">' in html
    assert "Show 7 registered evidence references" in html
    assert "cell-6" in html


def test_storyboard_keeps_provenance_in_audit_by_default_and_can_expose_a_disclosure():
    inputs = {
        "report_goal": "Explain the completed relationship.",
        "insights": [{
            "title": "The relationship is positive",
            "detail": "The supplied aggregate shows a positive relationship.",
            "evidence": [{"kind": "notebook_cell", "ref": "cell-relationship"}],
        }],
        "analyses": [{
            "title": "Relationship view",
            "figure": {"data": [{"type": "scatter", "x": [1], "y": [2]}]},
            "interpretation": "The supplied point sits on the positive trend.",
            "evidence": [{"kind": "notebook_cell", "ref": "cell-relationship"}],
        }],
    }

    audit_only = report_renderer.design_report_storyboard(**inputs)
    audit_roles = [item["layout_role"] for item in audit_only["section_plan"]]
    assert "evidence_trace" not in audit_roles
    assert audit_only["source_context"]["insights"][0]["evidence"][0]["ref"] == "cell-relationship"

    disclosed = report_renderer.design_report_storyboard(
        **inputs,
        requirements={"presentation": {"provenance": "disclosure"}},
    )
    trace = next(item for item in disclosed["section_plan"] if item["layout_role"] == "evidence_trace")
    assert trace["data"]["title"] == "Sources & reproducibility"
    assert trace["data"]["presentation"] == "disclosure"
    assert [item.get("ref") for item in trace["data"]["evidence"]].count("cell-relationship") == 1


def test_storyboard_uses_explicit_width_roles_instead_of_type_driven_narrow_sections():
    storyboard = report_renderer.design_report_storyboard(
        report_goal="Explain the completed relationship.",
        insights=[{"title": "Result", "detail": "A completed result."}],
        requirements={"data_quality": "Coverage is complete for the supplied rows."},
    )
    by_role = {item["layout_role"]: item["data"] for item in storyboard["section_plan"]}
    assert by_role["executive_readout"]["layout_width"] == "reading"
    assert by_role["data_quality"]["layout_width"] == "content"
    rendered = report_renderer.render_report_from_storyboard(storyboard)
    assert "r-section is-content-width" in rendered
    assert "r-section is-reading-width" in rendered
    assert "r-section is-narrow" not in rendered


def test_storyboard_compiles_a_bounded_desktop_composition_contract():
    storyboard = report_renderer.design_report_storyboard(
        report_goal="Explain the completed relationship.",
        insights=[{
            "title": "The supplied relationship is positive",
            "detail": "The completed aggregate increases across the supplied comparison groups.",
            "evidence": [{"kind": "notebook_cell", "ref": "cell-relationship"}],
        }],
        analyses=[{
            "title": "Relationship view",
            "caption": "Compare the supplied groups on the completed aggregate.",
            "figure": {"data": [{"type": "bar", "x": ["A", "B"], "y": [1, 2]}]},
            "interpretation": "The supplied comparison rises from A to B.",
            "evidence": [{"kind": "notebook_cell", "ref": "cell-relationship"}],
        }],
        requirements={"data_quality": "Coverage is complete for the supplied rows."},
    )
    by_role = {item["layout_role"]: item["data"] for item in storyboard["section_plan"]}
    assert by_role["opening_context"]["desktop_composition"] == "opening"
    assert by_role["executive_readout"]["desktop_composition"] == "reader_readout"
    assert by_role["primary_insights"]["desktop_composition"] == "editorial_findings"
    assert by_role["analysis_1_chart_interpretation"]["desktop_composition"] == "guided_visual"
    assert by_role["data_quality"]["desktop_composition"] == "trust_close"
    assert by_role["analysis_1_chart_interpretation"]["layout_width"] == "full"
    assert any(
        entry["desktop_composition"] == "guided_visual"
        for entry in storyboard["layout_plan"]
        if entry["section"] == "analysis_1_chart_interpretation"
    )

    rendered = report_renderer.render_report_from_storyboard(storyboard)
    assert 'data-dc-composition="guided_visual"' in rendered
    assert "is-composition-guided-visual" in rendered
    assert "is-composition-trust-close" in rendered
    assert report_renderer.review_storyboard_design(storyboard)["status"] == "pass"


def test_story_arcs_allow_variable_reader_questions_to_order_supplied_sections():
    figure = lambda title: {
        "data": [{"type": "bar", "x": ["A", "B"], "y": [2, 1]}],
        "layout": {"title": {"text": title}},
    }
    storyboard = report_renderer.design_report_storyboard(
        report_goal="Explain the completed analysis.",
        insights=[{"title": "The leading factor separates outcomes", "detail": "The supplied comparison shows a clear separation."}],
        analyses=[
            {
                "section_type": "chart_interpretation",
                "title": "The separation",
                "caption": "Compare the supplied groups on the leading factor.",
                "figure": figure("Separation"),
                "interpretation": "The leading group separates from the rest.",
                "story_arc": "signal",
            },
            {
                "section_type": "interactive_table",
                "title": "Scenario lookup",
                "caption": "Inspect the supplied aggregate scenarios.",
                "columns": ["scenario", "outcome"],
                "rows": [{"scenario": "A", "outcome": "Higher"}],
                "story_arc": "decision",
            },
        ],
        requirements={
            "story_arcs": [
                {
                    "id": "signal",
                    "title": "What separates the outcomes?",
                    "question": "Which factor creates the visible separation?",
                },
                {
                    "id": "decision",
                    "title": "Where should readers look next?",
                    "claim": "Use the supplied scenario lookup for the complete comparison.",
                },
            ],
        },
    )

    assert storyboard["storyboard_schema"] == 2
    assert [arc["phase"] for arc in storyboard["storyboard"]] == ["signal", "decision"]
    assert storyboard["storyboard"][0]["sections"] == ["analysis_1_chart_interpretation"]
    assert storyboard["storyboard"][1]["sections"] == ["analysis_2_interactive_table"]
    assert [item["layout_role"] for item in storyboard["section_plan"]] == [
        "opening_context",
        "story_arc_signal",
        "analysis_1_chart_interpretation",
        "story_arc_decision",
        "analysis_2_interactive_table",
        "primary_insights",
    ]
    rendered = report_renderer.render_report_from_storyboard(storyboard)
    assert "What separates the outcomes?" in rendered
    assert "Where should readers look next?" in rendered
    assert "r-section is-full-width is-quiet-surface is-story-arc" in rendered


def test_primary_insight_layout_defaults_to_editorial_list_but_keeps_card_grid_opt_in():
    standard = report_renderer.design_report_storyboard(
        report_goal="Explain observed retention.",
        insights=[{"title": "New customers churn first", "detail": "The newest cohort has the lowest observed renewal."}],
    )
    standard_findings = next(item["data"] for item in standard["section_plan"] if item["layout_role"] == "primary_insights")
    assert standard_findings["layout_variant"] == "editorial_list"
    assert "is-editorial_list" in report_renderer.render_report_from_storyboard(standard)

    analysis = {
        "section_type": "chart_interpretation",
        "story_role": "decision_path",
        "title": "Renewal paths",
        "caption": "Routes from activation to renewal.",
        "figure": {"data": [{"type": "scatter", "x": [0, 1], "y": [0, 1]}]},
        "interpretation": "The guided path has the highest predicted renewal.",
    }
    editorial = report_renderer.design_report_storyboard(
        report_goal="Forecast renewal along the customer journey.",
        insights=[{"title": "Guided onboarding leads", "detail": "The guided route has the highest renewal forecast."}],
        analyses=[analysis],
        requirements={"editorial_archetype": "path_dependent_forecast"},
    )
    editorial_findings = next(item["data"] for item in editorial["section_plan"] if item["layout_role"] == "primary_insights")
    assert editorial_findings["layout_variant"] == "editorial_list"
    assert editorial_findings["evidence_presentation"] == "none"

    explicit_grid = report_renderer.design_report_storyboard(
        report_goal="Forecast renewal along the customer journey.",
        insights=[{"title": "Guided onboarding leads", "detail": "The guided route has the highest renewal forecast."}],
        analyses=[analysis],
        requirements={
            "editorial_archetype": "path_dependent_forecast",
            "presentation": {"insight_layout": "card_grid"},
        },
    )
    explicit_findings = next(item["data"] for item in explicit_grid["section_plan"] if item["layout_role"] == "primary_insights")
    assert explicit_findings["layout_variant"] == "card_grid"


def test_surface_hierarchy_distinguishes_quiet_trust_and_evidence_sections():
    narrative = report_renderer.render_report_section("narrative_band", {
        "title": "The answer",
        "summary": "Retention is projected to improve.",
    })
    methodology = report_renderer.render_report_section("methodology_block", {
        "title": "Method",
        "methods": [{"title": "Grain", "detail": "Customer-month aggregate."}],
    })
    chart = report_renderer.render_report_section("chart_interpretation", {
        "title": "Renewal by path",
        "caption": "Expected renewal by path.",
        "figure": {"data": [{"type": "bar", "x": ["Guided"], "y": [0.7]}]},
        "interpretation": "Guided onboarding leads.",
    })
    entities = report_renderer.render_report_section("entity_card_grid", {
        "title": "Customer segments",
        "items": [{"title": "Guided", "count": 42, "detail": "Customers with guided onboarding."}],
    })

    assert "is-quiet-surface" in narrative
    assert "is-trust-surface" in methodology
    assert "is-evidence-surface" in chart
    assert "is-quiet-surface" in entities
    assert "r-entity-card" in entities


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
        report_goal="Forecast the remaining World Cup knockout matches and champion probabilities.",
        insights=[{
            "title": "Spain lead the title projection",
            "detail": "Spain have a 28% chance to win the tournament from an inferred quarter-final pairing.",
            "evidence": [{"kind": "notebook_cell", "ref": "cell-projection"}],
        }],
        analyses=[{
            "title": "Champion probabilities",
            "figure": {"data": [{"type": "bar", "x": ["Spain"], "y": [0.28]}]},
            "interpretation": "Spain lead the projected title odds.",
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


def test_static_runtime_and_contrast_checks_detect_broken_shell_wiring():
    storyboard = report_renderer.design_report_storyboard(
        report_goal="Explain the result",
        insights=[{"title": "Result", "detail": "A completed finding.", "finding_id": "finding-1"}],
        analyses=[{"title": "Supporting chart", "figure": {"data": [{"type": "bar", "x": ["A"], "y": [1]}]}}],
    )
    storyboard, _ = report_renderer.critique_report_storyboard(storyboard)
    doc = report_renderer.render_report_from_storyboard(storyboard)

    broken_runtime = report_renderer.analyze_report_quality(doc.replace("data-dc-report-shell-script", "data-dc-runtime-missing"))
    assert "runtime_smoke_failed" in {warning["code"] for warning in broken_runtime["warnings"]}

    missing_plotly = report_renderer.analyze_report_quality(doc.replace(report_renderer.plotly_script_tag(), ""))
    assert "runtime_smoke_failed" in {warning["code"] for warning in missing_plotly["warnings"]}

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
    assert plan["rubric_version"] == 7
    assert plan["checks"] == live_criterion_ids()
