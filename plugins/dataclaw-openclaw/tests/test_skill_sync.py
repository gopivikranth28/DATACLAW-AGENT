"""Tests for syncing Dataclaw skills into OpenClaw's managed skills dir."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import dataclaw.config.resolver as resolver
import dataclaw_openclaw.skill_sync as skill_sync


@pytest.fixture
def openclaw_home(tmp_path: Path, monkeypatch) -> Path:
    home = tmp_path / ".openclaw"
    home.mkdir()
    monkeypatch.setattr(resolver, "resolve", lambda *_args, **_kwargs: str(tmp_path))
    monkeypatch.setattr(
        skill_sync,
        "read_skill",
        lambda skill_id: {"id": skill_id, "name": "Churn", "description": "Churn analysis", "body": "Do it."}
        if skill_id == "churn" else None,
    )
    return home


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(skill_sync.router, prefix="/openclaw")
    return TestClient(app)


def test_sync_writes_to_managed_skills_dir_not_the_plugin_install(client, openclaw_home) -> None:
    res = client.post("/openclaw/skills/churn/sync")

    assert res.status_code == 200
    target = openclaw_home / "skills" / "churn" / "SKILL.md"
    assert res.json() == {"synced_to": str(target)}
    assert target.read_text().startswith("---\nname: Churn\ndescription: Churn analysis\n---\n")
    assert (openclaw_home / "skills" / "churn" / skill_sync.SYNC_MARKER).exists()
    assert not (openclaw_home / "extensions").exists()

    # Re-syncing our own copy is fine; unsync removes it.
    assert client.post("/openclaw/skills/churn/sync").status_code == 200
    assert client.delete("/openclaw/skills/churn/sync").status_code == 204
    assert not (openclaw_home / "skills" / "churn").exists()


def test_sync_and_unsync_leave_foreign_skills_alone(client, openclaw_home) -> None:
    foreign = openclaw_home / "skills" / "churn"
    foreign.mkdir(parents=True)
    (foreign / "SKILL.md").write_text("user's own skill")

    assert client.post("/openclaw/skills/churn/sync").status_code == 409
    assert client.delete("/openclaw/skills/churn/sync").status_code == 409
    assert (foreign / "SKILL.md").read_text() == "user's own skill"


def test_sync_unknown_skill_is_404(client, openclaw_home) -> None:
    assert client.post("/openclaw/skills/nope/sync").status_code == 404
