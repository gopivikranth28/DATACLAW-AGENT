"""Tests for full-document creative authoring under the single-path contract."""

from __future__ import annotations

import json
from pathlib import Path
import re

import pytest

from dataclaw.providers.llm.provider import TextDeltaEvent, TurnCompleteEvent
from dataclaw.tool_progress import tool_progress_context
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
async def test_creative_author_emits_real_phase_and_output_progress():
    updates: list[dict] = []
    llm = _JSONLLM((_authored_html(), {"status": "pass", "findings": []}))

    with tool_progress_context(updates.append):
        await author_report_visuals(_ledger_backed_storyboard(), llm=llm)

    phases = [update["phase"] for update in updates]
    assert phases[0] == "preparing"
    assert "drafting" in phases
    assert "validating" in phases
    assert "reviewing" in phases
    assert phases[-1] == "finalizing"
    drafting = [update for update in updates if update["phase"] == "drafting"]
    assert any(update.get("activity") == "receiving" for update in drafting)
    assert max(update.get("outputChars", 0) for update in drafting) > 0


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
    )
    storyboard["evidence_registry"] = build_evidence_registry(storyboard)

    dossier, _ = build_creative_author_dossier(storyboard, {"mode": "creative"})

    # Unsupported type folded into bespoke direction, not rejected.
    assert "radial_tree" in dossier
    assert "bespoke" in dossier.lower()
    # Per-asset direction and medium survive to the author.
    assert "streamgraph" in dossier
    assert '"visual_medium": "svg"' in dossier


def test_lean_storyboard_shape_and_enriched_dossier():
    """The storyboard is a lean evidence contract; the dossier is detail-rich."""
    requirements = {
        "evidence_registry": {"targets": [{"id": "ev-1", "kind": "notebook_cell"}]},
        "rigor": {"require_methodology": True, "require_uncertainty": True},
        "decision": "Which cohort to prioritize for intervention.",
        "hypotheses": [{"statement": "New cohort churns first", "disposition": "confirmed"}],
    }
    storyboard = design_report_storyboard(
        report_goal="Prioritize the intervention.",
        title="Cohort report",
        requirements=requirements,
        insights=[{
            "finding_id": "f1", "title": "New cohort churns first",
            "detail": "The first-90-day cohort has the lowest renewal.",
            "confidence": "high", "importance": 1,
            "recommendation": "Prioritize onboarding fixes.", "hypothesis_id": "hyp-1",
            "evidence": [{"kind": "notebook_cell", "ref": "ev-1"}],
        }],
        analyses=[{
            "title": "Renewal by cohort", "caption": "c", "interpretation": "i",
            "records": [{"cohort": "0-90", "rate": 0.4}],
            "baseline": "prior year", "time_window": "2025", "aggregation": "mean",
            "evidence": [{"kind": "notebook_cell", "ref": "ev-1"}],
        }],
    )

    # Lean storyboard: only the evidence/requirements contract, no page furniture.
    assert storyboard["storyboard_schema"] == 2
    assert set(storyboard) == {
        "storyboard_schema", "title", "report_goal", "audience",
        "source_context", "analysis_contract", "evidence_registry", "quality_plan", "section_plan",
    }
    roles = [s["layout_role"] for s in storyboard["section_plan"]]
    assert "primary_insights" in roles
    assert not any(r in roles for r in ("opening_context", "executive_kpis", "executive_readout",
                                        "methodology", "data_quality", "uncertainty", "evidence_trace"))

    storyboard["evidence_registry"] = build_evidence_registry(storyboard)
    dossier, _ = build_creative_author_dossier(storyboard, {"mode": "creative"})
    # Detail-rich: decision, required disclosures, per-finding + per-asset analytics.
    for token in ('"decision"', "required_disclosures", "methodology: grain",
                  "uncertainty: intervals", '"confidence"', '"importance"',
                  '"recommendation"', '"hypothesis"', '"baseline"', '"time_window"',
                  '"aggregation"', "coverage_instruction"):
        assert token in dossier, f"dossier missing {token}"


