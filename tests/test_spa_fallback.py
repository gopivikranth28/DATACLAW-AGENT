"""SPA catch-all: serves UI files only, never API paths or files outside ui/dist."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dataclaw.api.app import _mount_spa


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    ui_dir = tmp_path / "dist"
    (ui_dir / "assets").mkdir(parents=True)
    (ui_dir / "index.html").write_text("<html>index</html>")
    (ui_dir / "favicon.ico").write_text("icon")
    (tmp_path / "secret.txt").write_text("top secret")

    app = FastAPI()

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    _mount_spa(app, ui_dir)
    return TestClient(app)


def test_serves_ui_files_and_falls_back_to_index(client: TestClient) -> None:
    assert client.get("/favicon.ico").text == "icon"
    assert client.get("/chat/some-session").text == "<html>index</html>"


def test_api_routes_take_precedence(client: TestClient) -> None:
    assert client.get("/api/health").json() == {"status": "ok"}


def test_unknown_api_path_is_404_not_index(client: TestClient) -> None:
    resp = client.get("/api/does-not-exist")
    assert resp.status_code == 404


@pytest.mark.parametrize("path", ["//etc/hostname", "/..%2Fsecret.txt", "/%2E%2E/secret.txt"])
def test_paths_outside_ui_dir_are_not_served(client: TestClient, tmp_path: Path, path: str) -> None:
    secret = tmp_path / "secret.txt"
    absolute = client.get("/" + str(secret))
    assert "top secret" not in absolute.text

    resp = client.get(path)
    assert "top secret" not in resp.text
    assert resp.text == "<html>index</html>"
