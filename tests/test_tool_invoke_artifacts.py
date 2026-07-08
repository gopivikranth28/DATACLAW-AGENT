from __future__ import annotations

from fastapi.testclient import TestClient

import dataclaw.config.paths as paths
from dataclaw.api.app import create_app


def test_direct_tool_invoke_applies_artifact_context_hooks(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DATACLAW_HOME", tmp_path)

    with TestClient(create_app()) as client:
        response = client.post("/api/tools/publish_artifact/invoke", json={
            "session_id": "direct-session",
            "params": {
                "title": "Direct Invoke Artifact",
                "html": (
                    "<!doctype html><html><body><h1>Direct</h1>"
                    "<script>window.__artifactSmoke = true</script></body></html>"
                ),
            },
        })

        assert response.status_code == 200
        result = response.json()["result"]
        assert result["success"] is True

        session_listing = client.get(
            "/api/artifacts",
            params={"session_id": "direct-session"},
        ).json()
        ids = {artifact["artifact_id"] for artifact in session_listing["artifacts"]}
        assert result["artifact_id"] in ids

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
        assert "artifact-runtime/plotly.min.js" in served.text
        assert "window.__artifactSmoke" in served.text

        runtime = client.get("/api/artifacts/artifact-runtime/plotly.min.js")
        assert runtime.status_code == 200
        assert runtime.headers["x-content-type-options"] == "nosniff"
        assert "window.Plotly" in runtime.text or "Plotly.register" in runtime.text

        exported = client.get(f"/api/artifacts/{result['artifact_id']}/export?version={result['version']}")
        assert exported.status_code == 200
        assert exported.headers["content-disposition"] == f'attachment; filename="{result["artifact_id"]}-v{result["version"]}.html"'
        assert "script-src 'nonce-" in exported.headers["content-security-policy"]
        assert "artifact-runtime/plotly.min.js" not in exported.text
        assert "window.Plotly" in exported.text or "Plotly.register" in exported.text
