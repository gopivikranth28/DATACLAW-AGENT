"""OpenRouter key provisioning, status and rotation; preset migration; masking.

The management key must never be persisted, logged, returned or echoed in an
error.  OpenRouter is mocked with an httpx MockTransport; no keys are created.
"""

from __future__ import annotations

import json
import logging
import stat
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dataclaw.api.routers import config as config_router
from dataclaw.api.routers import openrouter as openrouter_router
from dataclaw.config.migrations import backup_path, migrate_config, migrate_config_file
from dataclaw.config.resolver import invalidate_cache
from dataclaw.providers.llm import openrouter_keys as keys
from dataclaw.providers.llm.registry import resolve_backend_config

MANAGEMENT_KEY = "sk-or-v1-mgmt-0123456789abcdef-MANAGEMENT"
NEW_KEY = "sk-or-v1-inference-new-fedcba9876543210"
OLD_KEY = "sk-or-v1-inference-old-1111111111111111"


class FakeOpenRouter:
    """Routes key-management requests to canned responses and records them."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.routes: dict[tuple[str, str], list[httpx.Response | Exception]] = {}

    def on(self, method: str, path: str, *responses: httpx.Response | Exception) -> None:
        self.routes.setdefault((method, path), []).extend(responses)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        item = self.routes[(request.method, request.url.path)].pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def bodies(self, method: str, path: str) -> list[dict[str, Any]]:
        return [json.loads(r.content) for r in self.requests if r.method == method and r.url.path == path]


def created(key: str = NEW_KEY, key_hash: str = "hash-new", **data: Any) -> httpx.Response:
    return httpx.Response(201, json={
        "key": key,
        "data": {"hash": key_hash, "name": "dataclaw-test", "label": f"{key[:11]}...{key[-4:]}",
                 "limit": None, "limit_reset": None, "expires_at": None, **data},
    })


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeOpenRouter:
    recorder = FakeOpenRouter()
    monkeypatch.setattr(keys, "TRANSPORT", httpx.MockTransport(recorder))
    monkeypatch.setattr(keys.socket, "gethostname", lambda: "lab-box")
    return recorder


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_dataclaw_home: Path):
    for name in ("OPENROUTER_API_KEY", "OPENROUTER_MANAGEMENT_KEY"):
        monkeypatch.delenv(name, raising=False)

    async def no_reload(request):
        return None

    monkeypatch.setattr(config_router, "reload_runtime", no_reload)
    app = FastAPI()
    app.include_router(config_router.router, prefix="/api/config")
    app.include_router(openrouter_router.router, prefix="/api/providers/openrouter")
    invalidate_cache()
    with TestClient(app) as test_client:
        yield test_client
    invalidate_cache()


def config_file(home: Path) -> Path:
    return home / "dataclaw.config.json"


def read_config(home: Path) -> dict[str, Any]:
    return json.loads(config_file(home).read_text())


def assert_management_key_absent(home: Path, caplog: pytest.LogCaptureFixture, *texts: str) -> None:
    for path in home.rglob("*"):
        if path.is_file():
            assert MANAGEMENT_KEY not in path.read_text(errors="ignore"), path
    for record in caplog.records:
        assert MANAGEMENT_KEY not in record.getMessage()
        assert MANAGEMENT_KEY not in str(record.args)
        if record.exc_info:
            assert MANAGEMENT_KEY not in logging.Formatter().formatException(record.exc_info)
    for text in texts:
        assert MANAGEMENT_KEY not in text


# ── Provisioning ────────────────────────────────────────────────────────────


def test_provision_stores_only_the_inference_key(client, fake, tmp_dataclaw_home, caplog):
    caplog.set_level(logging.DEBUG)
    fake.on("POST", "/api/v1/keys", created(limit=25.0, limit_reset="monthly", expires_at="2027-01-31T00:00:00Z"))
    response = client.post("/api/providers/openrouter/provision", json={
        "management_key": MANAGEMENT_KEY,
        "limit_usd": 25,
        "limit_reset": "monthly",
        "expires_at": "2027-01-31T00:00:00+00:00",
        "use_for_llm": True,
        "use_for_decisions": True,
    })
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "provisioned"
    assert result["key_hash"] == "hash-new" and result["limit"] == 25.0 and result["limit_reset"] == "monthly"
    assert NEW_KEY not in response.text  # the secret is stored, not returned

    request = fake.requests[0]
    assert request.method == "POST" and str(request.url) == "https://openrouter.ai/api/v1/keys"
    assert request.headers["authorization"] == f"Bearer {MANAGEMENT_KEY}"
    assert json.loads(request.content) == {
        "name": "dataclaw-lab-box",
        "limit": 25.0,
        "limit_reset": "monthly",
        "expires_at": "2027-01-31T00:00:00Z",
    }

    stored = read_config(tmp_dataclaw_home)
    assert stored["llm"]["backends"]["openrouter"] == {
        "api_key": NEW_KEY,
        "key_hash": "hash-new",
        "key_name": "dataclaw-test",
        "key_label": f"{NEW_KEY[:11]}...{NEW_KEY[-4:]}",
    }
    assert stored["llm"]["backend"] == "openrouter"
    assert stored["decision"]["backend"] == "openrouter"
    # The config now holds an inference key, so it must stay owner-only.
    assert stat.S_IMODE(config_file(tmp_dataclaw_home).stat().st_mode) == 0o600
    assert resolve_backend_config("openrouter").api_key == NEW_KEY
    assert_management_key_absent(tmp_dataclaw_home, caplog, response.text)


def test_provision_minimal_request_and_env_management_key(client, fake, tmp_dataclaw_home, monkeypatch, caplog):
    monkeypatch.setenv("OPENROUTER_MANAGEMENT_KEY", MANAGEMENT_KEY)
    fake.on("POST", "/api/v1/keys", created())
    response = client.post("/api/providers/openrouter/provision", json={"name": "ci-runner"})
    assert response.status_code == 200, response.text
    assert fake.bodies("POST", "/api/v1/keys") == [{"name": "ci-runner"}]
    assert fake.requests[0].headers["authorization"] == f"Bearer {MANAGEMENT_KEY}"
    stored = read_config(tmp_dataclaw_home)
    assert "backend" not in stored["llm"] and "decision" not in stored
    assert_management_key_absent(tmp_dataclaw_home, caplog, response.text)


@pytest.mark.parametrize(
    ("status", "body", "expected_status", "expected"),
    [
        (401, {"error": {"code": 401, "message": "Invalid credentials"}}, 401, "rejected the management key"),
        (403, {"error": {"code": 403, "message": "Only management keys can perform this operation"}}, 403, "not a management key"),
        (429, {"error": {"code": 429, "message": "Too many"}}, 429, "rate-limited"),
        (500, {"error": {"code": 500, "message": f"boom for {MANAGEMENT_KEY}"}}, 502, "[redacted]"),
        (400, {"error": {"code": 400, "message": "limit must be positive"}}, 400, "limit must be positive"),
    ],
)
def test_provision_failures_are_safe(client, fake, tmp_dataclaw_home, caplog, status, body, expected_status, expected):
    caplog.set_level(logging.DEBUG)
    fake.on("POST", "/api/v1/keys", httpx.Response(status, json=body))
    response = client.post("/api/providers/openrouter/provision", json={"management_key": MANAGEMENT_KEY})
    assert response.status_code == expected_status
    assert expected in response.json()["detail"]
    assert not config_file(tmp_dataclaw_home).exists()
    assert_management_key_absent(tmp_dataclaw_home, caplog, response.text)


def test_provision_transport_error_is_safe(client, fake, tmp_dataclaw_home, caplog):
    caplog.set_level(logging.DEBUG)
    fake.on("POST", "/api/v1/keys", httpx.ConnectError(f"cannot connect with {MANAGEMENT_KEY}"))
    response = client.post("/api/providers/openrouter/provision", json={"management_key": MANAGEMENT_KEY})
    assert response.status_code == 502
    assert response.json()["detail"] == "Unable to reach OpenRouter to create the key (ConnectError)."
    assert_management_key_absent(tmp_dataclaw_home, caplog, response.text)


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({}, "management key is required"),
        ({"management_key": "   "}, "management key is required"),
        ({"management_key": MANAGEMENT_KEY, "limit_usd": -1}, "zero or more"),
        ({"management_key": MANAGEMENT_KEY, "limit_reset": "yearly"}, "daily, weekly, monthly"),
        ({"management_key": MANAGEMENT_KEY, "expires_at": "tomorrow"}, "ISO 8601"),
        ({"management_key": MANAGEMENT_KEY, "expires_at": "2001-01-01T00:00:00Z"}, "in the future"),
        ({"management_key": MANAGEMENT_KEY, "limit_usd": "lots"}, "limit_usd"),
        ({"management_key": MANAGEMENT_KEY, "name": "x" * 101}, "name"),
    ],
)
def test_provision_rejects_bad_input_without_echoing_it(client, fake, tmp_dataclaw_home, caplog, payload, expected):
    response = client.post("/api/providers/openrouter/provision", json=payload)
    assert response.status_code in (400, 422)
    assert expected in response.json()["detail"]
    assert fake.requests == []
    assert_management_key_absent(tmp_dataclaw_home, caplog, response.text)


def test_management_key_is_redacted_from_reprs():
    created_key = keys.CreatedKey(key=NEW_KEY, hash="h", name="n")
    assert NEW_KEY not in repr(created_key)
    assert keys.redact(f"bad {MANAGEMENT_KEY}!", MANAGEMENT_KEY) == "bad [redacted]!"
    payload = openrouter_router._KeyRequest(management_key=MANAGEMENT_KEY)
    assert MANAGEMENT_KEY not in repr(payload) and MANAGEMENT_KEY not in str(payload.model_dump())


# ── Key status ──────────────────────────────────────────────────────────────


def test_key_status_reports_usage_with_the_inference_key(client, fake, tmp_dataclaw_home):
    config_file(tmp_dataclaw_home).write_text(json.dumps({"llm": {"backends": {"openrouter": {
        "api_key": OLD_KEY, "key_hash": "hash-old", "key_name": "dataclaw-lab-box",
    }}}}))
    invalidate_cache()
    fake.on("GET", "/api/v1/key", httpx.Response(200, json={"data": {
        "label": "sk-or-v1-inf...1111", "limit": 25, "limit_remaining": 17.5, "limit_reset": "monthly",
        "usage": 7.5, "usage_daily": 0.5, "usage_weekly": 2.0, "usage_monthly": 7.5,
        "is_free_tier": False, "is_management_key": False, "expires_at": None, "byok_usage": 0,
    }}))
    response = client.get("/api/providers/openrouter/key-status")
    assert response.status_code == 200
    status = response.json()
    assert status["configured"] is True and status["valid"] is True
    assert status["usage"] == 7.5 and status["limit"] == 25 and status["limit_remaining"] == 17.5
    assert status["key_hash"] == "hash-old" and status["key_name"] == "dataclaw-lab-box"
    assert "byok_usage" not in status
    assert fake.requests[0].headers["authorization"] == f"Bearer {OLD_KEY}"
    assert OLD_KEY not in response.text


def test_key_status_without_a_key_or_with_a_revoked_one(client, fake, tmp_dataclaw_home):
    assert client.get("/api/providers/openrouter/key-status").json() == {
        "configured": False, "valid": False, "key_hash": "", "key_name": "",
    }
    config_file(tmp_dataclaw_home).write_text(json.dumps({"llm": {"backends": {"openrouter": {"api_key": OLD_KEY}}}}))
    invalidate_cache()
    fake.on("GET", "/api/v1/key", httpx.Response(401, json={"error": {"code": 401, "message": "User not found."}}))
    status = client.get("/api/providers/openrouter/key-status").json()
    assert status["configured"] is True and status["valid"] is False
    assert "rejected the configured API key" in status["message"]


# ── Rotation ────────────────────────────────────────────────────────────────


def _provisioned(home: Path) -> None:
    config_file(home).write_text(json.dumps({"llm": {"backend": "openrouter", "backends": {"openrouter": {
        "api_key": OLD_KEY, "key_hash": "hash-old", "key_name": "dataclaw-lab-box", "model": "x-ai/grok-4.7",
    }}}}))
    invalidate_cache()


def test_rotate_swaps_the_key_then_deletes_the_old_one(client, fake, tmp_dataclaw_home, caplog):
    caplog.set_level(logging.DEBUG)
    _provisioned(tmp_dataclaw_home)
    fake.on("GET", "/api/v1/keys/hash-old", httpx.Response(200, json={"data": {
        "hash": "hash-old", "name": "dataclaw-lab-box", "limit": 40, "limit_reset": "weekly",
    }}))
    fake.on("POST", "/api/v1/keys", created(limit=40.0, limit_reset="weekly"))
    fake.on("DELETE", "/api/v1/keys/hash-old", httpx.Response(200, json={"deleted": True}))

    response = client.post("/api/providers/openrouter/rotate", json={"management_key": MANAGEMENT_KEY})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "rotated" and result["old_key_deleted"] is True and result["warning"] is None
    assert [(r.method, r.url.path) for r in fake.requests] == [
        ("GET", "/api/v1/keys/hash-old"),
        ("POST", "/api/v1/keys"),
        ("DELETE", "/api/v1/keys/hash-old"),
    ]
    # The old key's limit settings carry over.
    assert fake.bodies("POST", "/api/v1/keys") == [{"name": "dataclaw-lab-box", "limit": 40.0, "limit_reset": "weekly"}]
    stored = read_config(tmp_dataclaw_home)["llm"]["backends"]["openrouter"]
    assert stored["api_key"] == NEW_KEY and stored["key_hash"] == "hash-new"
    assert stored["model"] == "x-ai/grok-4.7"
    assert_management_key_absent(tmp_dataclaw_home, caplog, response.text)


def test_rotate_keeps_the_new_key_when_delete_fails(client, fake, tmp_dataclaw_home):
    _provisioned(tmp_dataclaw_home)
    fake.on("GET", "/api/v1/keys/hash-old", httpx.Response(404, json={"error": {"code": 404, "message": "nope"}}))
    fake.on("POST", "/api/v1/keys", created())
    fake.on("DELETE", "/api/v1/keys/hash-old", httpx.Response(500, json={"error": {"code": 500, "message": "later"}}))
    response = client.post("/api/providers/openrouter/rotate", json={"management_key": MANAGEMENT_KEY, "limit_usd": 10})
    assert response.status_code == 200
    assert response.json()["old_key_deleted"] is False
    assert "could not be deleted" in response.json()["warning"]
    assert fake.bodies("POST", "/api/v1/keys") == [{"name": "dataclaw-lab-box", "limit": 10.0}]
    assert read_config(tmp_dataclaw_home)["llm"]["backends"]["openrouter"]["api_key"] == NEW_KEY


def test_rotate_failure_leaves_the_old_key_in_place(client, fake, tmp_dataclaw_home):
    _provisioned(tmp_dataclaw_home)
    fake.on("GET", "/api/v1/keys/hash-old", httpx.Response(401, json={"error": {"code": 401, "message": "bad"}}))
    response = client.post("/api/providers/openrouter/rotate", json={"management_key": MANAGEMENT_KEY})
    assert response.status_code == 401
    assert read_config(tmp_dataclaw_home)["llm"]["backends"]["openrouter"]["api_key"] == OLD_KEY


def test_rotate_requires_a_provisioned_key(client, fake, tmp_dataclaw_home):
    config_file(tmp_dataclaw_home).write_text(json.dumps({"llm": {"backends": {"openrouter": {"api_key": OLD_KEY}}}}))
    invalidate_cache()
    response = client.post("/api/providers/openrouter/rotate", json={"management_key": MANAGEMENT_KEY})
    assert response.status_code == 400
    assert "Provision a key first" in response.json()["detail"]
    assert fake.requests == []


# ── GET /api/config masking ─────────────────────────────────────────────────


def test_config_masks_the_openrouter_key(client, fake, tmp_dataclaw_home):
    config_file(tmp_dataclaw_home).write_text(json.dumps({"llm": {"backends": {"openrouter": {
        "api_key": NEW_KEY,
        "key_hash": "hash-new",
        "routing": {"data_collection": "deny", "zdr": True},
        "headers": {"X-OpenRouter-Title": "DataClaw"},
        # Never written by DataClaw, but masked if a user adds it by hand.
        "management_key": MANAGEMENT_KEY,
    }}}}))
    raw = client.get("/api/config")
    body = raw.json()["llm"]["backends"]["openrouter"]
    assert NEW_KEY not in raw.text and MANAGEMENT_KEY not in raw.text
    assert body["api_key"] == f"{NEW_KEY[:8]}...{NEW_KEY[-4:]}"
    assert body["key_hash"] == "hash-new"
    assert body["routing"] == {"data_collection": "deny", "zdr": True}

    # Saving the masked value back keeps the real key.
    client.patch("/api/config", json={"llm": {"backends": {"openrouter": {"api_key": body["api_key"], "model": "x-ai/grok-4.7"}}}})
    stored = read_config(tmp_dataclaw_home)["llm"]["backends"]["openrouter"]
    assert stored["api_key"] == NEW_KEY and stored["model"] == "x-ai/grok-4.7"


# ── Migration from the openai_compatible preset ─────────────────────────────


def test_openrouter_preset_migrates_to_the_backend():
    raw = {
        "agent": {"runtime": "dataclaw"},
        "llm": {"backend": "openai_compatible", "backends": {"openai_compatible": {
            "preset": "openrouter",
            "base_url": "https://openrouter.ai/api/v1",
            "api_key": "sk-or-v1-preset",
            "model": "anthropic/claude-sonnet-5.5",
            "reasoning_effort": "high",
            "headers": {"X-Title": "DataClaw", "X-Team": "data"},
        }}},
    }
    assert migrate_config(raw) is True
    assert raw["llm"]["backend"] == "openrouter"
    assert "openai_compatible" not in raw["llm"]["backends"]
    assert raw["llm"]["backends"]["openrouter"] == {
        "api_key": "sk-or-v1-preset",
        "model": "anthropic/claude-sonnet-5.5",
        "reasoning_effort": "high",
        "headers": {"X-Team": "data"},
    }
    assert migrate_config(raw) is False  # idempotent


def test_preset_migration_keeps_newer_openrouter_settings_and_other_backends():
    raw = {
        "agent": {"runtime": "dataclaw"},
        "llm": {"backend": "anthropic", "backends": {
            "openai_compatible": {"preset": "openrouter", "api_key": "old", "model": "old/model"},
            "openrouter": {"api_key": "new"},
        }},
    }
    assert migrate_config(raw) is True
    assert raw["llm"]["backend"] == "anthropic"
    assert raw["llm"]["backends"]["openrouter"] == {"api_key": "new", "model": "old/model"}

    other = {"agent": {"runtime": "dataclaw"}, "llm": {"backend": "openai_compatible", "backends": {
        "openai_compatible": {"preset": "ollama", "model": "qwen3"},
    }}}
    assert migrate_config(other) is False


def test_preset_migration_runs_inside_the_backed_up_file_migration(tmp_dataclaw_home):
    path = config_file(tmp_dataclaw_home)
    original = {"agent": {"runtime": "dataclaw"}, "llm": {"backend": "openai_compatible", "backends": {
        "openai_compatible": {"preset": "openrouter", "api_key": "sk-or-v1-preset", "model": "x-ai/grok-4.7"},
    }}}
    path.write_text(json.dumps(original))
    assert migrate_config_file(path) is True
    assert json.loads(backup_path(path).read_text()) == original
    migrated = json.loads(path.read_text())
    assert migrated["llm"]["backend"] == "openrouter"
    assert migrated["llm"]["backends"]["openrouter"]["api_key"] == "sk-or-v1-preset"
