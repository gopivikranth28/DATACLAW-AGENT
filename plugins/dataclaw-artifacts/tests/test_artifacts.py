from __future__ import annotations

import os
from pathlib import Path

import pytest

import dataclaw.config.paths as paths
from dataclaw_analysis_review.store import append_review_finding, new_finding_id, now_iso
from dataclaw_artifacts.compiler import compile_living_report
from dataclaw_artifacts.hooks import artifact_capture_hook
from dataclaw_artifacts.sections import (
    CHART_SUMMARY_MAX_BYTES,
    SectionValidationError,
    normalize_section,
    section_attrs,
    section_meta_script,
)
from dataclaw_artifacts.store import (
    MAX_EXPORTED_ARTIFACT_BYTES,
    MAX_PUBLISHED_ARTIFACT_BYTES,
    ensure_living_report,
    read_manifest_events,
    read_meta,
    read_source,
)
from dataclaw_artifacts.tools import export_artifact, list_artifacts, publish_artifact, read_artifact, report_note
from dataclaw_artifacts.wrapper import (
    ARTIFACT_CSP,
    _inject_head,
    artifact_csp,
    artifact_host_shell,
    plotly_runtime_js,
    plotly_runtime_source,
)


@pytest.fixture(autouse=True)
def tmp_home(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DATACLAW_HOME", tmp_path)
    (tmp_path / "workspaces").mkdir()
    return tmp_path


def _workspace(session_id: str) -> Path:
    root = paths.workspaces_dir() / session_id
    root.mkdir(parents=True, exist_ok=True)
    return root


@pytest.mark.asyncio
async def test_publish_revise_read_and_conflict_by_source_path():
    session_id = "s1"
    report = _workspace(session_id) / "reports" / "report.html"
    report.parent.mkdir(parents=True)
    report.write_text("<!doctype html><html><body><h1>First</h1></body></html>", encoding="utf-8")

    created = await publish_artifact(
        title="Quarterly Report",
        source_path="reports/report.html",
        session_id=session_id,
        label="initial",
    )

    assert created["success"] is True
    assert created["version"] == 1
    assert created["artifact_id"].startswith("art-")
    assert "version=1" in created["url"]
    assert "session_id=s1" in created["url"]

    report.write_text("<!doctype html><html><body><h1>Second</h1></body></html>", encoding="utf-8")
    revised = await publish_artifact(
        title="Quarterly Report",
        source_path="reports/report.html",
        artifact_id=created["artifact_id"],
        base_version=1,
        session_id=session_id,
        label="revision",
    )

    assert revised["success"] is True
    assert revised["version"] == 2

    stale = await publish_artifact(
        title="Quarterly Report",
        source_path="reports/report.html",
        artifact_id=created["artifact_id"],
        base_version=1,
        session_id=session_id,
    )
    assert stale["success"] is False
    assert stale["error"]["code"] == "version_conflict"

    cross_session_revision = await publish_artifact(
        title="Quarterly Report",
        html="<!doctype html><html><body><h1>Cross session</h1></body></html>",
        artifact_id=created["artifact_id"],
        session_id="other-session",
    )
    assert cross_session_revision["success"] is False
    assert cross_session_revision["error"]["code"] == "artifact_session_mismatch"

    read = await read_artifact(artifact_id=created["artifact_id"], version=2, session_id=session_id)
    assert read["version"] == 2
    assert "Second" in read["html"]

    exported = await export_artifact(
        artifact_id=created["artifact_id"],
        version=2,
        session_id=session_id,
    )
    assert exported["success"] is True
    assert exported["download_url"].endswith("version=2&session_id=s1")
    assert exported["filename"] == f"{created['artifact_id']}-v2.html"
    assert exported["bytes"] > 100_000

    with pytest.raises(KeyError):
        await read_artifact(artifact_id=created["artifact_id"], version=2, session_id="other-session")
    with pytest.raises(KeyError):
        await export_artifact(artifact_id=created["artifact_id"], version=2, session_id="other-session")

    listed = await list_artifacts(session_id=session_id)
    assert listed["total"] == 2
    assert listed["artifacts"][0]["kind"] == "living_report"
    published = next(artifact for artifact in listed["artifacts"] if artifact["artifact_id"] == created["artifact_id"])
    assert published["latest_version"] == 2


@pytest.mark.asyncio
async def test_publish_strips_workspace_plotly_runtime_before_validation():
    html = """<!doctype html><html><head>
    <script data-dc-runtime="plotly">window.parent.postMessage({bad: true}, "*")</script>
    </head><body>
    <div id="chart"></div>
    <script>Plotly.newPlot("chart", [], {}, {responsive: true})</script>
    </body></html>"""

    result = await publish_artifact(
        title="Workspace report",
        html=html,
        session_id="runtime-strip",
    )

    assert result["success"] is True
    stored = read_source(result["artifact_id"], result["version"])
    assert 'data-dc-runtime="plotly"' not in stored
    assert "window.parent.postMessage" not in stored
    assert "Plotly.newPlot" in stored


@pytest.mark.asyncio
async def test_identical_publish_dedupes_without_new_version():
    session_id = "s2"
    html = "<!doctype html><html><body><h1>Same</h1></body></html>"

    created = await publish_artifact(title="Same Report", html=html, session_id=session_id)
    repeated = await publish_artifact(
        title="Same Report",
        html=html,
        artifact_id=created["artifact_id"],
        session_id=session_id,
    )

    assert repeated["success"] is True
    assert repeated["version"] == 1
    assert repeated["deduped"] is True


@pytest.mark.asyncio
async def test_publish_validation_rejects_live_calls_and_hostile_tags():
    live = await publish_artifact(
        title="Bad",
        html="<html><body><script>fetch('/api/plans')</script></body></html>",
        session_id="s3",
    )
    assert live["success"] is False
    assert live["error"]["code"] == "live_data_call"

    framed = await publish_artifact(
        title="Bad Frame",
        html="<html><body><iframe src='x'></iframe></body></html>",
        session_id="s3",
    )
    assert framed["success"] is False
    assert framed["error"]["code"] == "forbidden_tag"

    remote = await publish_artifact(
        title="Remote",
        html="<html><body><img src='https://example.com/pixel.png'></body></html>",
        session_id="s3",
    )
    assert remote["success"] is False
    assert remote["error"]["code"] == "external_asset"

    navigation = await publish_artifact(
        title="Bad Navigation",
        html="<html><body><script>window.location='https://evil.example/leak'</script></body></html>",
        session_id="s3",
    )
    assert navigation["success"] is False
    assert navigation["error"]["code"] == "live_data_call"

    parent_message = await publish_artifact(
        title="Bad Message",
        html="<html><body><script>window.parent.postMessage({type:'artifact_external_link',href:'https://evil.example'}, '*')</script></body></html>",
        session_id="s3",
    )
    assert parent_message["success"] is False
    assert parent_message["error"]["code"] == "live_data_call"


@pytest.mark.asyncio
async def test_publish_inlines_relative_image_asset_and_writes_canonical_source():
    session_id = "s4"
    root = _workspace(session_id)
    (root / "reports").mkdir()
    (root / "reports" / "tiny.png").write_bytes(b"png-bytes")
    source = root / "reports" / "image-report.html"
    source.write_text("<html><body><img src='tiny.png'></body></html>", encoding="utf-8")

    result = await publish_artifact(
        title="Image Report",
        source_path="reports/image-report.html",
        session_id=session_id,
    )

    assert result["success"] is True
    stored = read_source(result["artifact_id"], 1)
    assert "data:image/png;base64," in stored
    assert "tiny.png" not in stored
    assert "data:image/png;base64," in source.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_publish_rejects_relative_asset_escape_outside_workspace(tmp_home):
    session_id = "s4-escape"
    root = _workspace(session_id)
    report_dir = root / "reports"
    report_dir.mkdir()
    secret = tmp_home / "secret.txt"
    secret.write_text("SECRET-OUTSIDE-WORKSPACE", encoding="utf-8")
    rel_secret = Path("../../..") / secret.name
    source = report_dir / "escape-report.html"
    source.write_text(f"<html><body><img src='{rel_secret}'></body></html>", encoding="utf-8")

    result = await publish_artifact(
        title="Escape Report",
        source_path="reports/escape-report.html",
        session_id=session_id,
    )

    assert result["success"] is False
    assert result["error"]["code"] == "asset_outside_allowed_roots"


@pytest.mark.asyncio
async def test_publish_rejects_symlink_asset_escape(tmp_home):
    if not hasattr(os, "symlink"):
        pytest.skip("symlink unavailable")

    session_id = "s4-symlink"
    root = _workspace(session_id)
    report_dir = root / "reports"
    report_dir.mkdir()
    secret = tmp_home / "secret.js"
    secret.write_text("console.log('outside')", encoding="utf-8")
    symlink = report_dir / "leak.js"
    symlink.symlink_to(secret)
    source = report_dir / "symlink-report.html"
    source.write_text("<html><body><script src='leak.js'></script></body></html>", encoding="utf-8")

    result = await publish_artifact(
        title="Symlink Report",
        source_path="reports/symlink-report.html",
        session_id=session_id,
    )

    assert result["success"] is False
    assert result["error"]["code"] == "asset_outside_allowed_roots"


@pytest.mark.asyncio
async def test_publish_rejects_relative_asset_escape_to_other_session():
    session_id = "s4-source"
    root = _workspace(session_id)
    other = _workspace("s4-other")
    report_dir = root / "reports"
    report_dir.mkdir()
    (other / "other.png").write_bytes(b"not-for-this-session")
    source = report_dir / "cross-session-report.html"
    source.write_text("<html><body><img src='../../s4-other/other.png'></body></html>", encoding="utf-8")

    result = await publish_artifact(
        title="Cross Session Report",
        source_path="reports/cross-session-report.html",
        session_id=session_id,
    )

    assert result["success"] is False
    assert result["error"]["code"] == "asset_outside_allowed_roots"


@pytest.mark.asyncio
async def test_publish_inlines_css_urls_and_rejects_remote_css_assets():
    session_id = "s4-css"
    root = _workspace(session_id)
    report_dir = root / "reports"
    report_dir.mkdir()
    (report_dir / "tiny.png").write_bytes(b"png-bytes")
    source = report_dir / "css-report.html"
    source.write_text(
        """
        <html>
          <head><style>.hero{background-image:url("tiny.png")}</style></head>
          <body><div style="background:url('tiny.png')">Hello</div></body>
        </html>
        """,
        encoding="utf-8",
    )

    result = await publish_artifact(
        title="CSS Report",
        source_path="reports/css-report.html",
        session_id=session_id,
    )

    assert result["success"] is True
    stored = read_source(result["artifact_id"], 1)
    assert stored.count("data:image/png;base64,") == 2
    assert "tiny.png" not in stored

    remote = await publish_artifact(
        title="Remote CSS",
        html="<html><head><style>.x{background:url('https://example.com/pixel.png')}</style></head></html>",
        session_id=session_id,
    )

    assert remote["success"] is False
    assert remote["error"]["code"] == "external_asset"


def test_host_shell_uses_sandboxed_child_and_no_egress_csp():
    shell = artifact_host_shell(
        artifact_id="art-1234abcd",
        version=1,
        title="Test",
        source="<html><head><script>window.x = 1</script></head><body><h1>Hello</h1></body></html>",
        nonce="testnonce",
    )

    assert 'sandbox="allow-scripts"' in shell
    assert "frame.srcdoc = artifactSrcdoc" in shell
    assert "artifact_external_link" in shell
    assert "Blocked artifact navigation" in shell
    assert "artifact-runtime/plotly.min.js" in shell
    assert 'nonce="testnonce"' in shell
    assert 'nonce=\\"testnonce\\"' in shell
    assert "if (!event.isTrusted) return;" in shell
    assert "event.source !== frame.contentWindow" in shell
    assert "connect-src 'none'" in ARTIFACT_CSP
    assert "navigate-to 'none'" in ARTIFACT_CSP
    assert "script-src 'unsafe-inline'" in ARTIFACT_CSP
    assert "script-src 'nonce-testnonce'" in artifact_csp("testnonce")
    assert "script-src 'unsafe-inline'" not in artifact_csp("testnonce")
    assert "--dc-font" in shell
    assert "--dc-bg: #f7f8fb !important" in shell
    assert ".dc-page, .dataclaw-page, .r-page" in shell


def test_nonce_injection_does_not_rewrite_script_text():
    child = _inject_head(
        '<html><head></head><body><script>var fig={"x":["<script>label"]};</script></body></html>',
        "Script Text",
        nonce="testnonce",
    )

    assert '<script nonce="testnonce">var fig=' in child
    assert '<script>label' in child
    assert '<script nonce="testnonce">label' not in child


def test_theme_style_is_injected_after_author_head_styles():
    child = _inject_head(
        '<html><head><style>:root{--dc-bg:red}</style></head><body>Report</body></html>',
        "Themed",
        nonce="testnonce",
    )

    assert child.find("--dc-bg: #f7f8fb !important") > child.find("--dc-bg:red")
    assert child.find("--dc-bg: #f7f8fb !important") < child.find("</head>")


def test_plotly_runtime_uses_installed_bundle():
    plotly_runtime_source.cache_clear()
    plotly_runtime_js.cache_clear()
    js = plotly_runtime_js()

    assert "Plotly is unavailable" not in js
    assert "window.Plotly" in js or "Plotly.register" in js
    assert len(js.encode("utf-8")) > 100_000


def test_plotly_runtime_prefers_ui_vendored_bundle(tmp_path, monkeypatch):
    bundle = tmp_path / "ui" / "node_modules" / "plotly.js-dist-min" / "plotly.min.js"
    bundle.parent.mkdir(parents=True)
    bundle.write_text("window.Plotly = {newPlot: function(){}};", encoding="utf-8")

    monkeypatch.setattr("dataclaw_artifacts.wrapper._repo_root", lambda: tmp_path)
    plotly_runtime_source.cache_clear()
    plotly_runtime_js.cache_clear()

    source = plotly_runtime_source()
    js = plotly_runtime_js()

    assert source["kind"] == "ui_vendored"
    assert source["path"] == str(bundle)
    assert "window.Plotly" in js


def test_artifact_caps_are_raised_for_runtime_exports():
    assert MAX_PUBLISHED_ARTIFACT_BYTES == 25 * 1024 * 1024
    assert MAX_EXPORTED_ARTIFACT_BYTES == 25 * 1024 * 1024


def test_typed_sections_are_stable_and_validated():
    data = {
        "title": "Primary chart",
        "plan_step_id": "step-eda",
        "figure": {"data": [{"x": [1], "y": [2]}], "layout": {"title": {"text": "x"}}},
    }
    first = normalize_section("chart", data)
    second = normalize_section("chart", data)

    assert first["section_id"] == second["section_id"]
    assert first["kind"] == "chart"
    assert first["payload"]["series_count"] == 1
    assert 'data-dc-section="chart"' in section_attrs(first)
    assert "data-dc-section-meta" in section_meta_script(first)

    chart_story = normalize_section("chart_interpretation", {
        "title": "Chart story",
        "figure": data["figure"],
        "interpretation": "The chart changes the readiness verdict.",
        "evidence": [{"kind": "notebook_cell", "cell_id": "abc123"}],
    })
    assert chart_story["kind"] == "chart_interpretation"
    assert chart_story["payload"]["series_count"] == 1
    assert chart_story["payload"]["evidence_count"] == 1
    assert chart_story["payload"]["has_interpretation"] is True

    finding = normalize_section("findings", {
        "items": [{"title": "Evidence-only finding", "evidence": "notebook_cell:abc123"}],
    })
    assert finding["payload"]["items"][0]["evidence"] == "notebook_cell:abc123"

    narrative = normalize_section("narrative_band", {"title": "Narrative", "summary": "First.\n\nSecond."})
    assert narrative["payload"]["paragraph_count"] == 2

    method = normalize_section("methodology_block", {"methods": [{"title": "Check grain"}], "checks": [{"title": "Evidence", "status": "pass"}]})
    assert method["payload"]["method_count"] == 1
    assert method["payload"]["check_count"] == 1

    rail = normalize_section("evidence_rail", {"evidence": [{"kind": "finding", "finding_id": "find-1"}]})
    assert rail["payload"]["evidence_count"] == 1

    timeline = normalize_section("ledger_timeline", {"events": [{"title": "Finding recorded", "status": "confirmed"}]})
    assert timeline["payload"]["event_count"] == 1
    assert timeline["payload"]["statuses"] == ["confirmed"]

    explorer = normalize_section("chart_table_explorer", {
        "title": "Player explorer",
        "records": [{"team": "A", "player": "One", "score": 9.4}],
        "chart": {"type": "bar", "x": "player", "y": "score"},
        "filters": [{"key": "team"}],
    })
    assert explorer["kind"] == "chart_table_explorer"
    assert explorer["payload"]["record_count"] == 1
    assert explorer["payload"]["filter_count"] == 1
    assert explorer["payload"]["data_json_bytes"] > 0

    table = normalize_section("interactive_table", {
        "caption": "Top player aggregates by team.",
        "columns": ["player", "score"],
        "rows": [{"player": "One", "score": 9.4}],
        "filters": [{"key": "player"}],
    })
    assert table["kind"] == "interactive_table"
    assert table["data_policy"] == "preview"
    assert table["payload"]["row_count"] == 1
    assert table["payload"]["has_search"] is True

    selector = normalize_section("selector_panel", {
        "controls": [{"key": "team"}],
        "items": [{"name": "One", "team": "A"}],
    })
    assert selector["payload"]["control_count"] == 1
    assert selector["payload"]["item_count"] == 1

    cards = normalize_section("archetype_cards", {"items": [{"name": "Creator", "metrics": {"score": 8.2}}]})
    assert cards["kind"] == "entity_card_grid"
    assert cards["payload"]["item_count"] == 1


def test_typed_sections_reject_oversize_chart_summary():
    too_large = {"figure": {"data": [{"x": ["x" * CHART_SUMMARY_MAX_BYTES]}]}}

    with pytest.raises(SectionValidationError) as exc:
        normalize_section("chart", too_large)

    assert exc.value.code == "chart_summary_too_large"


@pytest.mark.asyncio
async def test_report_note_creates_live_report_and_compiles_pages():
    result = await report_note(
        page="decisions",
        markdown="Dropped the baseline after residual review.",
        plan_step_id="step-eda",
        session_id="session-living",
    )

    assert result["success"] is True
    assert result["url"].endswith("/living?session_id=session-living")

    events = read_manifest_events(result["artifact_id"])
    assert len(events) == 1
    assert events[0]["kind"] == "note"
    assert events[0]["plan_step_id"] == "step-eda"

    html = compile_living_report(result["artifact_id"])
    assert "DataClaw living report" in html
    assert "Dropped the baseline" in html
    assert "Decisions" in html
    assert "Log" in html

    listed = await list_artifacts(session_id="session-living")
    assert listed["artifacts"][0]["kind"] == "living_report"
    assert listed["artifacts"][0]["url"].endswith("/living?session_id=session-living")


@pytest.mark.asyncio
async def test_list_artifacts_creates_empty_living_report():
    listed = await list_artifacts(session_id="session-empty")

    assert listed["total"] == 1
    assert listed["artifacts"][0]["kind"] == "living_report"
    assert listed["artifacts"][0]["url"].endswith("/living?session_id=session-empty")
    assert read_manifest_events(listed["artifacts"][0]["artifact_id"]) == []


@pytest.mark.asyncio
async def test_list_artifacts_preserves_living_report_project_metadata():
    created = ensure_living_report("session-project", "project-1")

    listed = await list_artifacts(session_id="session-project")
    meta = read_meta(created["id"])

    assert listed["artifacts"][0]["kind"] == "living_report"
    assert meta["project_id"] == "project-1"
    assert meta["updated_at"] == created["updated_at"]


@pytest.mark.asyncio
async def test_artifact_capture_hook_appends_publish_event_to_living_report():
    state = {
        "session_id": "session-hook",
        "project_id": "",
        "tool_results": [{
            "tool_name": "publish_artifact",
            "tool_input": {
                "title": "EDA Dashboard",
                "description": "Main dashboard",
                "session_id": "session-hook",
                "plan_step_id": "step-eda",
            },
            "result": '{"success": true, "artifact_id": "art-1234abcd", "version": 2, "session_id": "session-hook", "url": "/api/artifacts/art-1234abcd?version=2&session_id=session-hook"}',
            "is_error": False,
        }],
    }

    updated = await artifact_capture_hook(state)
    assert updated is state

    listed = await list_artifacts(session_id="session-hook")
    living = listed["artifacts"][0]
    assert living["kind"] == "living_report"
    events = read_manifest_events(living["artifact_id"])
    assert events[0]["kind"] == "artifact_published"
    assert events[0]["plan_step_id"] == "step-eda"
    assert events[0]["session_id"] == "session-hook"
    assert events[0]["payload"]["artifact_id"] == "art-1234abcd"
    html = compile_living_report(living["artifact_id"])
    assert "Open artifact" in html
    assert "Export HTML" in html
    assert "session_id=session-hook" in html


@pytest.mark.asyncio
async def test_artifact_capture_hook_appends_unresolved_review_risk_event():
    finding_id = new_finding_id()
    append_review_finding(
        {
            "finding_id": finding_id,
            "review_id": "rev-test",
            "scope": "plan_step",
            "target_id": "step-eda",
            "plan_step_id": "step-eda",
            "session_id": "session-risk",
            "severity": "required",
            "category": "unsupported_claim",
            "source": "checklist:CHK-test",
            "claim": "Required review issue remains open",
            "evidence": ["step-eda"],
            "recommendation": "Resolve before publishing",
            "status": "open",
            "created_at": now_iso(),
        },
        "session-risk",
    )
    state = {
        "session_id": "session-risk",
        "project_id": "",
        "tool_results": [{
            "tool_name": "publish_artifact",
            "tool_input": {
                "title": "EDA Dashboard",
                "description": "Main dashboard",
                "session_id": "session-risk",
                "plan_step_id": "step-eda",
            },
            "result": '{"success": true, "artifact_id": "art-1234abcd", "version": 2, "session_id": "session-risk", "url": "/api/artifacts/art-1234abcd?version=2&session_id=session-risk"}',
            "is_error": False,
        }],
    }

    await artifact_capture_hook(state)

    living = (await list_artifacts(session_id="session-risk"))["artifacts"][0]
    events = read_manifest_events(living["artifact_id"])
    assert [event["kind"] for event in events] == ["artifact_published", "unresolved_review_risk"]
    assert events[1]["plan_step_id"] == "step-eda"
    assert events[1]["payload"]["finding_ids"] == [finding_id]
