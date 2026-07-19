"""Tests for the independent-session versus project-session boundary."""

import json

import pytest
import dataclaw.config.paths as paths
from dataclaw_projects.registry import create_project, list_projects


@pytest.fixture(autouse=True)
def tmp_home(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DATACLAW_HOME", tmp_path)
    paths.ensure_dirs()
    return tmp_path


# ── Independent session creation ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_session_without_project_stays_independent(tmp_home):
    """Creating from Chats never creates or attaches a project."""
    from dataclaw.api.routers.chat import create_chat_session, CreateSessionRequest

    req = CreateSessionRequest(title="Quick Analysis")
    session = await create_chat_session(req)

    assert session["projectId"] is None
    assert list_projects() == []


@pytest.mark.asyncio
async def test_session_with_project_uses_existing(tmp_home):
    """Creating a session with an explicit project_id does not auto-create."""
    from dataclaw.api.routers.chat import create_chat_session, CreateSessionRequest
    proj = create_project(name="My Project", directory=str(tmp_home / "my-proj"))

    req = CreateSessionRequest(project_id=proj["id"], title="Work Session")
    session = await create_chat_session(req)

    assert session["projectId"] == proj["id"]
    # Should still be only the one manually-created project
    assert len(list_projects()) == 1


@pytest.mark.asyncio
async def test_independent_listing_excludes_project_sessions(tmp_home):
    from dataclaw.storage import sessions

    independent = await sessions.create_session(title="Independent")
    project_session = await sessions.create_session(title="Project chat", project_id="project-1")

    listed = await sessions.list_sessions(independent_only=True)
    assert [item["id"] for item in listed] == [independent["id"]]
    assert (await sessions.list_sessions("project-1"))[0]["id"] == project_session["id"]


@pytest.mark.asyncio
async def test_legacy_project_id_session_stays_out_of_independent_listing(tmp_home):
    """Old snake-case session metadata must retain its project boundary."""
    from dataclaw.storage import sessions

    legacy_path = paths.sessions_dir() / "legacy-project-chat.json"
    legacy_path.write_text(json.dumps({
        "id": "legacy-project-chat",
        "project_id": "project-legacy",
        "title": "Legacy project chat",
        "messages": [],
    }))

    assert await sessions.list_sessions(independent_only=True) == []
    listed = await sessions.list_sessions("project-legacy")
    assert [item["id"] for item in listed] == ["legacy-project-chat"]
    assert (await sessions.get_session("legacy-project-chat"))["projectId"] == "project-legacy"


@pytest.mark.asyncio
async def test_project_chat_files_include_session_outputs_and_project_workspace(tmp_home):
    """A project chat must not hide files generated in its own session workspace."""
    from dataclaw.api.routers.chat import get_chat_session_files
    from dataclaw.storage import sessions

    project_dir = tmp_home / "project-workspace"
    project_dir.mkdir()
    (project_dir / "shared-data.csv").write_text("value\n1\n")
    project = create_project(name="Research", directory=str(project_dir))
    session = await sessions.create_session(title="Project analysis", project_id=project["id"])

    session_dir = paths.workspaces_dir() / session["id"]
    session_dir.mkdir()
    (session_dir / "analysis.md").write_text("# Session output\n")

    files = await get_chat_session_files(session["id"])

    assert files["kind"] == "project"
    assert [item["name"] for item in files["files"]] == ["analysis.md"]
    assert [item["name"] for item in files["projectFiles"]] == ["shared-data.csv"]


@pytest.mark.asyncio
async def test_independent_chat_files_only_use_its_session_workspace(tmp_home):
    from dataclaw.api.routers.chat import get_chat_session_files
    from dataclaw.storage import sessions

    session = await sessions.create_session(title="Independent analysis")
    session_dir = paths.workspaces_dir() / session["id"]
    session_dir.mkdir()
    (session_dir / "notes.txt").write_text("private session notes")

    files = await get_chat_session_files(session["id"])

    assert files == {
        "files": [{"name": "notes.txt", "path": str(session_dir / "notes.txt"), "is_dir": False, "size": 21}],
        "kind": "session",
    }
