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
                "html": "<!doctype html><html><body><h1>Direct</h1></body></html>",
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