class _StreamLLM:
    """Streams a scripted sequence per call; an exception entry is raised mid-stream."""

    def __init__(self, *scripts):
        # each script is a list of str deltas or an Exception to raise after them
        self.scripts = list(scripts)
        self.calls = 0

    async def stream_turn(self, messages, *, system, tools, **kwargs):
        script = self.scripts[self.calls]
        self.calls += 1
        for item in script:
            if isinstance(item, Exception):
                yield TextDeltaEvent(text="<partial-that-must-be-discarded>")
                raise item
            yield TextDeltaEvent(text=item)
        yield TurnCompleteEvent()


class _DroppedConnection(Exception):
    """Named to match the transient-stream classifier (like httpx.RemoteProtocolError)."""


RemoteProtocolError = type("RemoteProtocolError", (Exception,), {})


@pytest.mark.asyncio
async def test_stream_text_retries_transient_drop_and_discards_partial(monkeypatch):
    from dataclaw_workspace import visual_author as va

    monkeypatch.setattr(va, "_STREAM_RETRY_BACKOFF_SECONDS", 0)
    # Attempt 1 drops mid-stream with a transient error; attempt 2 completes.
    llm = _StreamLLM([RemoteProtocolError("peer closed connection")], ["FINAL-DOC"])
    out = await va._stream_text(
        llm, system="s", prompt="p", timeout_seconds=30, max_output_chars=1000,
        reasoning_effort="medium", text_verbosity="high",
        progress_phase="drafting", progress_label="x",
    )
    assert out == "FINAL-DOC"  # the discarded partial does not leak in
    assert llm.calls == 2


@pytest.mark.asyncio
async def test_stream_text_does_not_retry_deterministic_errors(monkeypatch):
    from dataclaw_workspace import visual_author as va

    monkeypatch.setattr(va, "_STREAM_RETRY_BACKOFF_SECONDS", 0)
    # A non-transport error is not retried — it raises on the first attempt.
    llm = _StreamLLM([ValueError("bad request")], ["never reached"])
    with pytest.raises(ValueError, match="bad request"):
        await va._stream_text(
            llm, system="s", prompt="p", timeout_seconds=30, max_output_chars=1000,
            reasoning_effort="medium", text_verbosity="high",
            progress_phase="drafting", progress_label="x",
        )
    assert llm.calls == 1


@pytest.mark.asyncio
async def test_stream_text_gives_up_after_exhausting_transient_retries(monkeypatch):
    from dataclaw_workspace import visual_author as va

    monkeypatch.setattr(va, "_STREAM_RETRY_BACKOFF_SECONDS", 0)
    drops = [[RemoteProtocolError("drop")] for _ in range(va._STREAM_RETRY_ATTEMPTS)]
    llm = _StreamLLM(*drops)
    with pytest.raises(RemoteProtocolError):
        await va._stream_text(
            llm, system="s", prompt="p", timeout_seconds=30, max_output_chars=1000,
            reasoning_effort="medium", text_verbosity="high",
            progress_phase="drafting", progress_label="x",
        )
    assert llm.calls == va._STREAM_RETRY_ATTEMPTS


@pytest.mark.asyncio
async def test_creative_author_repairs_a_structurally_invalid_first_draft():
    """A malformed first draft (e.g. no <h1>) is repaired, not fatal."""
    storyboard = _ledger_backed_storyboard()
    # Strip the hero heading entirely: zero <h1> is a structural failure (a
    # truncated document), unlike a mere duplicate heading which is now allowed.
    bad = _authored_html().replace("<h1>", "<p>").replace("</h1>", "</p>")
    good = _authored_html()
    llm = _JSONLLM((bad, good, {"status": "pass", "findings": []}))

    authored, record = await author_report_visuals(storyboard, config={"mode": "creative"}, llm=llm)

    assert record["status"] == "applied"
    assert record["repair_count"] == 1
    assert authored["authored_document"]["html"] == good
    # author draft + structural repair + evidence review
    assert llm.calls == 3


@pytest.mark.asyncio
async def test_creative_author_fails_closed_when_structure_never_recovers():
    storyboard = _ledger_backed_storyboard()
    bad = _authored_html().replace("<h1>", "<p>").replace("</h1>", "</p>")  # no h1 -> structural fail
    llm = _JSONLLM((bad, bad))  # budget=1 -> one repair, then give up
    with pytest.raises(VisualAuthorRequiredError, match="structural validation"):
        await author_report_visuals(storyboard, config={"mode": "creative", "max_repair_passes": 1}, llm=llm)


