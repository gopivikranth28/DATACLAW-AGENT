"""App-level LLM backend behavior: config migration on startup, masking, and
a visible error state (not a crash or a silent mock) for a missing API key."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from dataclaw.api.app import create_app
from dataclaw.config.paths import config_path
from dataclaw.config.resolver import invalidate_cache


@pytest.fixture(autouse=True)
def _no_llm_env(monkeypatch: pytest.MonkeyPatch):
    for name in (
        "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL", "OPENAI_API_KEY", "GOOGLE_API_KEY",
        "DATACLAW_UTILITY_BACKEND", "DATACLAW_LLM_BACKEND", "DATACLAW_AGENT_RUNTIME",
    ):
        monkeypatch.delenv(name, raising=False)
    invalidate_cache()
    yield
    invalidate_cache()


def _write(config: dict) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config))
    invalidate_cache()


def test_startup_migrates_legacy_llm_config_and_masks_secrets() -> None:
    _write({
        "agent": {"runtime": "dataclaw"},
        "llm": {"backend": "anthropic", "anthropic": {"api_key": "sk-ant-api03-secret-value"}},
    })

    with TestClient(create_app()) as client:
        on_disk = json.loads(config_path().read_text())
        assert "anthropic" not in on_disk["llm"]
        assert on_disk["llm"]["backends"]["anthropic"]["api_key"] == "sk-ant-api03-secret-value"

        shown = client.get("/api/config").json()
        masked = shown["llm"]["backends"]["anthropic"]["api_key"]
        assert masked != "sk-ant-api03-secret-value" and "..." in masked
        status = shown["_runtime_status"]
        assert status["available"] is True
        assert status["last_selection_error"] is None

        backends = client.get("/api/providers/llm-backends").json()
        assert "openai_compatible" in {b["id"] for b in backends}


def test_missing_api_key_surfaces_runtime_error_instead_of_mock() -> None:
    _write({"agent": {"runtime": "dataclaw"}, "llm": {"backend": "anthropic", "backends": {}}})

    with TestClient(create_app()) as client:
        status = client.get("/api/config").json()["_runtime_status"]

    assert status["available"] is False
    assert status["configured_runtime"] == "dataclaw"
    assert "ANTHROPIC_API_KEY" in status["last_selection_error"]
    assert "llm.backends.anthropic.api_key" in status["last_selection_error"]
