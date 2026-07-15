"""D7 verified-freeform tier: authored HTML, deterministically verified.

docs/report-design-variance.md, D7: a freeform-authored page is publishable
only when every displayed number/claim is bound to a contract fact via
data-fact-id and verification passes — at build time and again at publish.
"""

import json
from pathlib import Path

import pytest

from dataclaw_workspace.config import WorkspaceConfig
from dataclaw_workspace.report_renderer import verify_fact_bound_html
from dataclaw_workspace.tools import build_report, report_publish

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


FACTS = [
    {"fact_id": "renewal-rate", "text": "61%"},
    {"fact_id": "renewal-gap", "text": "23-point renewal gap"},
]

BOUND_PAGE = """<!doctype html><html><head><title>Renewal report</title></head><body>
<h1>Renewal report</h1>
<p>The newest cohort renews at <span data-fact-id="renewal-rate">61%</span>, a
<strong data-fact-id="renewal-gap">23-point renewal gap</strong> against mature accounts.</p>
<p>Mature accounts remain the stable base of the book.</p>
</body></html>"""


def test_verifier_passes_a_fully_bound_page():
    result = verify_fact_bound_html(BOUND_PAGE, FACTS)

    assert result["status"] == "pass"
    assert result["bound_fact_count"] == 2
    assert result["unbound_numeral_count"] == 0


def test_verifier_rejects_a_displayed_number_that_diverges_from_its_fact():
    page = BOUND_PAGE.replace(">61%<", ">58%<")
    result = verify_fact_bound_html(page, FACTS)

    assert result["status"] == "fail"
    finding = next(f for f in result["findings"] if f["id"] == "fact_text_mismatch")
    assert finding["fact_id"] == "renewal-rate"
    assert finding["expected"] == "61%"


def test_verifier_rejects_unbound_numerals_and_unknown_fact_ids():
    page = BOUND_PAGE.replace(
        "stable base of the book.",
        'stable base, worth <em data-fact-id="invented">$4.2M</em> across 310 accounts.',
    )
    result = verify_fact_bound_html(page, FACTS)

    ids = {f["id"] for f in result["findings"]}
    assert "unknown_fact_id" in ids
    assert "unbound_numerals" in ids


def test_verifier_ignores_numerals_inside_scripts_and_requires_bindings():
    page = """<html><body><p>No numbers in prose.</p>
    <script>var data = [1, 2, 3, 400];</script></body></html>"""
    result = verify_fact_bound_html(page, FACTS)

    ids = {f["id"] for f in result["findings"]}
    assert "unbound_numerals" not in ids
    assert "no_bound_facts" in ids
    assert result["status"] == "fail"


@pytest.mark.asyncio
async def test_build_report_freeform_tier_preserves_the_page_and_records_verification(cfg):
    built = await build_report(
        cfg=cfg,
        html=BOUND_PAGE,
        output_path="reports/freeform.html",
        title="Renewal report",
        facts=FACTS,
    )

    assert built["fact_verification"]["status"] == "pass"
    assert built["normalization"]["authoring_tier"] == "verified_freeform"
    assert Path(built["html_path"]).read_text() == BOUND_PAGE
    storyboard = json.loads(Path(built["storyboard_path"]).read_text())
    assert storyboard["fact_contract"]["facts"] == FACTS


@pytest.mark.asyncio
async def test_build_report_freeform_tier_fails_closed_on_a_wrong_number(cfg):
    with pytest.raises(ValueError, match="fact-verification gate failed: fact_text_mismatch"):
        await build_report(
            cfg=cfg,
            html=BOUND_PAGE.replace(">61%<", ">58%<"),
            output_path="reports/freeform-bad.html",
            title="Renewal report",
            facts=FACTS,
        )


@pytest.mark.asyncio
async def test_publish_recomputes_fact_verification_for_the_freeform_tier(cfg):
    built = await build_report(
        cfg=cfg,
        html=BOUND_PAGE,
        output_path="reports/freeform-publish.html",
        title="Renewal report",
        facts=FACTS,
    )

    published = await report_publish(
        cfg=cfg,
        report_path="reports/freeform-publish.html",
        storyboard_path=built["storyboard_path"],
    )

    assert published["published"] is True
    assert published["fact_verification"]["status"] == "pass"
    receipt = json.loads(Path(published["receipt_path"]).read_text())
    assert receipt["fact_verification"]["status"] == "pass"


@pytest.mark.asyncio
async def test_publish_blocks_a_preserved_low_confidence_page_without_a_contract(cfg):
    built = await build_report(
        cfg=cfg,
        html="<html><body><p>hi</p></body></html>",
        output_path="reports/low-confidence.html",
        title="Sparse page",
    )
    assert built["normalization"]["mode"] == "preserved_low_confidence"

    with pytest.raises(ValueError, match="has no fact contract"):
        await report_publish(
            cfg=cfg,
            report_path="reports/low-confidence.html",
            storyboard_path=built["storyboard_path"],
        )