def test_structural_validation_allows_extra_headings_but_requires_at_least_one():
    from dataclaw_workspace.visual_author import validate_authored_document, build_creative_author_dossier

    storyboard = _ledger_backed_storyboard()
    storyboard["evidence_registry"] = build_evidence_registry(storyboard)
    _, contract = build_creative_author_dossier(storyboard, {"mode": "creative"})

    # A second hero heading and a second <title> are a polish/accessibility
    # nuance judged at the visual-review layer, not a hard structural failure.
    two = _authored_html().replace("<h1>", "<h1>Section</h1><h1>", 1).replace(
        "</head>", "<title>Extra</title></head>", 1
    )
    result = validate_authored_document(two, contract)
    assert result["script_count"] >= 0  # validated without raising

    # But zero <h1> (a truncated document) still fails closed.
    none = _authored_html().replace("<h1>", "<p>").replace("</h1>", "</p>")
    with pytest.raises(ValueError, match="at least one title, and at least one h1"):
        validate_authored_document(none, contract)

    # An accessible <svg><title> chart label must NOT count as a document title
    # (it used to inflate the count and fail the gate). The single <head> title
    # plus an SVG title still validates cleanly.
    with_svg_title = _authored_html().replace(
        "<svg viewBox=\"0 0 400 120\" role=\"img\" aria-label=\"Evidence emphasis\">",
        "<svg viewBox=\"0 0 400 120\" role=\"img\"><title>Evidence emphasis</title>",
        1,
    )
    assert with_svg_title.count("<title>") == 2  # one head, one svg
    validate_authored_document(with_svg_title, contract)  # does not raise


def test_visual_author_config_clamps_out_of_range_tuning_instead_of_failing():
    from dataclaw_workspace.visual_author import visual_author_config

    # An out-of-range knob is clamped, not fatal (the production retry bug).
    assert visual_author_config({}, {"mode": "creative", "max_repair_passes": 99})["max_repair_passes"] == 3
    # A non-integer knob falls back to the default.
    assert visual_author_config({}, {"mode": "creative", "max_repair_passes": "lots"})["max_repair_passes"] == 2
    assert visual_author_config({}, {"mode": "creative", "timeout_seconds": 100000})["timeout_seconds"] == 900
    # Tiny values clamp UP to a usable floor, never a guaranteed-failure setting.
    assert visual_author_config({}, {"mode": "creative", "timeout_seconds": 1})["timeout_seconds"] == 60
    assert visual_author_config({}, {"mode": "creative", "max_output_chars": 100})["max_output_chars"] == 50_000


def test_disclosure_markers_require_visible_text_and_verified_semantics():
    from dataclaw_workspace.visual_author import _AuthoredDocumentParser

    def disclosures(html: str):
        parser = _AuthoredDocumentParser()
        parser.feed(html)
        parser.close()
        return sorted(parser.disclosures)

    # Ineligible markers are silently NOT credited (never fatal) — the honest
    # rigor warning stays instead. An inert <meta> is not a leaf text block.
    assert disclosures('<meta data-dc-disclosure="methodology data_quality uncertainty">') == []
    # A marker on a wrapping <div> is not credited even if the div contains text.
    assert disclosures(
        '<div data-dc-disclosure="data_quality">Coverage excludes churned accounts entirely.</div>'
    ) == []
    # A hidden / inert marker is not credited, even on a valid text block.
    assert disclosures('<p hidden data-dc-disclosure="data_quality">Coverage excludes churned accounts entirely.</p>') == []
    assert disclosures(
        '<p style="display:none" data-dc-disclosure="data_quality">Coverage excludes churned accounts entirely.</p>'
    ) == []
    # A nested marker inside another disclosure element cannot double-collect text.
    assert disclosures(
        '<p data-dc-disclosure="data_quality">Coverage excludes churned accounts entirely.'
        '<span data-dc-disclosure="uncertainty">and more</span></p>'
    ) == ["data_quality"]
    # Methodology is credited only when its three parts are visibly present —
    # matched by concept, so natural prose ("each row", "per") is accepted.
    assert disclosures(
        '<p data-dc-disclosure="methodology">Each row is a customer-month; rates are per '
        "eligible renewal, and figures were reconciled against invoices.</p>"
    ) == ["methodology"]
    # Prose missing a part (no validation) is not credited as methodology.
    assert disclosures(
        '<p data-dc-disclosure="methodology">Each row is a customer-month measured per eligible renewal.</p>'
    ) == []
    # Below the minimum length, even a well-formed marker is not credited.
    assert disclosures('<p data-dc-disclosure="data_quality">Excludes churn.</p>') == []
    assert disclosures('<p data-dc-disclosure="uncertainty"></p>') == []
    # A substantial data-quality note on a leaf block is credited.
    assert disclosures(
        '<p data-dc-disclosure="data_quality">Coverage excludes churned accounts and trial users.</p>'
    ) == ["data_quality"]


