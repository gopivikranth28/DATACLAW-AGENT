"""Tests for workspace tools."""

import json

import pytest
from pathlib import Path

import builtins

from dataclaw_workspace import report_renderer
import dataclaw_workspace.tools as workspace_tools
from dataclaw_workspace.config import WorkspaceConfig
from dataclaw_workspace.tools import (
    ws_list_files,
    ws_read_file,
    ws_write_file,
    ws_update_file,
    ws_exec,
    display_image,
    build_report,
    report_design_report,
    report_publish,
    report_add_section,
    _BODY_CLOSE_RE,
    _BODY_OPEN_RE,
    _REPORT_SECTION_END,
    _REPORT_SECTION_START,
    _REPORT_SHELL_CSS_ATTR,
    _REPORT_SHELL_SCRIPT_ATTR,
    _ensure_plotly_runtime,
    _ensure_report_shell_context,
    _plotly_script_tag,
    _report_shell,
    _report_shell_css,
    _report_shell_script,
    _typed_report_section,
    _base_dir,
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


@pytest.mark.asyncio
async def test_write_and_read(cfg):
    result = await ws_write_file(cfg=cfg, path="hello.txt", content="Hello world\nLine 2\n")
    assert result["created"] is True
    assert result["size"] > 0

    result = await ws_read_file(cfg=cfg, path="hello.txt")
    assert result["content"] == "Hello world\nLine 2\n"
    assert result["total_lines"] == 2


@pytest.mark.asyncio
async def test_read_with_offset_limit(cfg):
    await ws_write_file(cfg=cfg, path="lines.txt", content="a\nb\nc\nd\ne\n")
    result = await ws_read_file(cfg=cfg, path="lines.txt", offset=1, limit=2)
    assert result["lines_returned"] == 2
    assert result["content"] == "b\nc\n"


@pytest.mark.asyncio
async def test_read_too_large(cfg):
    cfg.max_read_bytes = 10
    await ws_write_file(cfg=cfg, path="big.txt", content="x" * 100)
    with pytest.raises(ValueError, match="too large"):
        await ws_read_file(cfg=cfg, path="big.txt")


@pytest.mark.asyncio
async def test_write_too_large(cfg):
    cfg.max_write_bytes = 10
    with pytest.raises(ValueError, match="too large"):
        await ws_write_file(cfg=cfg, path="big.txt", content="x" * 100)


@pytest.mark.asyncio
async def test_list_files(cfg):
    await ws_write_file(cfg=cfg, path="a.txt", content="a")
    await ws_write_file(cfg=cfg, path="b.txt", content="b")
    result = await ws_list_files(cfg=cfg)
    names = {e["name"] for e in result["entries"]}
    assert "a.txt" in names
    assert "b.txt" in names


@pytest.mark.asyncio
async def test_list_truncation(cfg):
    cfg.max_list_entries = 2
    for i in range(5):
        await ws_write_file(cfg=cfg, path=f"file{i}.txt", content=str(i))
    result = await ws_list_files(cfg=cfg)
    assert result["truncated"] is True
    assert len(result["entries"]) == 2


@pytest.mark.asyncio
async def test_update_file(cfg):
    await ws_write_file(cfg=cfg, path="code.py", content="x = 1\ny = 2\n")
    result = await ws_update_file(cfg=cfg, path="code.py", old_string="x = 1", new_string="x = 42")
    assert result["replacements"] == 1
    assert "x = 42" in result["diff"]

    read = await ws_read_file(cfg=cfg, path="code.py")
    assert "x = 42" in read["content"]


@pytest.mark.asyncio
async def test_update_file_not_found(cfg):
    with pytest.raises(ValueError, match="not found"):
        await ws_update_file(cfg=cfg, path="nope.txt", old_string="a", new_string="b")


@pytest.mark.asyncio
async def test_update_string_not_found(cfg):
    await ws_write_file(cfg=cfg, path="f.txt", content="hello")
    with pytest.raises(ValueError, match="old_string not found"):
        await ws_update_file(cfg=cfg, path="f.txt", old_string="nope", new_string="x")


@pytest.mark.asyncio
async def test_exec(cfg):
    result = await ws_exec(cfg=cfg, command="echo hello")
    assert result["exit_code"] == 0
    assert "hello" in result["stdout"]
    assert result["timed_out"] is False


@pytest.mark.asyncio
async def test_exec_timeout(cfg):
    cfg.exec_timeout_max = 1
    result = await ws_exec(cfg=cfg, command="sleep 10", timeout=1)
    assert result["timed_out"] is True


@pytest.mark.asyncio
async def test_path_traversal_blocked(cfg):
    with pytest.raises(ValueError, match="inside workspace"):
        await ws_read_file(cfg=cfg, path="../../etc/passwd")


@pytest.mark.asyncio
async def test_display_image(cfg, tmp_path):
    # Create a fake image file in the workspace
    base = _base_dir("default")
    img = base / "chart.png"
    img.write_bytes(b"fake png data")

    result = await display_image(cfg=cfg, path="chart.png", caption="A chart")
    assert result["displayed"] is True
    assert result["caption"] == "A chart"


@pytest.mark.asyncio
async def test_display_image_not_found(cfg):
    with pytest.raises(ValueError, match="not found"):
        await display_image(cfg=cfg, path="nope.png")


@pytest.mark.asyncio
async def test_display_image_bad_format(cfg):
    base = _base_dir("default")
    (base / "file.txt").write_text("not an image")
    with pytest.raises(ValueError, match="Unsupported"):
        await display_image(cfg=cfg, path="file.txt")


@pytest.mark.asyncio
async def test_report_design_report_storyboards_then_renders_cohesive_html(cfg):
    result = await report_design_report(
        cfg=cfg,
        report_goal="Explain player archetypes and where the evidence supports slicing by team.",
        title="World Cup Archetype Report",
        report_path="reports/designed.html",
        storyboard_path="reports/designed-storyboard.json",
        insights=[
            {
                "title": "Creator archetype separates from finishers",
                "detail": "Similarity scores show a distinct creator cluster with higher chance creation.",
                "finding_id": "find-creator",
                "hypothesis_id": "hyp-archetype",
                "evidence": [{"kind": "notebook_cell", "cell_id": "cell-sim", "summary": "Similarity matrix recompute."}],
                "metrics": [{"label": "Creator avg score", "value": "8.2"}],
                "caveat": "Simulation data is descriptive.",
            }
        ],
        analyses=[
            {
                "title": "Player similarity explorer",
                "caption": "Aggregate similarity scores by archetype and team.",
                "records": [
                    {"team": "A", "archetype": "Creator", "player": "One", "similarity": 0.94},
                    {"team": "B", "archetype": "Finisher", "player": "Two", "similarity": 0.87},
                ],
                "chart": {"type": "bar", "x": "player", "y": "similarity", "color": "archetype"},
                "columns": ["team", "archetype", "player", "similarity"],
                "filters": [{"key": "team", "label": "Team"}, {"key": "archetype", "label": "Archetype"}],
                "interpretation": "The explorer lets the reader compare archetype similarity without repeated static charts.",
                "evidence": [{"kind": "notebook_cell", "cell_id": "cell-sim"}],
            }
        ],
        requirements={
            "methodology": [{"title": "Aggregate first", "detail": "Use only precomputed aggregate records in report controls."}],
            "checks": [{"title": "Evidence ids attached", "status": "pass"}],
        },
    )

    html = Path(result["html_path"]).read_text()
    storyboard = Path(result["storyboard_path"]).read_text()
    assert result["type"] == "report_design"
    assert result["publication_status"] == "designed"
    assert result["publish_required"] is True
    assert result["section_count"] >= 6
    assert result["interaction_count"] == 1
    assert "World Cup Archetype Report" in html
    assert "Creator archetype separates from finishers" in html
    assert "Player similarity explorer" in html
    assert "data-dc-section=\"chart_table_explorer\"" in html
    assert "initChartTableExplorer" in html
    assert "report_design" in result["type"]
    assert "\"mode\": \"whole_report\"" in storyboard
    assert "section_plan" in storyboard


@pytest.mark.asyncio
async def test_report_publish_regates_and_writes_receipt(cfg):
    designed = await report_design_report(
        cfg=cfg,
        report_goal="Explain the one decision-changing finding.",
        report_path="reports/publishable.html",
        storyboard_path="reports/publishable.storyboard.json",
        insights=[
            {
                "title": "Retention improved",
                "detail": "The retained cohort rose after the onboarding change.",
                "finding_id": "finding-retention",
            }
        ],
    )

    published = await report_publish(
        cfg=cfg,
        report_path="reports/publishable.html",
        storyboard_path="reports/publishable.storyboard.json",
        receipt_path="reports/publishable.receipt.json",
        export_docx=False,
    )

    receipt = json.loads(Path(published["receipt_path"]).read_text())
    assert designed["quality"]["status"] == "pass"
    assert published["type"] == "report_publish"
    assert published["published"] is True
    assert published["publication_status"] == "published"
    assert published["publish_required"] is False
    expected_status = "pass" if published["runtime_smoke"]["status"] == "passed" else "warn"
    assert published["quality"]["status"] == expected_status
    assert published["docx_export"] == {"requested": False, "status": "skipped"}
    assert published["runtime_smoke"]["status"] in {"passed", "skipped"}
    assert receipt["status"] == "published"
    assert receipt["quality"]["rubric_version"] == 3
    assert receipt["runtime_smoke"] == published["runtime_smoke"]
    assert receipt["storyboard_path"] == published["storyboard_path"]


@pytest.mark.asyncio
async def test_build_report_normalizes_raw_html_for_publish(cfg):
    built = await build_report(
        cfg=cfg,
        html="<html><body><h1>Legacy report</h1></body></html>",
        output_path="reports/raw.html",
    )

    published = await report_publish(
        cfg=cfg,
        report_path="reports/raw.html",
        storyboard_path="reports/raw.storyboard.json",
        export_docx=False,
    )

    assert built["normalization"]["mode"] == "preserved_low_confidence"
    assert Path(built["source_html_path"]).read_text() == "<html><body><h1>Legacy report</h1></body></html>"
    assert Path(built["storyboard_path"]).is_file()
    assert "data-dc-section-meta" in Path(built["html_path"]).read_text()
    assert published["published"] is True


@pytest.mark.asyncio
async def test_build_report_extracts_prose_and_tables_into_storyboard(cfg):
    built = await build_report(
        cfg=cfg,
        html="""
        <html><head><title>Legacy retention</title></head><body>
          <h1>Retention report</h1><h2>Onboarding improved retention</h2>
          <p>The retained cohort grew after the onboarding change.</p>
          <table><tr><th>cohort</th><th>retention</th></tr><tr><td>new</td><td>0.72</td></tr></table>
        </body></html>
        """,
        output_path="reports/extracted.html",
    )

    storyboard = json.loads(Path(built["storyboard_path"]).read_text())
    section_types = [section["section_type"] for section in storyboard["section_plan"]]
    assert built["normalization"]["mode"] == "structured_rebuild"
    assert "insight_grid" in section_types
    assert "interactive_table" in section_types
    assert storyboard["normalization"]["extracted"]["tables"] == 1
    assert storyboard["critique"]["passes"] <= 2


@pytest.mark.asyncio
async def test_build_report_preserves_existing_typed_report(cfg):
    designed = await report_design_report(
        cfg=cfg,
        report_goal="Explain the existing report.",
        report_path="reports/original-typed.html",
        storyboard_path="reports/original-typed.storyboard.json",
        insights=[{"title": "Existing finding", "detail": "Already structured.", "finding_id": "finding-existing"}],
    )
    original_html = Path(designed["html_path"]).read_text()

    rebuilt = await build_report(
        cfg=cfg,
        html=original_html,
        output_path="reports/preserved-typed.html",
    )

    assert rebuilt["normalization"]["mode"] == "typed_preservation"
    assert Path(rebuilt["html_path"]).read_text() == original_html
    assert Path(rebuilt["source_html_path"]).read_text() == original_html


@pytest.mark.asyncio
async def test_build_report_restores_plotly_for_typed_chart_source(cfg):
    section = report_renderer.render_report_section(
        "chart",
        {
            "title": "Runtime check",
            "figure": {"data": [{"type": "bar", "x": ["A"], "y": [1]}]},
        },
    )
    source_html = _report_shell(title="Runtime check", first_section=section, include_plotly=False)

    rebuilt = await build_report(
        cfg=cfg,
        html=source_html,
        output_path="reports/preserved-chart.html",
        quality_gate="warn",
    )

    rendered = Path(rebuilt["html_path"]).read_text()
    assert rebuilt["normalization"]["mode"] == "typed_preservation"
    assert 'data-dc-runtime="plotly"' in rendered
    assert "plotly_runtime" not in {
        check["check"]
        for check in rebuilt["quality"]["runtime_smoke"]["checks"]
    }
    assert Path(rebuilt["source_html_path"]).read_text() == source_html


@pytest.mark.asyncio
async def test_report_publish_records_docx_export_failure(cfg, monkeypatch):
    await report_design_report(
        cfg=cfg,
        report_goal="Explain the result.",
        report_path="reports/docx-failure.html",
        storyboard_path="reports/docx-failure.storyboard.json",
        insights=[
            {
                "title": "A result",
                "detail": "The completed finding is available in the report.",
                "finding_id": "finding-docx",
            }
        ],
    )

    async def fail_docx_export(*_args, **_kwargs):
        raise OSError("test DOCX failure")

    monkeypatch.setattr(workspace_tools.asyncio, "to_thread", fail_docx_export)
    published = await report_publish(
        cfg=cfg,
        report_path="reports/docx-failure.html",
        storyboard_path="reports/docx-failure.storyboard.json",
    )

    receipt = json.loads(Path(published["receipt_path"]).read_text())
    assert published["published"] is True
    assert published["docx_export"]["status"] == "failed"
    assert "test DOCX failure" in published["docx_export"]["error"]
    assert receipt["docx_export"] == published["docx_export"]


@pytest.mark.asyncio
async def test_report_design_report_infers_explorers_selectors_and_controls(cfg):
    result = await report_design_report(
        cfg=cfg,
        report_goal="Explain player archetypes with controls for team and role.",
        title="Inferred Interaction Report",
        report_path="reports/inferred.html",
        storyboard_path="reports/inferred-storyboard.json",
        insights=[
            {
                "title": "Creators separate cleanly",
                "detail": "Archetype and team slices expose the strongest similarity signals.",
                "finding_id": "find-inferred-controls",
            }
        ],
        analyses=[
            {
                "title": "Similarity controls",
                "caption": "No filters are provided; the designer should infer useful controls.",
                "records": [
                    {"team": "A", "archetype": "Creator", "player": "One", "similarity": 0.94},
                    {"team": "A", "archetype": "Creator", "player": "Three", "similarity": 0.91},
                    {"team": "B", "archetype": "Finisher", "player": "Two", "similarity": 0.87},
                    {"team": "B", "archetype": "Finisher", "player": "Four", "similarity": 0.84},
                ],
                "chart": {"type": "bar", "x": "player", "y": "similarity", "color": "archetype"},
                "interpretation": "The inferred controls let the reader inspect the same aggregate evidence.",
            },
            {
                "title": "Archetype selector",
                "items": [
                    {"id": "creator", "name": "Creator", "archetype": "Creator", "team": "A", "metrics": {"players": 2}},
                    {"id": "finisher", "name": "Finisher", "archetype": "Finisher", "team": "B", "metrics": {"players": 2}},
                ],
            },
        ],
    )

    html = Path(result["html_path"]).read_text()
    storyboard = json.loads(Path(result["storyboard_path"]).read_text())
    section_types = [item["section_type"] for item in storyboard["section_plan"]]

    assert "chart_table_explorer" in section_types
    assert "selector_panel" in section_types
    assert result["interaction_count"] == 2
    assert any(
        control.get("key") == "archetype"
        for item in storyboard["interaction_plan"]
        for control in item.get("controls", [])
    )
    assert "data-dc-section=\"chart_table_explorer\"" in html
    assert "data-dc-section=\"selector_panel\"" in html
    assert "data-dc-selection-detail" in html
    assert "r-control-reset" in html
    assert "r-control-summary" in html
    assert "role=\"button\"" in html
    assert "aria-pressed=\"false\"" in html


@pytest.mark.asyncio
async def test_report_design_report_requires_completed_insights(cfg):
    with pytest.raises(ValueError, match="at least one completed insight"):
        await report_design_report(
            cfg=cfg,
            report_goal="Build a report from charts only.",
            title="Thin Report",
            report_path="reports/thin.html",
            insights=[],
            analyses=[
                {"title": "Chart", "figure": {"data": [{"type": "bar", "x": ["A"], "y": [1]}]}},
            ],
        )


@pytest.mark.asyncio
async def test_report_design_report_default_gate_rejects_noninteractive_chart_stack(cfg):
    with pytest.raises(ValueError, match="missing_interactive_explorer"):
        await report_design_report(
            cfg=cfg,
            report_goal="Explain the chart stack.",
            title="Chart Stack",
            report_path="reports/chart-stack.html",
            insights=[
                {
                    "title": "One insight exists",
                    "detail": "The report still needs an explorer when several charts carry the evidence.",
                    "finding_id": "find-stack",
                }
            ],
            analyses=[
                {"title": f"Chart {i}", "figure": {"data": [{"type": "bar", "x": ["A"], "y": [i]}]}}
                for i in range(3)
            ],
        )


@pytest.mark.asyncio
async def test_report_add_section_builds_live_html_report(cfg):
    header = await report_add_section(
        cfg=cfg,
        section_type="header",
        report_path="reports/live.html",
        title="Live Report",
        data={"title": "World Cup Analysis", "subtitle": "A visual report"},
    )
    assert header["type"] == "report"
    assert header["publication_status"] == "draft"
    assert header["publish_required"] is True
    assert header["updated"] is True
    assert header["section"]["kind"] == "header"
    assert "--dc-bg" in header["section"]["tokens"]
    assert "data-dc-runtime=\"plotly\"" not in Path(header["html_path"]).read_text()
    await report_add_section(
        cfg=cfg,
        section_type="metric_row",
        report_path="reports/live.html",
        data={"metrics": [{"label": "Rows", "value": "54,600"}]},
    )
    await report_add_section(
        cfg=cfg,
        section_type="findings",
        report_path="reports/live.html",
        data={
            "items": [{
                "title": "Value is bought with consistency",
                "detail": "Consistency and pressure resistance dominate the signal.",
                "caveat": "Correlations are descriptive, not causal.",
            }]
        },
    )
    await report_add_section(
        cfg=cfg,
        section_type="chart",
        report_path="reports/live.html",
        data={
            "title": "Simple trend",
            "figure": {"data": [{"x": [1, 2], "y": [3, 4]}], "layout": {"title": {"text": "Simple trend"}}},
        },
    )
    await report_add_section(
        cfg=cfg,
        section_type="insight_grid",
        report_path="reports/live.html",
        data={
            "title": "Structured EDA insights",
            "caption": "The report should separate interpretation, method, evidence, and caveats.",
            "tags": ["structured", {"label": "validated", "status": "pass"}],
            "methodology": "Validate each high-value observation against notebook evidence before promotion.",
            "bullets": ["Lead with decision-changing findings.", "Keep unresolved caveats visible."],
            "items": [{
                "title": "Revenue outliers drive tail risk",
                "summary": "A small account cohort explains most variance.",
                "evidence": "cell abc123",
                "confidence": "medium",
                "finding_id": "find-1",
                "hypothesis_id": "hyp-1",
                "bullets": ["Tail risk is concentrated.", "Median behavior remains stable."],
            }],
        },
    )
    await report_add_section(
        cfg=cfg,
        section_type="explanation",
        report_path="reports/live.html",
        data={
            "title": "Why this matters",
            "summary": "The analysis separates signal from notebook noise.",
            "steps": [
                {"title": "Validate grain", "detail": "Compare user-event and account-level denominators."},
                {"title": "Track caveats", "detail": "Keep unresolved domain questions visible."},
            ],
        },
    )
    await report_add_section(
        cfg=cfg,
        section_type="comparison",
        report_path="reports/live.html",
        data={
            "title": "Segment comparison",
            "metrics": [{"key": "missing_rate", "label": "Missing rate"}, {"key": "rows", "label": "Rows"}],
            "groups": [
                {"name": "Enterprise", "values": {"missing_rate": "2.1%", "rows": "12,420"}},
                {"name": "SMB", "values": {"missing_rate": "8.4%", "rows": "41,030"}},
            ],
        },
    )
    await report_add_section(
        cfg=cfg,
        section_type="checklist",
        report_path="reports/live.html",
        data={
            "title": "Readiness checks",
            "method": "Treat blockers as unresolved until a supporting evidence trace exists.",
            "checks": [
                {"title": "Missingness sweep", "status": "passed", "detail": "No blocker missingness in target."},
                {"title": "Leakage review", "status": "blocked", "detail": "Requires domain confirmation."},
            ],
        },
    )
    await report_add_section(
        cfg=cfg,
        section_type="hypothesis_ledger",
        report_path="reports/live.html",
        data={
            "hypotheses": [
                {
                    "id": "hyp-1",
                    "statement": "Target leakage may exist in post-event flags.",
                    "status": "unresolved",
                    "priority": "high",
                    "linked_finding_ids": ["find-1"],
                    "covers_checks": ["leakage_risk"],
                }
            ],
        },
    )
    await report_add_section(
        cfg=cfg,
        section_type="evidence_trace",
        report_path="reports/live.html",
        data={
            "evidence": [
                {"kind": "notebook_cell", "cell_id": "abc123", "summary": "Recomputed segment missingness."},
                {"kind": "finding", "finding_id": "find-1", "summary": "Outlier finding anchored to cell abc123."},
            ],
        },
    )
    await report_add_section(
        cfg=cfg,
        section_type="narrative_band",
        report_path="reports/live.html",
        data={
            "title": "Narrative readout",
            "summary": "The first pass found a concentrated tail and one unresolved leakage question.",
            "bullets": ["Lead with the decision-changing signal.", "Keep the blocker visible."],
        },
    )
    await report_add_section(
        cfg=cfg,
        section_type="methodology_block",
        report_path="reports/live.html",
        data={
            "title": "Methodology",
            "methods": [
                {"title": "Validate denominator", "detail": "Recomputed at account grain.", "evidence": "notebook_cell:abc123"},
                {"title": "Review leakage", "detail": "Checked post-event fields before readiness."},
            ],
            "checks": [{"title": "Notebook evidence attached", "status": "pass"}],
        },
    )
    await report_add_section(
        cfg=cfg,
        section_type="evidence_rail",
        report_path="reports/live.html",
        data={
            "title": "Evidence rail",
            "summary": "Evidence stays beside the claim instead of buried at the end.",
            "evidence": [
                {"kind": "notebook_cell", "cell_id": "abc123", "summary": "Segment recompute."},
                {"kind": "finding", "finding_id": "find-1", "summary": "Validated outlier finding."},
            ],
        },
    )
    await report_add_section(
        cfg=cfg,
        section_type="ledger_timeline",
        report_path="reports/live.html",
        data={
            "title": "EDA timeline",
            "events": [
                {"title": "Hypothesis proposed", "status": "open", "time": "loop 1", "hypothesis_id": "hyp-1"},
                {"title": "Finding recorded", "status": "confirmed", "time": "loop 2", "finding_id": "find-1"},
            ],
        },
    )
    await report_add_section(
        cfg=cfg,
        section_type="chart_interpretation",
        report_path="reports/live.html",
        data={
            "title": "Chart plus interpretation",
            "figure": {"data": [{"x": ["Enterprise", "SMB"], "y": [2.1, 8.4], "type": "bar"}], "layout": {"title": {"text": "Missingness by segment"}}},
            "caption": "SMB has higher missingness and needs a denominator check.",
            "interpretation": "The chart changes readiness because one segment requires remediation before modeling.",
            "caveat": "Rates are descriptive until reviewed with domain owners.",
            "evidence": [{"kind": "notebook_cell", "cell_id": "abc123", "summary": "Segment missingness recompute."}],
        },
    )
    await report_add_section(
        cfg=cfg,
        section_type="filterable_chart",
        report_path="reports/live.html",
        data={
            "title": "Filterable team chart",
            "caption": "Aggregate score by team.",
            "records": [
                {"team": "A", "player": "One", "score": 9.4},
                {"team": "B", "player": "Two", "score": 8.1},
            ],
            "chart": {"type": "bar", "x": "player", "y": "score", "color": "team"},
            "filters": [{"key": "team", "label": "Team"}],
            "interpretation": "The filter keeps the chart tied to a reader-selected team.",
        },
    )
    await report_add_section(
        cfg=cfg,
        section_type="metric_row",
        report_path="reports/live.html",
        data={"metrics": [{"label": "Teams", "value": 2}]},
    )
    await report_add_section(
        cfg=cfg,
        section_type="interactive_table",
        report_path="reports/live.html",
        data={
            "title": "Interactive leaderboard",
            "caption": "Top aggregate player scores; sortable and searchable.",
            "columns": ["team", "player", "score"],
            "rows": [
                {"team": "A", "player": "One", "score": 9.4},
                {"team": "B", "player": "Two", "score": 8.1},
            ],
            "filters": [{"key": "team", "label": "Team"}],
        },
    )
    await report_add_section(
        cfg=cfg,
        section_type="chart_table_explorer",
        report_path="reports/live.html",
        data={
            "title": "Player similarity explorer",
            "caption": "A chart and table share the same aggregate payload.",
            "records": [
                {"archetype": "Creator", "player": "One", "similarity": 0.94},
                {"archetype": "Finisher", "player": "Two", "similarity": 0.87},
            ],
            "chart": {"type": "bar", "x": "player", "y": "similarity", "color": "archetype"},
            "columns": ["archetype", "player", "similarity"],
            "filters": [{"key": "archetype", "label": "Archetype"}],
            "interpretation": "The selector changes both the visual evidence and the lookup table.",
            "evidence": [{"kind": "notebook_cell", "cell_id": "sim-1", "summary": "Similarity matrix aggregate."}],
        },
    )
    await report_add_section(
        cfg=cfg,
        section_type="selector_panel",
        report_path="reports/live.html",
        data={
            "title": "Scenario selector",
            "caption": "Cards filter by scenario type.",
            "controls": [{"key": "scenario", "label": "Scenario"}],
            "items": [
                {"id": "base", "name": "Base case", "scenario": "Base", "metrics": {"win_rate": "18%"}},
                {"id": "upside", "name": "Upside case", "scenario": "Upside", "metrics": {"win_rate": "24%"}},
            ],
        },
    )
    await report_add_section(
        cfg=cfg,
        section_type="entity_card_grid",
        report_path="reports/live.html",
        data={
            "title": "Archetype cards",
            "items": [
                {"name": "Creator", "status": "confirmed", "metrics": {"players": 12, "avg_score": 8.2}},
                {"name": "Finisher", "status": "confirmed", "metrics": {"players": 9, "avg_score": 8.0}},
            ],
        },
    )

    report_path = Path(header["html_path"])
    html = report_path.read_text()
    assert "World Cup Analysis" in html
    assert "Rows" in html
    assert "54,600" in html
    assert "Value is bought with consistency" in html
    assert "Consistency and pressure resistance dominate the signal." in html
    assert "{&#x27;title&#x27;" not in html
    assert "Simple trend" in html
    assert "Revenue outliers drive tail risk" in html
    assert "The report should separate interpretation" in html
    assert "r-section-context" in html
    assert "r-method-note" in html
    assert "r-bullets" in html
    assert "Why this matters" in html
    assert "Segment comparison" in html
    assert "Enterprise" in html
    assert "Readiness checks" in html
    assert "Target leakage may exist" in html
    assert "Evidence trace" in html
    assert "Narrative readout" in html
    assert "Methodology" in html
    assert "Evidence rail" in html
    assert "EDA timeline" in html
    assert "Chart plus interpretation" in html
    assert "Filterable team chart" in html
    assert "Interactive leaderboard" in html
    assert "Player similarity explorer" in html
    assert "Scenario selector" in html
    assert "Archetype cards" in html
    assert "r-narrative-band" in html
    assert "r-methodology-grid" in html
    assert "r-evidence-rail" in html
    assert "r-timeline" in html
    assert "r-chart-story-grid" in html
    assert "r-interactive-shell" in html
    assert "r-explorer-grid" in html
    assert "r-entity-grid" in html
    assert "initFilterableChart" in html
    assert "initInteractiveTable" in html
    assert "initChartTableExplorer" in html
    assert "initSelectorPanel" in html
    assert "r-control-reset" in html
    assert "r-control-summary" in html
    assert "r-sort-button" in html
    assert "aria-sort" in html
    assert "data-dc-selection-detail" in html
    assert "aria-pressed=\"false\"" in html
    assert "r-empty-state" in html
    assert "Plotly.newPlot" in html
    assert "Plotly is loaded by the DataClaw artifact runtime" not in html
    assert "DATACLAW_REPORT_SECTIONS_START" in html
    assert "r-story-nav" in html
    assert "r-progress" in html
    assert "IntersectionObserver" in html
    assert "data-dc-section-id" in html
    assert "getAttribute(&#x27;data-dc-section-id&#x27;)" not in html
    assert "getAttribute('data-dc-section-id')" in html
    assert "data-dc-section=\"header\"" in html
    assert "data-dc-section=\"metric_row\"" in html
    assert "data-dc-section=\"findings\"" in html
    assert "data-dc-section=\"chart\"" in html
    assert "data-dc-section=\"insight_grid\"" in html
    assert "data-dc-section=\"explanation\"" in html
    assert "data-dc-section=\"comparison\"" in html
    assert "data-dc-section=\"checklist\"" in html
    assert "data-dc-section=\"hypothesis_ledger\"" in html
    assert "data-dc-section=\"evidence_trace\"" in html
    assert "data-dc-section=\"filterable_chart\"" in html
    assert "data-dc-section=\"interactive_table\"" in html
    assert "data-dc-section=\"chart_table_explorer\"" in html
    assert "data-dc-section=\"selector_panel\"" in html
    assert "data-dc-section=\"entity_card_grid\"" in html
    assert "data-dc-section-meta" in html
    assert "--dc-bg" in html
    assert "data-dc-runtime=\"plotly\"" in html


@pytest.mark.asyncio
async def test_report_add_section_normalizes_array_table_rows_and_safe_narrative_markup(cfg):
    report_path = "reports/array-rows.html"
    draft = await report_add_section(
        cfg=cfg,
        section_type="narrative_band",
        report_path=report_path,
        data={
            "heading": "Executive readout",
            "body": "<b>Argentina</b> leads the sample.\n\n<script>alert('never run')</script>",
        },
    )
    await report_add_section(
        cfg=cfg,
        section_type="metric_row",
        report_path=report_path,
        data={"metrics": [{"label": "Teams", "value": 2}]},
    )
    await report_add_section(
        cfg=cfg,
        section_type="interactive_table",
        report_path=report_path,
        data={
            "title": "Team lookup",
            "columns": ["Team", "Rating", "Reach semifinal"],
            "rows": [["Argentina", 2214, "100%"], ["Spain", 2107, "83%"]],
        },
    )

    html = Path(draft["html_path"]).read_text(encoding="utf-8")
    assert draft["publication_status"] == "draft"
    assert "<h2>Executive readout</h2>" in html
    assert "<p><strong>Argentina</strong> leads the sample.</p>" in html
    assert "<p>&lt;script&gt;alert(&#x27;never run&#x27;)&lt;/script&gt;</p>" in html
    assert '"Team": "Argentina"' in html
    assert '"Reach semifinal": "100%"' in html
    assert "function normalizeTableRows(rows, columns)" in html
    smoke = await workspace_tools._run_report_runtime_smoke(Path(draft["html_path"]))
    assert smoke["status"] in {"passed", "skipped"}
    if smoke["status"] == "passed":
        assert not [check for check in smoke["checks"] if check["check"] == "table_content"]


@pytest.mark.asyncio
async def test_report_add_section_quality_warns_on_chart_dump(cfg):
    report_path = "reports/chart-dump.html"
    last = None
    for i in range(4):
        last = await report_add_section(
            cfg=cfg,
            section_type="chart",
            report_path=report_path,
            quality_gate="warn",
            data={
                "title": f"Chart {i}",
                "figure": {"data": [{"x": [1, 2], "y": [i, i + 1]}]},
            },
        )

    assert last is not None
    assert last["quality"]["status"] == "fail"
    codes = {warning["code"] for warning in last["quality"]["warnings"]}
    assert "consecutive_plain_charts" in codes
    assert "chart_dump" in codes
    assert "plain_chart_overuse" in codes


@pytest.mark.asyncio
async def test_report_add_section_quality_flags_plain_chart_overuse_even_with_interactive(cfg):
    report_path = "reports/plain-chart-overuse.html"
    await report_add_section(
        cfg=cfg,
        section_type="interactive_table",
        report_path=report_path,
        quality_gate="warn",
        data={
            "title": "Lookup table",
            "caption": "One interactive section should not excuse a chart dump.",
            "columns": ["team", "score"],
            "rows": [{"team": "A", "score": 1}],
        },
    )
    last = None
    for i in range(4):
        last = await report_add_section(
            cfg=cfg,
            section_type="chart",
            report_path=report_path,
            quality_gate="warn",
            data={"title": f"Plain chart {i}", "figure": {"data": [{"x": [1], "y": [i]}]}},
        )

    assert last is not None
    codes = {warning["code"] for warning in last["quality"]["warnings"]}
    assert "plain_chart_overuse" in codes


@pytest.mark.asyncio
async def test_report_add_section_quality_gate_can_fail_before_write(cfg):
    report_path = "reports/chart-gate.html"
    for i in range(2):
        await report_add_section(
            cfg=cfg,
            section_type="chart",
            report_path=report_path,
            quality_gate="fail",
            data={"title": f"Chart {i}", "figure": {"data": [{"x": [1], "y": [i]}]}},
        )

    with pytest.raises(ValueError, match="Report quality gate failed"):
        await report_add_section(
            cfg=cfg,
            section_type="chart",
            report_path=report_path,
            quality_gate="fail",
            data={"title": "Chart 2", "figure": {"data": [{"x": [1], "y": [2]}]}},
        )


def test_report_visual_system_lives_in_renderer_module():
    assert _REPORT_SECTION_START == report_renderer.REPORT_SECTION_START
    assert _REPORT_SECTION_END == report_renderer.REPORT_SECTION_END
    assert _REPORT_SHELL_CSS_ATTR == report_renderer.REPORT_SHELL_CSS_ATTR
    assert _REPORT_SHELL_SCRIPT_ATTR == report_renderer.REPORT_SHELL_SCRIPT_ATTR
    assert _BODY_OPEN_RE is report_renderer.BODY_OPEN_RE
    assert _BODY_CLOSE_RE is report_renderer.BODY_CLOSE_RE
    assert _report_shell is report_renderer.report_shell
    assert _report_shell_css is report_renderer.report_shell_css
    assert _report_shell_script is report_renderer.report_shell_script
    assert _ensure_report_shell_context is report_renderer.ensure_report_shell_context

    html = report_renderer.render_report_section(
        "evidence_trace",
        {"evidence": [{"kind": "notebook_cell", "cell_id": "cell-1", "summary": "Validated grain."}]},
    )

    assert "r-ledger" in html
    assert "r-evidence-ref" in html
    assert "cell-1" in html


def test_report_shell_parts_keep_original_context_contract():
    css = _report_shell_css()
    script = _report_shell_script()
    first_section = (
        '    <section class="r-section" data-dc-section="findings" '
        'data-dc-section-id="findings-alpha"><h2>Findings Alpha</h2></section>'
    )
    html = _report_shell(title="Shell Contract", first_section=first_section)

    assert "--dc-bg" in css
    assert ".r-story-nav" in css
    assert ".r-section-context" in css
    assert ".r-method-note" in css
    assert ".r-bullets" in css
    assert ".r-insight-grid" in css
    assert ".r-steps" in css
    assert ".r-comparison" in css
    assert ".r-checks" in css
    assert ".r-ledger-item" in css
    assert ".r-evidence-rail" in css
    assert ".r-timeline" in css
    assert ".r-chart-story-grid" in css
    assert ".r-methodology-grid" in css
    assert ".r-chart-target" in css
    assert "@media (max-width: 720px)" in css

    assert "document.querySelectorAll('.r-hero, .r-section')" in script
    assert "document.querySelector('.r-story-nav')" in script
    assert "document.querySelector('.r-progress span')" in script
    assert "getAttribute('data-dc-section-id')" in script
    assert "IntersectionObserver" in script
    assert "updateProgress" in script

    assert css.strip() in html
    assert script.strip() in html
    assert "DATACLAW_REPORT_SECTIONS_START" in html
    assert "DATACLAW_REPORT_SECTIONS_END" in html
    assert first_section in html
    assert "data-dc-runtime=\"plotly\"" not in html
    assert "{shell_css}" not in html
    assert "{shell_script}" not in html


def test_report_shell_parts_can_be_called_independently():
    first_section = (
        '    <section class="r-section" data-dc-section="chart" '
        'data-dc-section-id="chart-alpha"><h2>Chart Alpha</h2></section>'
    )
    html = _report_shell(title="Runtime Contract", first_section=first_section, include_plotly=True)

    assert _report_shell_css().strip()
    assert _report_shell_script().strip()
    assert "Runtime Contract" in html
    assert "Chart Alpha" in html
    assert html.count("data-dc-runtime=\"plotly\"") == 1

    without_runtime = html.replace(_plotly_script_tag(), "")
    with_runtime = _ensure_plotly_runtime(without_runtime)
    assert with_runtime.count("data-dc-runtime=\"plotly\"") == 1
    assert _ensure_plotly_runtime(with_runtime).count("data-dc-runtime=\"plotly\"") == 1

    auto_runtime = _ensure_report_shell_context(without_runtime)
    assert auto_runtime.count("data-dc-runtime=\"plotly\"") == 1


def test_existing_report_shell_context_upgrade_is_idempotent():
    legacy = """<!doctype html>
<html><head><title>Legacy</title><style>.r-section { padding: 18px; }</style></head>
<body><main class="r-page">
<!-- DATACLAW_REPORT_SECTIONS_START -->
<section class="r-section" data-dc-section="findings" data-dc-section-id="old"><h2>Old</h2></section>
<!-- DATACLAW_REPORT_SECTIONS_END -->
</main></body></html>"""

    migrated = _ensure_report_shell_context(legacy)

    assert "Old" in migrated
    assert "data-dc-report-shell-css" in migrated
    assert "data-dc-report-shell-script" in migrated
    assert '<div class="r-progress" aria-hidden="true"><span></span></div>' in migrated
    assert '<nav class="r-story-nav" aria-label="Report sections"></nav>' in migrated
    assert ".r-method-note" in migrated
    assert "document.querySelectorAll('.r-hero, .r-section')" in migrated
    assert _ensure_report_shell_context(migrated).count("data-dc-report-shell-css") == 1
    assert _ensure_report_shell_context(migrated).count("data-dc-report-shell-script") == 1
    assert _ensure_report_shell_context(migrated).count('class="r-story-nav"') == 1


def test_legacy_shell_without_attrs_gets_current_runtime():
    legacy = """<!doctype html>
<html><head><title>Legacy</title><style>.r-story-nav { display: flex; }</style></head>
<body><main class="r-page">
<!-- DATACLAW_REPORT_SECTIONS_START -->
<section class="r-section" data-dc-section="findings" data-dc-section-id="old"><h2>Old</h2></section>
<!-- DATACLAW_REPORT_SECTIONS_END -->
</main>
<script>
(function() {
  var sections = Array.prototype.slice.call(document.querySelectorAll('.r-hero, .r-section'));
})();
</script>
</body></html>"""

    migrated = _ensure_report_shell_context(legacy)

    assert migrated.count("data-dc-report-shell-css") == 1
    assert migrated.count("data-dc-report-shell-script") == 1
    assert "window.DataClawReport" in migrated
    assert "r-interactive-shell" in migrated
    assert migrated.count("document.querySelectorAll('.r-hero, .r-section')") == 1


@pytest.mark.asyncio
async def test_report_add_section_upgrades_legacy_report_shell(cfg):
    base = _base_dir("default")
    report = base / "reports" / "legacy.html"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        """<!doctype html>
<html><head><title>Legacy report</title><style>.r-section { padding: 18px; }</style></head>
<body><main class="r-page">
<!-- DATACLAW_REPORT_SECTIONS_START -->
<section class="r-section" data-dc-section="findings" data-dc-section-id="legacy"><h2>Legacy finding</h2></section>
<!-- DATACLAW_REPORT_SECTIONS_END -->
</main></body></html>""",
        encoding="utf-8",
    )

    await report_add_section(
        cfg=cfg,
        section_type="insight_grid",
        report_path="reports/legacy.html",
        data={
            "title": "New insight layer",
            "methodology": "Re-check with the current denominator.",
            "items": [{"title": "Segment shift", "evidence": "cell-7"}],
        },
    )

    html = report.read_text()
    assert "Legacy finding" in html
    assert "New insight layer" in html
    assert "Segment shift" in html
    assert "data-dc-report-shell-css" in html
    assert "data-dc-report-shell-script" in html
    assert '<nav class="r-story-nav" aria-label="Report sections"></nav>' in html
    assert ".r-insight-grid" in html
    assert ".r-method-note" in html
    assert "document.querySelectorAll('.r-hero, .r-section')" in html


def test_plotly_script_tag_never_falls_back_to_cdn(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("plotly"):
            raise ImportError("plotly unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    tag = _plotly_script_tag()
    open_tag = tag.split(">", 1)[0]
    assert "src=" not in open_tag
    assert "data-dc-runtime=\"plotly\"" in tag
    assert "window.Plotly" in tag
    assert "Plotly is loaded by the DataClaw artifact runtime" not in tag


def test_report_sections_use_artifact_contract():
    first = _typed_report_section("kpi", {"title": "Summary", "metrics": [{"label": "Rows", "value": 10}]})
    second = _typed_report_section("kpi", {"title": "Summary", "metrics": [{"label": "Rows", "value": 10}]})

    assert first["kind"] == "metric_row"
    assert first["section_id"] == second["section_id"]
    assert first["payload"]["metric_count"] == 1
    assert "--dc-danger" in first["tokens"]
