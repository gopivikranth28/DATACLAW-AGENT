"""Tests for auto-project creation when a session has no project_id."""

import pytest
from pathlib import Path
from unittest.mock import patch

import dataclaw.config.paths as paths
from dataclaw.storage import sessions
from dataclaw_projects.registry import list_projects, _read_registry


@pytest.fixture(autouse=True)
def tmp_home(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DATACLAW_HOME", tmp_path)
    paths.ensure_dirs()
    return tmp_path


# ── Auto-project creation ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_session_without_project_creates_one(tmp_home):
    """Creating a session without a project_id auto-creates a session-scoped project."""
    from dataclaw.api.routers.chat import create_chat_session, CreateSessionRequest

    req = CreateSessionRequest(title="Quick Analysis")
    session = await create_chat_session(req)

    # Session should have a project attached
    assert session["projectId"] is not None

    # A project should exist in the registry
    projects = list_projects()
    assert len(projects) == 1
    assert projects[0]["name"] == "Quick Analysis"

    # Project directory should be under workspaces/{session_id}/
    project_dir = Path(projects[0]["directory"])
    assert project_dir.parent == paths.workspaces_dir()
    assert project_dir.name == session["id"]
    assert project_dir.exists()


@pytest.mark.asyncio
async def test_session_with_project_uses_existing(tmp_home):
    """Creating a session with an explicit project_id does not auto-create."""
    from dataclaw.api.routers.chat import create_chat_session, CreateSessionRequest
    from dataclaw_projects.registry import create_project

    proj = create_project(name="My Project", directory=str(tmp_home / "my-proj"))

    req = CreateSessionRequest(project_id=proj["id"], title="Work Session")
    session = await create_chat_session(req)

    assert session["projectId"] == proj["id"]
    # Should still be only the one manually-created project
    assert len(list_projects()) == 1


@pytest.mark.asyncio
async def test_auto_project_dir_is_under_workspaces(tmp_home):
    """Auto-created project directory is under ~/.dataclaw/workspaces/."""
    from dataclaw.api.routers.chat import create_chat_session, CreateSessionRequest

    req = CreateSessionRequest()
    session = await create_chat_session(req)

    registry = _read_registry()
    assert len(registry) == 1
    project_dir = Path(registry[0]["directory"])
    assert str(project_dir).startswith(str(paths.workspaces_dir()))