def test_data_decoration_is_not_inherited_and_cannot_cloak_a_data_visual():
    from dataclaw_workspace.visual_author import _AuthoredDocumentParser

    def unbound(html: str):
        parser = _AuthoredDocumentParser()
        parser.feed(html)
        parser.close()
        return parser.visuals_without_evidence

    # An ancestor data-decoration must NOT exempt a descendant visual.
    assert unbound('<div data-decoration="true"><figure><svg></svg></figure></div>') == ["figure"]
    # A genuinely decorative figure (own marker) is exempt; its inner svg is content.
    assert unbound('<figure data-decoration="true"><svg></svg></figure>') == []
    # A figure with its own evidence is bound.
    assert unbound('<figure data-evidence="ev-1"><svg></svg></figure>') == []
    # A decoration visual cannot also carry data-source (data-bound => not decorative).
    parser = _AuthoredDocumentParser()
    with pytest.raises(ValueError, match="cannot also carry data-source"):
        parser.feed('<figure data-decoration="true" data-source="src-1"><svg></svg></figure>')


def test_bespoke_visual_without_records_renders_instead_of_aborting():
    storyboard = design_report_storyboard(
        report_goal="Explain the bracket.",
        title="Bracket",
        requirements={"evidence_registry": {"targets": [{"id": "ev-1", "kind": "notebook_cell"}]}},
        insights=[{"finding_id": "f1", "title": "Seed A favored", "detail": "Bracket favors seed A.",
                   "evidence": [{"kind": "notebook_cell", "ref": "ev-1"}]}],
        analyses=[{  # explicit advanced_visual, unsupported type, NO records
            "section_type": "advanced_visual", "title": "Bracket map", "caption": "c",
            "interpretation": "The bracket structure favors the top seed.",
            "visual": {"type": "radial_tournament"},
            "evidence": [{"kind": "notebook_cell", "ref": "ev-1"}],
        }],
    )
    kinds = [s["section_type"] for s in storyboard["section_plan"]]
    assert "chart_interpretation" in kinds  # rendered, not aborted


def test_publish_integrity_helpers_block_authored_tampering():
    from dataclaw_workspace.tools import _scan_authored_extra_js, _require_authored_publish_integrity

    authored = '<html data-dc-authored-document="true"><body>{}</body></html>'
    # Authored-extra JS in an executable script is rejected; prose/JSON is not.
    with pytest.raises(ValueError, match="forbidden"):
        _scan_authored_extra_js(authored.format('<script>document.cookie="x"</script>'))
    _scan_authored_extra_js(authored.format('<p>We import data.</p><script type="application/json">{"k":"eval"}</script>'))
    # Missing embedded ledger / failed evidence review are blocked at publish.
    with pytest.raises(ValueError, match="evidence-ledger targets"):
        _require_authored_publish_integrity(authored.format("<h1>r</h1>"))
    full = authored.format(
        '<script type="application/json" data-dc-evidence-registry>{"targets":[{"id":"ev-1"}]}</script>'
        '<script type="application/json" data-dc-author-coverage>{"coverage_schema":1,"used":["s"],"omitted":[]}</script>'
        '<script type="application/json" data-dc-evidence-review>{"schema":1,"status":"%s"}</script>'
    )
    with pytest.raises(ValueError, match="evidence review did not pass"):
        _require_authored_publish_integrity(full % "attention_required")
    _require_authored_publish_integrity(full % "pass")  # valid authored doc passes
    # Enforcement is unconditional: it does NOT gate on a self-declared marker, so
    # a doc missing the embedded evidence integrity is blocked regardless of any
    # (spoofable) authoredness attribute or its quoting.
    with pytest.raises(ValueError, match="evidence-ledger targets"):
        _require_authored_publish_integrity("<html data-dc-authored-document='true'><body>x</body></html>")


