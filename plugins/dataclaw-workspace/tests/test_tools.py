"""Tests for workspace tools."""

import pytest
from pathlib import Path

import builtins

from dataclaw_workspace.config import WorkspaceConfig
from dataclaw_workspace.tools import (
    ws_list_files,
    ws_read_file,
    ws_write_file,
    ws_update_file,
    ws_exec,
    display_image,
    report_add_section,
    _ensure_plotly_runtime,
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
async def test_report_add_section_builds_live_html_report(cfg):
    header = await report_add_section(
        cfg=cfg,
        section_type="header",
        report_path="reports/live.html",
        title="Live Report",
        data={"title": "World Cup Analysis", "subtitle": "A visual report"},
    )
    assert header["type"] == "report"
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
    assert "data-dc-section-meta" in html
    assert "--dc-bg" in html
    assert "data-dc-runtime=\"plotly\"" in html


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
