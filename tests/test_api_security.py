"""Origin/Host validation and token authentication (dataclaw.api.security)."""

from __future__ import annotations

import json
import logging
import os
import stat
from pathlib import Path

import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from dataclaw.api import security
from dataclaw.api.routers import auth as auth_router
from dataclaw.api.routers import terminal as terminal_router
from dataclaw.config import paths
from dataclaw.config.secure_io import write_private_text

TOKEN = "test-token-123"
FOREIGN = "http://evil.example"


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(security.SecurityMiddleware)
    app.include_router(auth_router.router, prefix="/api/auth")
    app.include_router(terminal_router.router, prefix="/api/terminal")

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/ping")
    async def ping() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/api/thing")
    async def post_thing() -> dict[str, bool]:
        return {"ok": True}

    @app.patch("/api/config")
    async def patch_config() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/api/workspace/files")
    async def files(path: str) -> dict[str, str]:
        return {"path": path}

    @app.get("/api/artifacts/artifact-runtime/plotly.min.js")
    async def plotly() -> dict[str, bool]:
        return {"ok": True}

    @app.websocket("/api/echo/ws")
    async def echo(ws: WebSocket) -> None:
        await ws.accept()
        await ws.send_text(await ws.receive_text())
        await ws.close()

    @app.get("/{path:path}")
    async def spa(path: str) -> dict[str, str]:
        return {"spa": path}

    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(_app())