def test_repair_prompt_is_bounded_to_the_context_budget():
    from dataclaw_workspace.visual_author import _bounded_repair_prompt

    findings = [{"issue": "unsupported claim", "recommendation": "cite evidence"}]
    # Dossier fits: prompt keeps the full dossier.
    fits = _bounded_repair_prompt("D" * 1_000, findings, "<html></html>", max_chars=700_000)
    assert fits is not None and fits.startswith("D" * 1_000)
    # Dossier too large: trimmed to fit, HTML + findings preserved.
    trimmed = _bounded_repair_prompt("D" * 900_000, findings, "<html></html>", max_chars=100_000)
    assert trimmed is not None and len(trimmed) <= 100_200
    assert "dossier trimmed to fit the repair context" in trimmed
    assert "<html></html>" in trimmed
    # HTML alone exceeds the budget: skip the repair (fail-closed at the gate).
    assert _bounded_repair_prompt("D" * 1_000, findings, "H" * 200_000, max_chars=100_000) is None


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
async def test_render_injects_host_scripts_when_metadata_has_unicode():
    # A title/goal with a Unicode em dash is serialized as — in the injected
    # JSON host scripts. The injection must treat that string literally, not as a
    # regex replacement (which raised re.error: "bad escape \\u").
    storyboard = design_report_storyboard(
        report_goal="F1 dominance — eras, money, and the 2023 peak — a résumé.",
        title="F1 Driver Trends — Eras, Dominance, and the 2023 Peak",
        insights=[{
            "finding_id": "find-new-customers",
            "title": "New customers have the weakest renewal rate",
            "detail": "The first-90-day cohort has the lowest renewal rate.",
        }],
    )
    storyboard["evidence_registry"] = build_evidence_registry(storyboard)
    llm = _JSONLLM((_authored_html(), {"status": "pass", "findings": []}))
    authored, _ = await author_report_visuals(storyboard, llm=llm)

    html = render_report_from_storyboard(authored)  # must not raise "bad escape \\u"

    assert "data-dc-section-meta" in html
    assert "data-dc-evidence-registry" in html
    # The em dash survives into the injected JSON as an escaped code point.
    assert "\\u2014" in html


def test_safe_modern_css_is_not_flagged_as_executable_but_legacy_vectors_are():
    dossier, contract = build_creative_author_dossier(_ledger_backed_storyboard())

    # scroll-behavior / overscroll-behavior are safe modern properties that used
    # to trip the "behavior:" executable-CSS pattern and fail whole reports.
    safe = _authored_html().replace(
        "body{margin:0",
        "html{scroll-behavior:smooth}body{overscroll-behavior:contain;margin:0",
        1,
    )
    assert validate_authored_document(safe, contract)["coverage"]["used"] == ["src-finding-1"]

    # A genuine executable-CSS vector (IE expression()) is still rejected.
    unsafe = _authored_html().replace(
        "margin:0", "width:expression(alert(1));margin:0", 1
    )
    with pytest.raises(ValueError, match="forbidden executable CSS"):
        validate_authored_document(unsafe, contract)


def test_css_content_is_not_gated_evidence_discipline_lives_elsewhere():
    dossier, contract = build_creative_author_dossier(_ledger_backed_storyboard())

    # There is no `content:` gate: decorative content, the justify-content /
    # align-content layout properties, and even textual content: all validate.
    # A surface CSS scan cannot soundly tell a decorative label from a smuggled
    # claim (CSS escapes defeat it), and evidence discipline is enforced on the
    # DOM claims, not the decorative CSS layer.
    for snippet in (
        'body{display:flex;justify-content:space-between;align-content:center;margin:0',
        '.tick::before{content:"\\25b8"}.q::after{content:""}.n::before{content:"Figure " counter(step)}\nbody{margin:0',
        '.k::after{content:"43% lift vs prior"}body{margin:0',
    ):
        html = _authored_html().replace("body{margin:0", snippet, 1)
        validate_authored_document(html, contract)  # does not raise


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


