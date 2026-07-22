"""Tests for full-document creative authoring under the single-path contract."""

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
    author_report_visuals,
    build_creative_author_dossier,
    validate_authored_document,
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


def test_creative_author_requires_non_empty_evidence_ledger():
    with pytest.raises(ValueError, match="non-empty evidence ledger"):
        build_creative_author_dossier(_storyboard())


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
            {"team": f"Team {index}", "before": index / 1000, "after": (index + 3) / 1000}
            for index in range(250)
        ],
        "visual": {"type": "slopegraph", "label": "team", "start": "before", "end": "after"},
        "evidence": [{"kind": "notebook_cell", "ref": "cell-probability-shift"}],
    }]

    dossier, contract = build_creative_author_dossier(storyboard, {"max_dossier_chars": 300_000})

    # Aggregates are bounded (no raw-data dumps) but generously — 200 rows.
    assert '"included_row_count": 200' in dossier
    assert '"row_count": 250' in dossier
    assert '"team": "Team 0"' in dossier
    assert '"team": "Team 199"' in dossier
    assert '"team": "Team 200"' not in dossier
    assert '"type": "slopegraph"' in dossier
    assert "cell-probability-shift" in dossier
    assert {item["alias"] for item in contract["sources"]} == {"src-finding-1", "src-asset-1"}
    assert {item["alias"] for item in contract["evidence"]} == {"ev-1", "ev-2"}


def test_bespoke_visual_intent_reaches_dossier_without_governed_vocabulary():
    """A custom visual type or explicit visual_direction must survive to the author.

    An unsupported ``visual.type`` is bespoke intent, not an error: it folds into
    free-text ``visual_direction`` rather than failing the closed advanced-visual
    validator. A per-asset ``visual_direction``/``medium`` also reaches the dossier.
    """
    requirements = {"evidence_registry": {"targets": [
        {"id": "cell-paths", "kind": "notebook_cell"},
    ]}}
    storyboard = design_report_storyboard(
        report_goal="Explain how the draw reshaped contender paths.",
        title="Draw",
        insights=[{
            "finding_id": "find-paths",
            "title": "The draw reordered contenders",
            "detail": "Bracket structure favors the top seed.",
            "evidence": [{"kind": "notebook_cell", "ref": "cell-paths"}],
        }],
        analyses=[
            {   # unsupported visual.type must NOT raise; it becomes bespoke intent
                "title": "Tournament paths",
                "caption": "Contender paths through the bracket.",
                "interpretation": "The bracket favors the top seed.",
                "records": [{"team": "A", "prob": 0.4}, {"team": "B", "prob": 0.2}],
                "visual": {"type": "radial_tree", "description": "annotated radial bracket"},
                "required_visual": True,
                "evidence": [{"kind": "notebook_cell", "ref": "cell-paths"}],
            },
            {   # explicit per-asset direction + medium, no governed type
                "title": "Momentum",
                "caption": "Momentum across rounds.",
                "interpretation": "Momentum swung in the late rounds.",
                "visual_direction": "Build an annotated SVG streamgraph of momentum.",
                "medium": "svg",
                "records": [{"round": 1, "value": 3}, {"round": 2, "value": 5}],
                "evidence": [{"kind": "notebook_cell", "ref": "cell-paths"}],
            },
        ],
        requirements=requirements,
        max_design_passes=1,
    )
    storyboard["evidence_registry"] = build_evidence_registry(storyboard)

    dossier, _ = build_creative_author_dossier(storyboard, {"mode": "creative"})

    # Unsupported type folded into bespoke direction, not rejected.
    assert "radial_tree" in dossier
    assert "bespoke" in dossier.lower()
    # Per-asset direction and medium survive to the author.
    assert "streamgraph" in dossier
    assert '"visual_medium": "svg"' in dossier


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