@pytest.fixture
def remote(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """A server bound to all interfaces, which requires the token."""
    monkeypatch.setenv("DATACLAW_HOST", "0.0.0.0")
    monkeypatch.setenv("DATACLAW_TOKEN", TOKEN)
    return TestClient(_app())


# ── Origin ──────────────────────────────────────────────────────────────────


def test_websocket_with_foreign_origin_is_rejected(client: TestClient) -> None:
    # The real terminal endpoint: rejected before accept, so no shell starts.
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/api/terminal/ws", headers={"origin": FOREIGN}):
            pass
    assert exc.value.code == 1008


@pytest.mark.parametrize("origin", ["http://testserver", "http://localhost:5173"])
def test_websocket_with_allowed_origin_is_accepted(client: TestClient, origin: str) -> None:
    with client.websocket_connect("/api/echo/ws", headers={"origin": origin}) as ws:
        ws.send_text("hi")
        assert ws.receive_text() == "hi"


@pytest.mark.parametrize("method", ["post", "patch"])
def test_state_changing_request_with_foreign_origin_is_rejected(client: TestClient, method: str) -> None:
    path = "/api/thing" if method == "post" else "/api/config"
    resp = getattr(client, method)(path, headers={"origin": FOREIGN})
    assert resp.status_code == 403
    assert getattr(client, method)(path, headers={"origin": "null"}).status_code == 403


@pytest.mark.parametrize(
    "headers",
    [
        {},  # CLI / server-to-server
        {"origin": "http://testserver"},  # the app's own origin
        {"origin": "http://localhost:5173"},  # dev server (CORS list)
    ],
)
def test_allowed_or_missing_origin_passes(client: TestClient, headers: dict[str, str]) -> None:
    assert client.post("/api/thing", headers=headers).status_code == 200


def test_configured_extra_origin_passes(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATACLAW_ALLOWED_ORIGINS", "https://dataclaw.internal, http://other:9000")
    assert client.post("/api/thing", headers={"origin": "https://dataclaw.internal"}).status_code == 200
    assert client.post("/api/thing", headers={"origin": FOREIGN}).status_code == 403


def test_safe_methods_are_not_origin_checked(client: TestClient) -> None:
    assert client.get("/api/ping", headers={"origin": FOREIGN}).status_code == 200


# ── Host ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("host", ["localhost:8000", "127.0.0.1:8000", "[::1]:8000", "app.localhost"])
def test_loopback_host_names_pass(client: TestClient, host: str) -> None:
    assert client.get("/api/ping", headers={"host": host}).status_code == 200


def test_foreign_host_is_rejected_on_loopback_bind(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    assert client.get("/api/ping", headers={"host": "evil.example:8000"}).status_code == 400
    monkeypatch.setenv("DATACLAW_ALLOWED_HOSTS", "testserver,dataclaw.lan")
    assert client.get("/api/ping", headers={"host": "dataclaw.lan:8000"}).status_code == 200


def test_foreign_host_websocket_is_rejected(client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/echo/ws", headers={"host": "evil.example"}):
            pass


def test_any_host_passes_on_non_loopback_bind(remote: TestClient) -> None:
    resp = remote.get("/api/ping", headers={"host": "192.168.1.20:8000", "x-dataclaw-token": TOKEN})
    assert resp.status_code == 200


# ── Token ───────────────────────────────────────────────────────────────────


def test_token_optional_on_loopback(client: TestClient) -> None:
    assert client.get("/api/ping").status_code == 200
    assert client.get("/api/auth/status").json() == {"auth_required": False, "authenticated": True}


def test_token_can_be_required_on_loopback(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATACLAW_AUTH", "token")
    monkeypatch.setenv("DATACLAW_TOKEN", TOKEN)
    assert client.get("/api/ping").status_code == 401
    assert client.get("/api/ping", headers={"authorization": f"Bearer {TOKEN}"}).status_code == 200


def test_token_required_on_non_loopback_bind(remote: TestClient) -> None:
    resp = remote.get("/api/ping")
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"] == "Bearer"
    # Loopback requests are not exempt.
    assert remote.get("/api/ping", headers={"host": "127.0.0.1:8000"}).status_code == 401
    assert remote.post("/api/thing").status_code == 401
    assert remote.get("/api/ping", headers={"authorization": "Bearer wrong"}).status_code == 401
    assert remote.get("/docs").status_code == 401


@pytest.mark.parametrize(
    "headers",
    [{"authorization": f"Bearer {TOKEN}"}, {"x-dataclaw-token": TOKEN}],
)
def test_bearer_and_header_tokens_accepted(remote: TestClient, headers: dict[str, str]) -> None:
    assert remote.get("/api/ping", headers=headers).status_code == 200
    assert remote.post("/api/thing", headers=headers).status_code == 200


def test_health_spa_and_runtime_assets_stay_open(remote: TestClient) -> None:
    assert remote.get("/api/health").json() == {"status": "ok"}
    assert remote.get("/").status_code == 200
    assert remote.get("/chat/abc").status_code == 200
    assert remote.get("/api/artifacts/artifact-runtime/plotly.min.js").status_code == 200
    assert remote.get("/api/auth/status").json() == {"auth_required": True, "authenticated": False}


def test_cookie_login_flow(remote: TestClient) -> None:
    assert remote.post("/api/auth/login", json={"token": "wrong"}).status_code == 401
    assert remote.get("/api/ping").status_code == 401

    resp = remote.post("/api/auth/login", json={"token": TOKEN}, headers={"origin": "http://testserver"})
    assert resp.status_code == 200
    set_cookie = resp.headers["set-cookie"]
    assert set_cookie.startswith(f"{security.cookie_name()}=")
    assert "HttpOnly" in set_cookie
    assert "SameSite=strict" in set_cookie
    assert TOKEN not in set_cookie

    assert remote.get("/api/ping").status_code == 200
    assert remote.get("/api/auth/status").json()["authenticated"] is True

    remote.post("/api/auth/logout")
    assert remote.get("/api/ping").status_code == 401


def test_login_endpoint_rejects_foreign_origin(remote: TestClient) -> None:
    assert remote.post("/api/auth/login", json={"token": TOKEN}, headers={"origin": FOREIGN}).status_code == 403


def test_token_query_on_ui_url_sets_cookie_and_redirects(remote: TestClient) -> None:
    resp = remote.get(f"/chat/1?token={TOKEN}&tab=x", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/chat/1?tab=x"
    assert "HttpOnly" in resp.headers["set-cookie"]
    assert remote.get("/api/ping").status_code == 200


def test_token_query_redirect_stays_on_site(remote: TestClient) -> None:
    resp = remote.get(f"//evil.example/?token={TOKEN}", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"


def test_wrong_token_query_does_not_log_in(remote: TestClient) -> None:
    assert remote.get("/?token=wrong", follow_redirects=False).status_code == 200
    assert remote.get("/api/ping").status_code == 401


def test_websocket_requires_cookie_when_token_required(remote: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect):
        with remote.websocket_connect("/api/echo/ws", headers={"origin": "http://testserver"}):
            pass

    remote.post("/api/auth/login", json={"token": TOKEN})
    with remote.websocket_connect("/api/echo/ws", headers={"origin": "http://testserver"}) as ws:
        ws.send_text("hi")
        assert ws.receive_text() == "hi"

    # A valid cookie does not let a foreign page in.
    with pytest.raises(WebSocketDisconnect):
        with remote.websocket_connect("/api/echo/ws", headers={"origin": FOREIGN}):
            pass


def test_signed_urls_grant_only_the_signed_get(remote: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    params = security.sign_url_params("/api/workspace/files", {"path": "/ws/a.png"})
    assert set(params) == {"path", "dc_exp", "dc_sig"}
    assert remote.get("/api/workspace/files", params=params).json() == {"path": "/ws/a.png"}

    tampered = {**params, "path": "/ws/secret.csv"}
    assert remote.get("/api/workspace/files", params=tampered).status_code == 401
    assert remote.get("/api/ping", params=params).status_code == 401

    monkeypatch.setattr(security.time, "time", lambda: 10**12)
    assert remote.get("/api/workspace/files", params=params).status_code == 401


def test_signing_is_a_no_op_without_enforced_auth() -> None:
    assert security.sign_url_params("/api/workspace/files", {"path": "x"}) == {"path": "x"}


# ── Token generation ────────────────────────────────────────────────────────


def test_generated_token_is_persisted_privately(
    tmp_dataclaw_home: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("DATACLAW_HOST", "0.0.0.0")
    with caplog.at_level(logging.WARNING, logger="dataclaw.api.security"):
        security.log_startup_status()
    path = paths.api_token_path()
    token = path.read_text().strip()
    assert len(token) >= 32
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert f"/?token={token}" in caplog.text

    # Restarts reuse the same token and do not print it again.
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="dataclaw.api.security"):
        security.log_startup_status()
    assert security.api_token() == token
    assert token not in caplog.text


def test_configured_token_takes_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    write_private_text(paths.api_token_path(), "from-file\n")
    assert security.api_token() == "from-file"
    monkeypatch.setenv("DATACLAW_TOKEN", "from-env")
    assert security.api_token() == "from-env"


# ── Server-to-server callers on the real app ────────────────────────────────


@pytest.fixture
def full_app(monkeypatch: pytest.MonkeyPatch):
    from dataclaw.api.app import create_app

    monkeypatch.setenv("DATACLAW_HOST", "0.0.0.0")
    monkeypatch.setenv("DATACLAW_TOKEN", TOKEN)
    with TestClient(create_app()) as client:
        yield client


def test_openclaw_tool_proxy_and_callbacks_need_the_token(full_app: TestClient) -> None:
    auth = {"X-Dataclaw-Token": TOKEN}
    assert full_app.post("/api/chat/sessions", json={"title": "t"}).status_code == 401
    session_id = full_app.post("/api/chat/sessions", json={"title": "t"}, headers=auth).json()["id"]

    tool_call = {"session_id": session_id, "params": {}}
    assert full_app.post("/api/tools/list_skills/call", json=tool_call).status_code == 401
    # The OpenClaw tools client sends both headers.
    resp = full_app.post(
        "/api/tools/list_skills/call",
        json=tool_call,
        headers={**auth, "Authorization": f"Bearer {TOKEN}"},
    )
    assert resp.status_code == 200

    persist = {"role": "assistant", "content": "hello", "messageId": "m1"}
    persist_path = f"/api/chat/sessions/{session_id}/message"
    assert full_app.post(persist_path, json=persist).status_code == 401
    assert full_app.post(persist_path, json=persist, headers=auth).status_code == 200

    callback_path = f"/api/agent/callback/{session_id}"
    assert full_app.post(callback_path, json={"text": "hi"}).status_code == 401
    # No active run, but authentication passed.
    assert full_app.post(callback_path, json={"text": "hi"}, headers=auth).status_code == 404


def test_config_write_is_private(full_app: TestClient) -> None:
    auth = {"X-Dataclaw-Token": TOKEN}
    cfg = paths.config_path()
    assert stat.S_IMODE(cfg.stat().st_mode) == 0o600
    resp = full_app.patch("/api/config", json={"app": {"max_turns": 7}}, headers=auth)
    assert resp.status_code == 200
    assert json.loads(cfg.read_text())["app"]["max_turns"] == 7
    assert stat.S_IMODE(cfg.stat().st_mode) == 0o600


# ── Atomic private writes ───────────────────────────────────────────────────


def test_write_private_text_is_atomic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "dataclaw.config.json"
    target.write_text('{"old": true}')
    target.chmod(0o644)

    def fail(*_args, **_kwargs):
        raise OSError("disk full")

    with monkeypatch.context() as m:
        m.setattr(os, "replace", fail)
        with pytest.raises(OSError):
            write_private_text(target, '{"new": true}')
    assert target.read_text() == '{"old": true}'
    assert [p.name for p in tmp_path.iterdir() if p.name != ".dataclaw"] == ["dataclaw.config.json"]

    write_private_text(target, '{"new": true}')
    assert target.read_text() == '{"new": true}'
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_existing_world_readable_config_is_tightened(tmp_path: Path) -> None:
    from dataclaw.config.secure_io import restrict_permissions

    cfg = tmp_path / "dataclaw.config.json"
    cfg.write_text("{}")
    cfg.chmod(0o644)
    restrict_permissions(cfg)
    assert stat.S_IMODE(cfg.stat().st_mode) == 0o600


def test_write_private_text_follows_symlinks(tmp_path: Path) -> None:
    real = tmp_path / "real.json"
    real.write_text("{}")
    link = tmp_path / "link.json"
    link.symlink_to(real)
    write_private_text(link, '{"a": 1}')
    assert link.is_symlink()
    assert real.read_text() == '{"a": 1}'


# ── Integrations send the token ─────────────────────────────────────────────


def test_preview_asset_urls_are_signed_when_auth_enforced(remote: TestClient) -> None:
    from dataclaw.api.routers.files import _workspace_file_href

    href = _workspace_file_href(Path("/ws/a b.png"), "v=1", "top")
    assert href.startswith("../files?path=%2Fws%2Fa%20b.png&asset_query=v%3D1&dc_exp=")
    assert href.endswith("#top")
    query = href.split("?", 1)[1].split("#", 1)[0]
    assert remote.get(f"/api/workspace/files?{query}").status_code == 200


def test_openclaw_shared_token_follows_api_token(monkeypatch: pytest.MonkeyPatch) -> None:
    from dataclaw_openclaw.shared_token import resolve_shared_token

    write_private_text(paths.api_token_path(), "generated\n")
    # Fresh installs no longer fall back to a well-known value.
    assert resolve_shared_token({}) == "generated"
    # Without enforced auth an explicitly configured token is still honoured.
    assert resolve_shared_token({"token": "dataclaw-local"}) == "dataclaw-local"
    # With enforced auth OpenClaw must present the API token.
    monkeypatch.setenv("DATACLAW_HOST", "0.0.0.0")
    assert resolve_shared_token({"token": "dataclaw-local"}) == "generated"


def test_hermes_extension_environment_carries_token(tmp_path: Path) -> None:
    from dataclaw_hermes.config import HermesConfig
    from dataclaw_hermes.installer import install_extension

    write_private_text(paths.api_token_path(), "generated\n")
    source = tmp_path / "src"
    source.mkdir()
    (source / "plugin.yaml").write_text("name: dataclaw\n")
    config = HermesConfig(
        url="http://127.0.0.1:8642",
        api_key="k",
        dataclaw_api_url="http://127.0.0.1:8000",
        profile="dataclaw",
        model="",
        provider="",
        utility_backend="",
        utility_model="",
        cli_path="hermes",
        request_timeout_seconds=60,
        reconnect_timeout_seconds=30,
        tool_callback_timeout_seconds=330,
    )
    result = install_extension(source, hermes_home=tmp_path / "hermes", config=config)
    env_path = Path(result["environment"])
    assert json.loads(env_path.read_text())["DATACLAW_TOKEN"] == "generated"
    assert stat.S_IMODE(env_path.stat().st_mode) == 0o600


def test_notebook_kernels_receive_token_and_api_url(tmp_path: Path) -> None:
    from dataclaw_notebooks.manager import NotebookManager

    write_private_text(paths.api_token_path(), "generated\n")
    env = NotebookManager(tmp_path / "notebooks")._kernel_env()
    assert env["DATACLAW_TOKEN"] == "generated"
    assert env["DATACLAW_API_URL"] == "http://127.0.0.1:8000"