def test_authoring_review_requires_typed_facts_when_display_facts_are_required():
    storyboard = _storyboard()
    storyboard["source_context"]["requirements"]["presentation"] = {"require_display_facts": True}
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


@pytest.mark.asyncio
async def test_report_publish_reruns_artifact_safety_on_the_stored_html(cfg, tmp_path, monkeypatch):
    """A hash-consistent report/storyboard pair with a remote asset must not publish.

    Simulates a report authored under an older policy (or a jointly edited
    report/storyboard pair): the stored HTML embeds a remote asset and the
    storyboard hash matches it, so the integrity gate passes — but publication
    must re-run artifact-safety under the current policy and fail closed.
    """
    import hashlib as _hashlib

    import dataclaw.config.paths as paths

    monkeypatch.setattr(paths, "DATACLAW_HOME", tmp_path)
    await report_design_report(
        cfg=cfg,
        llm=_JSONLLM((_authored_html(title="Older-policy report"), {"status": "pass", "findings": []})),
        report_goal="Publish an older-policy report.",
        report_path="reports/legacy.html",
        storyboard_path="reports/legacy.storyboard.json",
        quality_gate="warn",
        insights=[{"finding_id": "f-legacy", "title": "Finding", "detail": "Ready to publish."}],
    )

    html_path = tmp_path / "workspaces" / "default" / "reports" / "legacy.html"
    storyboard_path = tmp_path / "workspaces" / "default" / "reports" / "legacy.storyboard.json"
    tampered = html_path.read_text(encoding="utf-8").replace(
        "</body>", '<img src="https://evil.example/x.png"></body>'
    )
    html_path.write_text(tampered, encoding="utf-8")
    storyboard = json.loads(storyboard_path.read_text(encoding="utf-8"))
    # Re-sign the hash so the integrity gate passes and the safety gate is reached.
    storyboard["rendered_html_sha256"] = _hashlib.sha256(tampered.encode("utf-8")).hexdigest()
    storyboard_path.write_text(json.dumps(storyboard), encoding="utf-8")

    with pytest.raises(ValueError, match="artifact-safety gate failed"):
        await report_publish(
            cfg=cfg,
            report_path="reports/legacy.html",
            storyboard_path="reports/legacy.storyboard.json",
            export_docx=False,
        )


def test_bespoke_fold_minimizes_unmapped_columns_and_handles_explicit_advanced_visual():
    """Folding an unsupported visual must project only mapped columns (no PII leak)
    and must work whether the asset is untyped or explicitly typed advanced_visual."""
    from dataclaw_workspace.report_renderer import design_report_storyboard

    reqs = {"evidence_registry": {"targets": [{"id": "ev-1", "kind": "notebook_cell"}]}}
    insights = [{"finding_id": "f1", "title": "T", "detail": "D",
                 "evidence": [{"kind": "notebook_cell", "ref": "ev-1"}]}]
    records = [
        {"label": f"seg{i}", "value": i, "private_email": True, "contact": "secret@example.com"}
        for i in range(4)
    ]

    def dossier_for(analysis):
        sb = design_report_storyboard(report_goal="G", insights=insights, analyses=[analysis],
                                      title="R", requirements=reqs)
        sb["evidence_registry"] = build_evidence_registry(sb)
        text, _ = build_creative_author_dossier(sb, {"mode": "creative"})
        return text

    implicit = dossier_for({
        "title": "Waffle", "caption": "c", "interpretation": "i", "records": records,
        "visual": {"type": "waffle", "label": "label", "value": "value"},
        "evidence": [{"kind": "notebook_cell", "ref": "ev-1"}],
    })
    assert "waffle" in implicit                       # folded to bespoke direction
    assert "secret@example.com" not in implicit       # unmapped PII column dropped
    assert "private_email" not in implicit

    explicit = dossier_for({
        "section_type": "advanced_visual", "title": "Waffle2", "caption": "c",
        "interpretation": "i", "records": records,
        "visual": {"type": "waffle", "label": "label", "value": "value"},
        "evidence": [{"kind": "notebook_cell", "ref": "ev-1"}],
    })
    assert "waffle" in explicit                        # explicit advanced_visual also folds (no crash)
    assert "secret@example.com" not in explicit
    assert "private_email" not in explicit