def test_full_document_validator_preserves_explicitly_required_visual_assets():
    storyboard = design_report_storyboard(
        report_goal="Show the validated comparison.",
        title="Required comparison",
        insights=[{
            "finding_id": "find-required",
            "title": "A is higher",
            "detail": "A has the higher supplied value.",
            "evidence": [{"kind": "notebook_cell", "ref": "cell-required"}],
        }],
        analyses=[{
            "id": "comparison-asset",
            "required_visual": True,
            "title": "Validated comparison",
            "records": [{"label": "A", "value": 2}, {"label": "B", "value": 1}],
            "evidence": [{"kind": "notebook_cell", "ref": "cell-required"}],
        }],
        requirements={
            "evidence_registry": {
                "targets": [{"id": "cell-required", "kind": "notebook_cell", "present": True}],
            },
        },
    )
    storyboard["evidence_registry"] = build_evidence_registry(storyboard)
    _, contract = build_creative_author_dossier(storyboard)

    omitted = _authored_html().replace(
        '{"omitted":[]}',
        '{"omitted":[{"source":"src-asset-1","reason":"Not selected for the story."}]}',
    )
    with pytest.raises(ValueError, match="required visual sources cannot be omitted"):
        validate_authored_document(omitted, contract)

    used_as_prose = _authored_html().replace(
        'data-source="src-finding-1"',
        'data-source="src-finding-1 src-asset-1"',
    )
    with pytest.raises(ValueError, match="did not render required visual sources"):
        validate_authored_document(used_as_prose, contract)

    rendered = _authored_html().replace(
        '<figure data-evidence="ev-1">',
        '<figure data-source="src-asset-1" data-evidence="ev-1">',
    )
    validated = validate_authored_document(rendered, contract)
    assert validated["coverage"]["visual_sources"] == ["src-asset-1"]


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
async def test_visual_author_rejects_non_creative_modes():
    for mode in ("runtime", "provided", "off", "required"):
        with pytest.raises(ValueError, match="must be 'creative'"):
            await author_report_visuals(_ledger_backed_storyboard(), config={"mode": mode})


@pytest.mark.asyncio
async def test_creative_author_fails_closed_without_llm_or_ledger():
    ledgered = _ledger_backed_storyboard()
    with pytest.raises(VisualAuthorRequiredError) as failed:
        await author_report_visuals(ledgered, config={"mode": "creative"})
    assert failed.value.reason.startswith("No LLM provider")
    assert failed.value.record["mode"] == "creative"

    with pytest.raises(VisualAuthorRequiredError, match="non-empty evidence ledger"):
        await author_report_visuals(
            _storyboard(),
            config={"mode": "creative"},
            llm=_JSONLLM(_authored_html()),
        )


def test_authoring_review_requires_typed_facts_when_creative_visuals_are_requested():
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
async def test_report_design_persists_creative_visual_author_failure_audit(cfg, tmp_path, monkeypatch):
    import dataclaw.config.paths as paths

    monkeypatch.setattr(paths, "DATACLAW_HOME", tmp_path)
    # A ledger-backed finding reaches the creative author, but no LLM is
    # available, so authoring fails closed and an audit record is persisted.
    with pytest.raises(ValueError, match="Failure audit"):
        await report_design_report(
            cfg=cfg,
            report_goal="Decide whether an intervention is needed.",
            title="Creative visual author",
            report_path="reports/required.html",
            storyboard_path="reports/required.storyboard.json",
            quality_gate="off",
            insights=[{
                "finding_id": "finding-complete",
                "title": "A completed insight",
                "detail": "The evidence is ready.",
            }],
        )

    audit = tmp_path / "workspaces" / "default" / "reports" / "required.storyboard.visual-author-failure.json"
    payload = json.loads(audit.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["visual_author"]["mode"] == "creative"


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
    assert published["quality"]["rubric_version"] == 15
    assert published["quality"]["status"] in {"pass", "warn"}
    receipt = json.loads(Path(published["receipt_path"]).read_text(encoding="utf-8"))
    assert designed["html_sha256"] == receipt["html_sha256"]
