from __future__ import annotations

from fastapi.testclient import TestClient

import dataclaw.config.paths as paths
from dataclaw.api.app import create_app
from dataclaw_artifacts.store import read_manifest_events


def test_tool_invocation_requires_a_live_session(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DATACLAW_HOME", tmp_path)

    with TestClient(create_app()) as client:
        missing_id = "missing-session"
        direct_without_session = client.post(
            "/api/tools/list_skills/invoke",
            json={"params": {}},
        )
        direct_missing_session = client.post(
            "/api/tools/list_skills/invoke",
            json={"session_id": missing_id, "params": {}},
        )
        proxy_missing_session = client.post(
            "/api/tools/list_skills/call",
            json={"session_id": missing_id, "params": {}},
        )
        agent_missing_session = client.post(
            "/api/agent",
            json={
                "thread_id": missing_id,
                "messages": [{"role": "user", "content": "hello"}],
            },
        )
        callback_missing_session = client.post(
            f"/api/chat/sessions/{missing_id}/message",
            json={"role": "assistant", "content": "late response"},
        )

        assert direct_without_session.status_code == 400
        assert direct_missing_session.status_code == 404
        assert proxy_missing_session.status_code == 404
        assert agent_missing_session.status_code == 404
        assert callback_missing_session.status_code == 404


def test_direct_tool_invoke_applies_artifact_context_hooks(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DATACLAW_HOME", tmp_path)

    with TestClient(create_app()) as client:
        session_id = client.post(
            "/api/chat/sessions",
            json={"title": "Direct tool session"},
        ).json()["id"]
        response = client.post("/api/tools/publish_artifact/invoke", json={
            "session_id": session_id,
            "params": {
                "title": "Direct Invoke Artifact",
                "html": (
                    "<!doctype html><html><body><h1>Direct</h1>"
                    "<div id='chart'></div><script>window.__artifactSmoke = true; "
                    "Plotly.newPlot('chart', [], {})</script></body></html>"
                ),
            },
        })

        assert response.status_code == 200
        result = response.json()["result"]
        assert result["success"] is True
        assert result["session_id"] == session_id

        session_listing = client.get(
            "/api/artifacts",
            params={"session_id": session_id},
        ).json()
        ids = {artifact["artifact_id"] for artifact in session_listing["artifacts"]}
        assert result["artifact_id"] in ids
        listed = next(artifact for artifact in session_listing["artifacts"] if artifact["artifact_id"] == result["artifact_id"])
        assert listed["latest_version"] == result["version"]
        assert listed["url"] == result["url"]
        assert listed["versions"][0]["version"] == result["version"]

        default_listing = client.get(
            "/api/artifacts",
            params={"session_id": "default"},
        ).json()
        default_ids = {artifact["artifact_id"] for artifact in default_listing["artifacts"]}
        assert result["artifact_id"] not in default_ids

        served = client.get(result["url"])
        assert served.status_code == 200
        assert "script-src 'nonce-" in served.headers["content-security-policy"]
        assert "connect-src 'none'" in served.headers["content-security-policy"]
        assert 'sandbox="allow-scripts"' in served.text
        assert "artifact-runtime/plotly.min.js" not in served.text
        assert "window.Plotly" in served.text or "Plotly.register" in served.text
        assert "window.__artifactSmoke" in served.text

        wrong_session = client.get(
            f"/api/artifacts/{result['artifact_id']}",
            params={"version": result["version"], "session_id": "other-session"},
        )
        assert wrong_session.status_code == 404
        missing_session = client.get(
            f"/api/artifacts/{result['artifact_id']}",
            params={"version": result["version"]},
        )
        assert missing_session.status_code == 422

        runtime = client.get("/api/artifacts/artifact-runtime/plotly.min.js")
        assert runtime.status_code == 200
        assert runtime.headers["x-content-type-options"] == "nosniff"
        assert "window.Plotly" in runtime.text or "Plotly.register" in runtime.text

        export_tool = client.post("/api/tools/export_artifact/invoke", json={
            "session_id": session_id,
            "params": {"artifact_id": result["artifact_id"], "version": result["version"]},
        })
        assert export_tool.status_code == 200
        export_result = export_tool.json()["result"]
        assert export_result["success"] is True
        assert export_result["download_url"].endswith(
            f"version={result['version']}&session_id={session_id}"
        )

        exported = client.get(export_result["download_url"])
        assert exported.status_code == 200
        assert exported.headers["content-disposition"] == f'attachment; filename="{result["artifact_id"]}-v{result["version"]}.html"'
        assert "script-src 'nonce-" in exported.headers["content-security-policy"]
        assert "artifact-runtime/plotly.min.js" not in exported.text
        assert "window.Plotly" in exported.text or "Plotly.register" in exported.text


def test_openclaw_tool_proxy_runs_artifact_post_hooks(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DATACLAW_HOME", tmp_path)

    with TestClient(create_app()) as client:
        session_id = client.post(
            "/api/chat/sessions",
            json={"title": "OpenClaw tool session"},
        ).json()["id"]
        response = client.post("/api/tools/publish_artifact/call", json={
            "session_id": session_id,
            "params": {
                "title": "OpenClaw Artifact",
                "description": "Published through OpenClaw proxy",
                "html": "<!doctype html><html><body><h1>OpenClaw</h1></body></html>",
            },
        })

        assert response.status_code == 200
        result = response.json()["result"]
        assert result["success"] is True

        listed = client.get("/api/artifacts", params={"session_id": session_id}).json()
        living = listed["artifacts"][0]
        events = read_manifest_events(living["artifact_id"])
        assert events[0]["kind"] == "artifact_published"
        assert events[0]["payload"]["artifact_id"] == result["artifact_id"]


def test_openclaw_tool_proxy_persists_one_tool_call_under_the_openclaw_id(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DATACLAW_HOME", tmp_path)

    with TestClient(create_app()) as client:
        session_id = client.post(
            "/api/chat/sessions",
            json={"title": "OpenClaw tool session"},
        ).json()["id"]
        response = client.post("/api/tools/list_skills/call", json={
            "session_id": session_id,
            "openclaw_session_key": f"agent:main:dataclaw:channel:{session_id}",
            "tool_call_id": "toolu_openclaw_1",
            "params": {},
        })
        assert response.status_code == 200

        messages = client.get(f"/api/chat/sessions/{session_id}").json()["messages"]
        tool_calls = [m for m in messages if m.get("role") == "tool_call"]
        assert len(tool_calls) == 1
        assert tool_calls[0]["toolCallId"] == "toolu_openclaw_1"
        assert tool_calls[0]["messageId"] == "tc-toolu_openclaw_1"
        assert tool_calls[0]["toolName"] == "list_skills"
