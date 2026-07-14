"""Tests for the evidence-bound runtime visual-author stage."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dataclaw.providers.llm.provider import TextDeltaEvent, TurnCompleteEvent
from dataclaw_workspace.config import WorkspaceConfig
from dataclaw_workspace.report_renderer import (
    design_report_storyboard,
    render_report_from_storyboard,
    review_storyboard_authoring,
)
from dataclaw_workspace.tools import report_design_report
from dataclaw_workspace.visual_author import (
    VisualAuthorRequiredError,
    apply_visual_spec,
    author_report_visuals,
    build_visual_author_catalog,
    validate_visual_spec,
)


class _JSONLLM:
    def __init__(self, response: dict):
        self.response = json.dumps(response)
        self.system = ""
        self.messages = []

    async def stream_turn(self, messages, *, system, tools, **kwargs):
        self.system = system
        self.messages = messages
        yield TextDeltaEvent(text=self.response)
        yield TurnCompleteEvent()


@pytest.fixture
def cfg():
    return WorkspaceConfig()


def _storyboard() -> dict:
    return design_report_storyboard(
        report_goal="Decide which customer cohort needs intervention.",
        title="Customer health",
        insights=[{
            "finding_id": "find-new-customers",
            "title": "New customers have the weakest renewal rate",
            "detail": "The first-90-day cohort has the lowest renewal rate.",
            "pills": [{"label": "First 90 days", "tone": "accent"}],
            "bullets": ["Lowest renewal rate", "Largest recoverable account base"],
            "representative_examples": ["Self-serve customers", "New enterprise accounts"],
        }],
    )


def _multi_surface_storyboard() -> dict:
    storyboard = _storyboard()
    storyboard["section_plan"].insert(1, {
        "section_type": "chart_interpretation",
        "layout_role": "renewal_evidence",
        "data": {
            "title": "Renewal evidence",
            "caption": "Aggregate renewal evidence by customer age.",
            "figure": {"data": [{"type": "bar", "x": ["New", "Mature"], "y": [61, 84]}]},
            "interpretation": "New customers renew less often.",
            "display_facts": [
                {"fact_id": "cohort-window", "text": "First 90 days", "uses": ["pill"]},
                {"fact_id": "renewal-gap", "text": "23-point renewal gap", "uses": ["scan_point"]},
                {"fact_id": "renewal-note", "text": "Observed cohorts only", "uses": ["annotation"]},
            ],
        },
    })
    storyboard["section_plan"].append({
        "section_type": "insight_grid",
        "layout_role": "secondary_insights",
        "data": {
            "title": "Secondary finding",
            "items": [{
                "finding_id": "find-mature-customers",
                "title": "Mature customers are stable",
                "detail": "The mature cohort is less volatile.",
                "bullets": ["Higher renewal rate"],
            }],
        },
    })
    return storyboard


@pytest.mark.asyncio
async def test_runtime_visual_author_materializes_only_selected_source_facts():
    storyboard = _storyboard()
    response = {
        "schema": 1,
        "theme": "ocean",
        "sections": [{
            "section_id": "primary_insights",
            "surface": "quiet",
            "layout": "editorial_list",
            "evidence_presentation": "linked",
        }],
        "insights": [{
            "insight_id": "find-new-customers",
            "pills": [{"fact_id": "find-new-customers-pill-1", "tone": "accent"}],
            "scan_points": ["find-new-customers-scan-1"],
            "examples": ["find-new-customers-example-1"],
        }],
    }

    authored, record = await author_report_visuals(
        storyboard,
        config={"mode": "runtime"},
        llm=_JSONLLM(response),
    )

    assert record["status"] == "applied"
    assert record["source"] == "runtime"
    primary = next(item for item in authored["section_plan"] if item["layout_role"] == "primary_insights")
    insight = primary["data"]["items"][0]
    assert primary["data"]["layout_variant"] == "editorial_list"
    assert insight["display_pills"] == [{"label": "First 90 days", "tone": "accent"}]
    assert insight["scan_points"] == ["Lowest renewal rate"]
    assert insight["representative_examples"] == ["Self-serve customers"]
    assert authored["visual_theme"]["name"] == "ocean"

    html = render_report_from_storyboard(authored)
    assert "--dc-accent: #0369a1" in html
    assert "r-insight-grid is-editorial_list" in html
    assert "Examples" in html
    assert "Self-serve customers" in html


@pytest.mark.asyncio
async def test_runtime_visual_author_rejects_a_fabricated_fact_and_preserves_storyboard():
    storyboard = _storyboard()
    response = {
        "schema": 1,
        "sections": [],
        "insights": [{
            "insight_id": "find-new-customers",
            "scan_points": ["invented-fact"],
        }],
    }

    authored, record = await author_report_visuals(
        storyboard,
        config={"mode": "runtime"},
        llm=_JSONLLM(response),
    )

    assert record["status"] == "fallback"
    assert record["applied"] is False
    primary = next(item for item in authored["section_plan"] if item["layout_role"] == "primary_insights")
    assert "display_pills" not in primary["data"]["items"][0]
    assert "invented-fact" not in render_report_from_storyboard(authored)


def test_visual_author_validator_rejects_unbounded_theme_and_cross_insight_fact():
    catalog = build_visual_author_catalog(_storyboard(), {"mode": "runtime"})
    with pytest.raises(ValueError, match="unknown theme"):
        validate_visual_spec({"schema": 1, "theme": "#ff00ff", "sections": [], "insights": []}, catalog)
    with pytest.raises(ValueError, match="cannot be used"):
        validate_visual_spec({
            "schema": 1,
            "sections": [],
            "insights": [{
                "insight_id": "find-new-customers",
                "scan_points": ["find-new-customers-pill-1"],
            }],
        }, catalog)


def test_visual_author_can_reorder_only_declared_story_blocks():
    storyboard = _storyboard()
    storyboard["section_plan"].extend([
        {
            "section_type": "callout",
            "layout_role": "mechanism",
            "visual_author_story_zone": "evidence_sequence",
            "visual_author_story_block": "mechanism",
            "data": {"title": "Mechanism", "text": "The supplied mechanism explains the observed change."},
        },
        {
            "section_type": "callout",
            "layout_role": "scenarios",
            "visual_author_story_zone": "evidence_sequence",
            "visual_author_story_block": "scenarios",
            "data": {"title": "Scenarios", "text": "The supplied scenarios change the decision threshold."},
        },
    ])
    catalog = build_visual_author_catalog(storyboard, {"mode": "provided", "allow_story_reorder": True})
    assert catalog["composition"] == [{
        "zone_id": "evidence_sequence",
        "blocks": [
            {"block_id": "mechanism", "section_ids": ["mechanism"]},
            {"block_id": "scenarios", "section_ids": ["scenarios"]},
        ],
    }]
    spec = validate_visual_spec({
        "schema": 1,
        "sections": [],
        "insights": [],
        "composition": [{"zone_id": "evidence_sequence", "order": ["scenarios", "mechanism"]}],
    }, catalog)
    authored = apply_visual_spec(storyboard, spec, catalog)
    roles = [item["layout_role"] for item in authored["section_plan"]]
    assert roles[-2:] == ["scenarios", "mechanism"]

    with pytest.raises(ValueError, match="every declared block exactly once"):
        validate_visual_spec({
            "schema": 1,
            "sections": [],
            "insights": [],
            "composition": [{"zone_id": "evidence_sequence", "order": ["mechanism"]}],
        }, catalog)


def test_authoring_review_requires_typed_facts_when_runtime_visuals_are_requested():
    storyboard = _storyboard()
    storyboard["visual_author_config"] = {"mode": "runtime", "facts": []}
    review = review_storyboard_authoring(storyboard)
    assert review["status"] == "attention_recommended"
    assert {finding["id"] for finding in review["findings"]} == {"legacy_insight_display_semantics"}

    primary = next(item for item in storyboard["section_plan"] if item["layout_role"] == "primary_insights")
    primary["data"]["items"][0]["display_facts"] = [{
        "fact_id": "renewal-rate",
        "text": "61% renewal rate",
        "uses": ["pill", "scan_point"],
    }]
    covered = review_storyboard_authoring(storyboard)
    assert covered["status"] == "pass"
    assert covered["target_count"] == covered["covered_target_count"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("finding_id", "title", "detail", "fact_id", "fact_text"),
    [
        ("customer-retention", "New customers have the weakest renewal", "The first contract cohort has the lowest renewal rate.", "renewal-gap", "23-point renewal gap"),
        ("clinical-pathway", "Treatment delay concentrates in one pathway", "The supplied pathway has the longest time to treatment.", "treatment-delay", "Median 18-hour treatment delay"),
        ("supply-route", "One route drives the service risk", "The supplied route has the largest late-delivery share.", "late-delivery", "14% late-delivery share"),
    ],
)
async def test_runtime_visual_author_uses_same_typed_fact_contract_across_domains(
    finding_id, title, detail, fact_id, fact_text,
):
    storyboard = design_report_storyboard(
        report_goal="Identify the evidence-backed decision priority.",
        title="Cross-domain report",
        insights=[{
            "finding_id": finding_id,
            "title": title,
            "detail": detail,
            "display_facts": [{"fact_id": fact_id, "text": fact_text, "uses": ["scan_point"]}],
        }],
    )
    response = {
        "schema": 1,
        "sections": [],
        "insights": [{"insight_id": finding_id, "scan_points": [fact_id]}],
    }
    authored, record = await author_report_visuals(storyboard, config={"mode": "runtime"}, llm=_JSONLLM(response))
    assert record["status"] == "applied"
    primary = next(item for item in authored["section_plan"] if item["layout_role"] == "primary_insights")
    assert primary["data"]["items"][0]["scan_points"] == [fact_text]


@pytest.mark.asyncio
async def test_disabled_visual_author_bypasses_legacy_fact_catalog_validation():
    storyboard = _storyboard()
    primary = next(item for item in storyboard["section_plan"] if item["layout_role"] == "primary_insights")
    primary["data"]["items"].append({
        "finding_id": "find-other",
        "title": "Another cohort",
        "detail": "A second source insight.",
        "pills": [{"id": "reused-decorative-id", "label": "Second"}],
    })
    primary["data"]["items"][0]["pills"] = [{"id": "reused-decorative-id", "label": "First"}]

    authored, record = await author_report_visuals(storyboard, config={"mode": "off"})

    assert record == {"schema": 1, "mode": "off", "status": "disabled", "applied": False}
    assert authored["visual_author"] == record


@pytest.mark.asyncio
async def test_visual_author_applies_section_facts_and_all_insight_grids():
    storyboard = _multi_surface_storyboard()
    response = {
        "schema": 1,
        "sections": [{
            "section_id": "renewal_evidence",
            "surface": "evidence",
            "pills": [{"fact_id": "cohort-window", "tone": "accent"}],
            "scan_points": ["renewal-gap"],
            "annotations": ["renewal-note"],
        }],
        "insights": [{
            "insight_id": "find-mature-customers",
            "scan_points": ["find-mature-customers-scan-1"],
        }],
    }

    authored, record = await author_report_visuals(storyboard, config={"mode": "runtime"}, llm=_JSONLLM(response))

    assert record["status"] == "applied"
    evidence = next(item for item in authored["section_plan"] if item["layout_role"] == "renewal_evidence")["data"]
    assert evidence["visual_pills"] == [{"label": "First 90 days", "tone": "accent"}]
    assert evidence["visual_scan_points"] == ["23-point renewal gap"]
    assert evidence["visual_annotations"] == ["Observed cohorts only"]
    secondary = next(item for item in authored["section_plan"] if item["layout_role"] == "secondary_insights")
    assert secondary["data"]["items"][0]["scan_points"] == ["Higher renewal rate"]
    html = render_report_from_storyboard(authored)
    assert "23-point renewal gap" in html
    assert "Observed cohorts only" in html


@pytest.mark.asyncio
async def test_required_visual_author_returns_auditable_failure_and_runtime_has_output_limit():
    storyboard = _storyboard()
    with pytest.raises(VisualAuthorRequiredError) as failed:
        await author_report_visuals(storyboard, config={"mode": "required"})
    assert failed.value.record["status"] == "failed"
    assert failed.value.storyboard["visual_author"]["reason"].startswith("No LLM provider")

    authored, record = await author_report_visuals(
        storyboard,
        config={"mode": "runtime", "max_output_chars": 512},
        llm=_JSONLLM({"schema": 1, "sections": [], "insights": [], "padding": "x" * 600}),
    )
    assert record["status"] == "fallback"
    assert "max_output_chars" in record["reason"]
    assert authored["visual_author"] == record


@pytest.mark.asyncio
async def test_report_design_persists_required_visual_author_failure_audit(cfg, tmp_path, monkeypatch):
    import dataclaw.config.paths as paths

    monkeypatch.setattr(paths, "DATACLAW_HOME", tmp_path)
    with pytest.raises(ValueError, match="Failure audit"):
        await report_design_report(
            cfg=cfg,
            report_goal="Decide whether an intervention is needed.",
            title="Required visual author",
            report_path="reports/required.html",
            storyboard_path="reports/required.storyboard.json",
            quality_gate="off",
            insights=[{"title": "A completed insight", "detail": "The evidence is ready."}],
            visual_author={"mode": "required"},
        )

    audit = tmp_path / "workspaces" / "default" / "reports" / "required.storyboard.visual-author-failure.json"
    payload = json.loads(audit.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["visual_author"]["mode"] == "required"


@pytest.mark.asyncio
async def test_report_design_report_runs_runtime_visual_author_with_explicit_facts(cfg, tmp_path, monkeypatch):
    import dataclaw.config.paths as paths

    monkeypatch.setattr(paths, "DATACLAW_HOME", tmp_path)
    response = {
        "schema": 1,
        "theme": "forest",
        "sections": [{
            "section_id": "primary_insights",
            "surface": "quiet",
            "layout": "editorial_list",
            "evidence_presentation": "linked",
        }],
        "insights": [{
            "insight_id": "find-activation",
            "pills": [{"fact_id": "activation-rate", "tone": "warn"}],
            "scan_points": ["activation-action"],
        }],
    }
    result = await report_design_report(
        cfg=cfg,
        llm=_JSONLLM(response),
        report_goal="Decide whether to improve onboarding activation.",
        title="Activation health",
        report_path="reports/activation.html",
        storyboard_path="reports/activation.storyboard.json",
        quality_gate="warn",
        insights=[{
            "finding_id": "find-activation",
            "title": "Activation drops in the first week",
            "detail": "Observed activation is below the target in the first seven days.",
        }],
        visual_author={
            "mode": "runtime",
            "facts": [
                {"fact_id": "activation-rate", "insight_id": "find-activation", "text": "42% activated", "uses": ["pill"]},
                {"fact_id": "activation-action", "insight_id": "find-activation", "text": "Prioritize the first-week checklist", "uses": ["scan_point"]},
            ],
        },
    )

    assert result["visual_author"]["status"] == "applied"
    html = Path(result["html_path"]).read_text(encoding="utf-8")
    assert "--dc-accent: #166534" in html
    assert "42% activated" in html
    assert "Prioritize the first-week checklist" in html
