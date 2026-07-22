"""Tests for full-document creative authoring and bounded visual editing."""

from __future__ import annotations

import json
from pathlib import Path
import re

import pytest

from dataclaw.providers.llm.provider import TextDeltaEvent, TurnCompleteEvent
from dataclaw_workspace import tools as workspace_tools
from dataclaw_workspace.config import WorkspaceConfig
from dataclaw_workspace.report_renderer import (
    analyze_report_quality,
    build_evidence_registry,
    design_report_storyboard,
    render_report_from_storyboard,
    review_storyboard_authoring,
)
from dataclaw_workspace.tools import report_design_report, report_publish
from dataclaw_workspace.visual_author import (
    VisualAuthorRequiredError,
    apply_visual_spec,
    author_report_visuals,
    build_creative_author_dossier,
    build_visual_author_catalog,
    validate_authored_document,
    visual_author_config,
    validate_visual_spec,
)


class _JSONLLM:
    def __init__(self, response):
        responses = response if isinstance(response, tuple) else (response,)
        self.responses = [item if isinstance(item, str) else json.dumps(item) for item in responses]
        self.calls = 0
        self.system = ""
        self.systems = []
        self.messages = []

    async def stream_turn(self, messages, *, system, tools, **kwargs):
        self.system = system
        self.systems.append(system)
        self.messages = messages
        if self.calls >= len(self.responses):
            raise AssertionError("test LLM received more calls than configured responses")
        response = self.responses[self.calls]
        self.calls += 1
        yield TextDeltaEvent(text=response)
        yield TurnCompleteEvent()


@pytest.fixture
def cfg():
    return WorkspaceConfig()


@pytest.fixture(autouse=True)
def reset_project_directory_override():
    """Keep request-scoped workspace routing from leaking into these tests."""
    workspace_tools.set_project_dir(None)
    yield
    workspace_tools.set_project_dir(None)


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


def _ledger_backed_storyboard() -> dict:
    storyboard = _storyboard()
    storyboard["evidence_registry"] = build_evidence_registry(storyboard)
    assert storyboard["evidence_registry"]["targets"]
    return storyboard


def _authored_html(*, title: str = "Customer intervention brief", claim: str | None = None) -> str:
    claim = claim or "The earliest customer window deserves the first intervention review."
    return f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{title}</title>
  <style>
    :root{{--dc-ink:#172033;--dc-muted:#526079;--dc-surface:#ffffff;--accent:#d84a2f}}
    body{{margin:0;background:#f4efe8;color:var(--dc-ink);font:17px/1.6 Georgia,serif}}
    main{{max-width:72rem;margin:auto;padding:4rem 2rem}} figure{{margin:3rem 0}}
  </style>
</head>
<body>
  <main data-source="src-finding-1">
    <header><p>Customer health · editorial evidence brief</p><h1>{title}</h1></header>
    <section data-evidence="ev-1">
      <h2>Where to begin</h2>
      <p id="claim-1">{claim}</p>
      <figure data-evidence="ev-1">
        <svg viewBox="0 0 400 120" role="img" aria-label="Evidence emphasis">
          <path d="M10 100 C90 80 170 85 240 45 S340 25 390 12" fill="none" stroke="#d84a2f" stroke-width="8"/>
        </svg>
        <figcaption>The visual emphasis accompanies the cited completed finding.</figcaption>
      </figure>
    </section>
  </main>
  <script type="application/json" data-dc-author-coverage>{{"omitted":[]}}</script>
</body>
</html>'''


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
async def test_creative_visual_author_writes_full_html_prose_and_custom_visuals_from_dossier():
    storyboard = _ledger_backed_storyboard()
    html_response = _authored_html()
    llm = _JSONLLM((html_response, {"status": "pass", "findings": []}))

    authored, record = await author_report_visuals(
        storyboard,
        config={"mode": "creative"},
        llm=llm,
    )

    assert record["status"] == "applied"
    assert record["mode"] == "creative"
    assert record["source"] == "llm_full_document"
    assert record["evidence_review"]["status"] == "pass"
    assert llm.calls == 2
    assert "writer, information designer" in llm.systems[0]
    assert "independent evidence editor" in llm.systems[1]
    assert authored["authored_document"]["html"] == html_response
    assert "The first-90-day cohort has the lowest renewal rate" in authored["authored_document"]["dossier"]
    html = render_report_from_storyboard(authored)
    assert 'data-dc-authored-document="true"' in html
    assert "The earliest customer window deserves the first intervention review" in html
    assert '<svg viewBox="0 0 400 120"' in html
    assert "Content-Security-Policy" in html
    assert "data-dc-author-evidence-map" in html
    assert "data-dc-evidence-registry" in html

    quality = analyze_report_quality(html, visual_author=record)
    assert "creative_evidence_ledger_missing" not in {item["code"] for item in quality["warnings"]}
    assert "authored_evidence_coverage_missing" not in {item["code"] for item in quality["warnings"]}
    assert "authored_evidence_review_failed" not in {item["code"] for item in quality["warnings"]}
    without_ledger = re.sub(
        r"<script[^>]*data-dc-evidence-registry[^>]*>.*?</script>",
        "",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    missing = analyze_report_quality(without_ledger, visual_author=record)
    assert "creative_evidence_ledger_missing" in {item["code"] for item in missing["warnings"]}

    without_coverage = re.sub(
        r"<script[^>]*data-dc-author-coverage[^>]*>.*?</script>",
        "",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    missing_coverage = analyze_report_quality(without_coverage, visual_author=record)
    assert "authored_evidence_coverage_missing" in {item["code"] for item in missing_coverage["warnings"]}

    failed_review = dict(record)
    failed_review["evidence_review"] = {
        "status": "attention_required",
        "findings": [{"issue": "Unsupported conclusion"}],
    }
    review_quality = analyze_report_quality(html, visual_author=failed_review)
    assert "authored_evidence_review_failed" in {item["code"] for item in review_quality["warnings"]}


@pytest.mark.parametrize(
    ("layout_html", "css", "message"),
    [
        (
            '<div>{{section:opening_context}}{{section:executive_readout}}</div>',
            ".r-page{display:grid}",
            "every supplied section exactly once",
        ),
        (
            '<div>New claim{{section:opening_context}}{{section:executive_readout}}{{section:primary_insights}}</div>',
            ".r-page{display:grid}",
            "not visible text",
        ),
        (
            '<script>{{section:opening_context}}</script><div>{{section:executive_readout}}{{section:primary_insights}}</div>',
            ".r-page{display:grid}",
            "cannot use <script>",
        ),
        (
            '<div>{{section:opening_context}}{{section:executive_readout}}{{section:primary_insights}}</div>',
            ".r-page{background:url(https://example.test/pixel.png)}",
            "remote or embedded assets",
        ),
        (
            '<div>{{section:opening_context}}{{section:executive_readout}}{{section:primary_insights}}</div>',
            '.r-page::before{content:"Unsupported conclusion"}',
            "generated visible copy",
        ),
    ],
)
def test_creative_visual_author_rejects_missing_sections_copy_code_and_remote_assets(
    layout_html, css, message,
):
    catalog = build_visual_author_catalog(_ledger_backed_storyboard(), {"mode": "creative"})
    with pytest.raises(ValueError, match=message):
        validate_visual_spec({
            "schema": 1,
            "sections": [],
            "insights": [],
            "creative": {"layout_html": layout_html, "css": css},
        }, catalog)


def test_creative_visual_author_requires_non_empty_evidence_ledger():
    with pytest.raises(ValueError, match="non-empty evidence ledger"):
        build_visual_author_catalog(_storyboard(), {"mode": "creative"})


def test_creative_catalog_exposes_asset_shape_and_semantics_without_row_values():
    storyboard = _ledger_backed_storyboard()
    storyboard["section_plan"].append({
        "section_type": "advanced_visual",
        "layout_role": "probability_shift",
        "data": {
            "title": "Probability shift",
            "caption": "Change across the two supplied aggregate snapshots.",
            "interpretation": "The supplied leader changed after the update.",
            "semantic_role": "comparison",
            "records": [
                {"team": "Private Team A", "before": 0.34, "after": 0.51},
                {"team": "Private Team B", "before": 0.42, "after": 0.37},
            ],
            "visual": {"type": "slopegraph", "label": "team", "start": "before", "end": "after"},
            "evidence": [{"kind": "notebook_cell", "ref": "cell-shift"}],
        },
    })

    catalog = build_visual_author_catalog(storyboard, {"mode": "creative"})
    section = next(item for item in catalog["sections"] if item["section_id"] == "probability_shift")
    semantics = section["asset_semantics"]

    assert semantics["visual_type"] == "slopegraph"
    assert semantics["field_mappings"] == {"label": "team", "start": "before", "end": "after"}
    assert semantics["aggregate_record_count"] == 2
    assert semantics["aggregate_columns"] == ["team", "before", "after"]
    assert semantics["semantic_role"] == "comparison"
    assert semantics["evidence_ids"] == ["cell-shift"]
    assert "Private Team A" not in json.dumps(catalog)


def test_creative_dossier_includes_bounded_aggregate_values_and_complete_ledger():
    storyboard = _ledger_backed_storyboard()
    storyboard["evidence_registry"]["targets"].append({
        "id": "cell-probability-shift", "kind": "notebook_cell", "present": True,
    })
    storyboard["source_context"]["analyses"] = [{
        "section_type": "advanced_visual",
        "visual_author_section_id": "probability-shift",
        "title": "Probability movement",
        "caption": "Supplied aggregate comparison.",
        "interpretation": "The supplied leader changed.",
        "records": [
            {"team": f"Team {index}", "before": index / 100, "after": (index + 3) / 100}
            for index in range(75)
        ],
        "visual": {"type": "slopegraph", "label": "team", "start": "before", "end": "after"},
        "evidence": [{"kind": "notebook_cell", "ref": "cell-probability-shift"}],
    }]

    dossier, contract = build_creative_author_dossier(storyboard, {"max_dossier_chars": 180_000})

    assert '"included_row_count": 60' in dossier
    assert '"row_count": 75' in dossier
    assert '"team": "Team 0"' in dossier
    assert '"team": "Team 59"' in dossier
    assert '"team": "Team 60"' not in dossier
    assert '"type": "slopegraph"' in dossier
    assert "cell-probability-shift" in dossier
    assert {item["alias"] for item in contract["sources"]} == {"src-finding-1", "src-asset-1"}
    assert {item["alias"] for item in contract["evidence"]} == {"ev-1", "ev-2"}


def test_full_document_validator_enforces_source_coverage_evidence_and_safe_javascript():
    dossier, contract = build_creative_author_dossier(_ledger_backed_storyboard())
    assert dossier
    validated = validate_authored_document(_authored_html(), contract)
    assert validated["coverage"]["used"] == ["src-finding-1"]
    assert validated["evidence_aliases"] == ["ev-1"]

    interactive = _authored_html().replace(
        "</body>",
        '<script data-dc-author-script>document.querySelector("h1").addEventListener("click", function () { document.querySelector("h1").textContent = "Customer intervention brief"; });</script></body>',
    )
    assert validate_authored_document(interactive, contract)["script_count"] == 1

    unknown = _authored_html().replace('data-evidence="ev-1"', 'data-evidence="ev-99"')
    with pytest.raises(ValueError, match="unknown evidence aliases"):
        validate_authored_document(unknown, contract)

    uncovered = _authored_html().replace('data-source="src-finding-1"', "")
    with pytest.raises(ValueError, match="use or explicitly omit every source"):
        validate_authored_document(uncovered, contract)

    unsafe = _authored_html().replace(
        "</body>",
        '<script data-dc-author-script>fetch("https://example.test/data")</script></body>',
    )
    with pytest.raises(ValueError, match="artifact safety failed: live_data_call"):
        validate_authored_document(unsafe, contract)


@pytest.mark.asyncio
async def test_creative_author_runs_one_evidence_repair_pass():
    storyboard = _ledger_backed_storyboard()
    original_html = _authored_html(claim="The evidence proves onboarding caused the renewal gap.")
    repaired_html = _authored_html(claim="The supplied finding identifies the earliest customer window as the intervention priority.")
    llm = _JSONLLM((
        original_html,
        {
            "status": "attention_required",
            "findings": [{
                "anchor": "claim-1",
                "evidence_aliases": ["ev-1"],
                "issue": "The descriptive finding was rewritten as a causal claim.",
                "recommendation": "Remove the causal attribution.",
            }],
        },
        repaired_html,
        {"status": "pass", "findings": []},
    ))

    authored, record = await author_report_visuals(
        storyboard,
        config={"mode": "creative", "max_repair_passes": 1},
        llm=llm,
    )

    assert record["status"] == "applied"
    assert record["repair_count"] == 1
    assert record["evidence_review"]["status"] == "pass"
    assert llm.calls == 4
    assert "caused the renewal gap" not in authored["authored_document"]["html"]


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
async def test_default_visual_author_records_the_deterministic_desktop_baseline():
    config = visual_author_config({})
    assert config == {"mode": "off", "baseline": "deterministic_desktop_editorial"}

    authored, record = await author_report_visuals(_storyboard(), config=config)

    assert record["mode"] == "off"
    assert record["status"] == "disabled"
    assert record["baseline"] == "deterministic_desktop_editorial"
    assert record["source"] == "renderer"
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


@pytest.mark.asyncio
async def test_default_handcrafted_report_uses_available_llm_as_bounded_visual_author(cfg, tmp_path, monkeypatch):
    import dataclaw.config.paths as paths

    monkeypatch.setattr(paths, "DATACLAW_HOME", tmp_path)
    result = await report_design_report(
        cfg=cfg,
        llm=_JSONLLM({
            "schema": 1,
            "theme": "plum",
            "sections": [{"section_id": "opening_context", "surface": "strong"}],
            "insights": [],
        }),
        report_goal="Explain the completed finding.",
        report_path="reports/default-authored.html",
        storyboard_path="reports/default-authored.storyboard.json",
        quality_gate="warn",
        insights=[{"title": "Finding complete", "detail": "The supplied finding is ready."}],
    )

    assert result["presentation_mode"] == "handcrafted"
    assert result["visual_author"]["mode"] == "runtime"
    assert result["visual_author"]["status"] == "applied"
    assert "--dc-accent: #6d28d9" in Path(result["html_path"]).read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_default_handcrafted_report_gives_llm_creative_freedom_when_ledger_exists(
    cfg, tmp_path, monkeypatch,
):
    import dataclaw.config.paths as paths

    monkeypatch.setattr(paths, "DATACLAW_HOME", tmp_path)
    result = await report_design_report(
        cfg=cfg,
        llm=_JSONLLM((_authored_html(title="Ledger-backed finding"), {"status": "pass", "findings": []})),
        report_goal="Explain the completed ledger-backed finding.",
        report_path="reports/default-creative.html",
        storyboard_path="reports/default-creative.storyboard.json",
        quality_gate="fail",
        insights=[{
            "finding_id": "finding-complete",
            "title": "Finding complete",
            "detail": "The supplied ledger-backed finding is ready.",
        }],
    )

    assert result["presentation_mode"] == "handcrafted"
    assert result["visual_author"]["mode"] == "creative"
    assert result["visual_author"]["status"] == "applied"
    html = Path(result["html_path"]).read_text(encoding="utf-8")
    assert 'data-dc-authored-document="true"' in html
    assert "The earliest customer window deserves" in html
    assert Path(result["authoring_dossier_path"]).is_file()
    assert "finding-complete" in Path(result["authoring_dossier_path"]).read_text(encoding="utf-8")
    storyboard = json.loads(Path(result["storyboard_path"]).read_text(encoding="utf-8"))
    assert storyboard["evidence_registry"]["targets"][0]["id"] == "finding-complete"
    assert "dossier" not in storyboard["authored_document"]
    assert storyboard["authored_document"]["evidence_review"]["status"] == "pass"


@pytest.mark.asyncio
async def test_report_design_rejects_explicit_creative_mode_without_ledger(cfg, tmp_path, monkeypatch):
    import dataclaw.config.paths as paths

    monkeypatch.setattr(paths, "DATACLAW_HOME", tmp_path)
    with pytest.raises(ValueError, match="requires a non-empty evidence ledger"):
        await report_design_report(
            cfg=cfg,
            llm=_JSONLLM({"schema": 1, "sections": [], "insights": []}),
            report_goal="Explain a supplied observation without a stable finding id.",
            report_path="reports/creative-without-ledger.html",
            storyboard_path="reports/creative-without-ledger.storyboard.json",
            quality_gate="off",
            insights=[{"title": "Observation", "detail": "No stable evidence target was supplied."}],
            visual_author={"mode": "creative"},
        )


@pytest.mark.asyncio
async def test_full_document_authored_report_survives_publication_revalidation(cfg, tmp_path, monkeypatch):
    import dataclaw.config.paths as paths

    monkeypatch.setattr(paths, "DATACLAW_HOME", tmp_path)
    designed = await report_design_report(
        cfg=cfg,
        llm=_JSONLLM((_authored_html(title="Published evidence brief"), {"status": "pass", "findings": []})),
        report_goal="Publish the completed evidence-backed finding.",
        report_path="reports/authored-publish.html",
        storyboard_path="reports/authored-publish.storyboard.json",
        quality_gate="warn",
        insights=[{
            "finding_id": "finding-publish",
            "title": "Publishable finding",
            "detail": "The completed finding is ready for an editorial report.",
        }],
    )

    async def passed_smoke(_path):
        return {
            "status": "passed",
            "checks": [],
            "screenshots": [],
            "semantic_visual": {"visual_semantic_schema": 1, "status": "pass", "findings": []},
        }

    monkeypatch.setattr(workspace_tools, "_run_report_runtime_smoke", passed_smoke)
    published = await report_publish(
        cfg=cfg,
        report_path="reports/authored-publish.html",
        storyboard_path="reports/authored-publish.storyboard.json",
        export_docx=False,
    )

    assert published["publication_status"] == "published"
    assert published["quality"]["rubric_version"] == 12
    assert published["quality"]["status"] in {"pass", "warn"}
    receipt = json.loads(Path(published["receipt_path"]).read_text(encoding="utf-8"))
    assert designed["html_sha256"] == receipt["html_sha256"]
