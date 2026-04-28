"""Tests for projects and subagents plugin."""

import pytest
from pathlib import Path

import dataclaw.config.paths as paths
from dataclaw_projects.registry import (
    list_projects, get_project, create_project, delete_project, list_project_files,
)
from dataclaw_projects.subagents import (
    list_subagent_definitions, get_subagent_definition,
    create_subagent_definition, update_subagent_definition, delete_subagent_definition,
)
from dataclaw_projects.tools import list_subagents_tool, delegate_to_subagent


@pytest.fixture(autouse=True)
def tmp_home(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DATACLAW_HOME", tmp_path)
    return tmp_path


# ── Project CRUD ────────────────────────────────────────────────────────────


def test_list_empty():
    assert list_projects() == []


def test_create_project(tmp_home):
    proj_dir = tmp_home / "test-proj"
    proj = create_project(name="Test Project", description="A test", directory=str(proj_dir))
    assert proj["name"] == "Test Project"
    assert proj["id"] == "test-project"
    assert Path(proj["directory"]).exists()
    assert (Path(proj["directory"]) / ".dataclaw" / "project.json").exists()


def test_list_projects(tmp_home):
    create_project(name="Proj A", directory=str(tmp_home / "a"))
    create_project(name="Proj B", directory=str(tmp_home / "b"))
    result = list_projects()
    assert len(result) == 2


def test_get_project(tmp_home):
    create_project(name="My Proj", directory=str(tmp_home / "myproj"))
    proj = get_project("my-proj")
    assert proj["name"] == "My Proj"


def test_get_project_not_found():
    with pytest.raises(KeyError):
        get_project("nonexistent")


def test_delete_project(tmp_home):
    create_project(name="Delete Me", directory=str(tmp_home / "del"))
    assert delete_project("delete-me") is True
    assert list_projects() == []
    # User files should still exist
    assert (tmp_home / "del").exists()
    # But .dataclaw dir should be gone
    assert not (tmp_home / "del" / ".dataclaw").exists()


def test_list_project_files(tmp_home):
    proj_dir = tmp_home / "fileproj"
    create_project(name="File Proj", directory=str(proj_dir))
    (proj_dir / "data.csv").write_text("a,b\n1,2")
    (proj_dir / "subdir").mkdir()
    (proj_dir / "subdir" / "script.py").write_text("print('hi')")

    result = list_project_files("file-proj")
    names = {e["name"] for e in result["project"]}
    assert "data.csv" in names
    assert "subdir" in names


# ── Subagent CRUD ───────────────────────────────────────────────────────────


def test_list_subagents_empty():
    assert list_subagent_definitions() == []


def test_create_subagent():
    sa = create_subagent_definition(name="Research Bot", description="Does research")
    assert sa["id"] == "research-bot"
    assert sa["name"] == "Research Bot"
    assert sa["agent_type"] == "llm"


def test_get_subagent():
    create_subagent_definition(name="Getter Bot")
    sa = get_subagent_definition("getter-bot")
    assert sa["name"] == "Getter Bot"


def test_get_subagent_not_found():
    with pytest.raises(KeyError):
        get_subagent_definition("nope")


def test_update_subagent():
    create_subagent_definition(name="Updater Bot")
    updated = update_subagent_definition("updater-bot", {"description": "Updated!"})
    assert updated["description"] == "Updated!"


def test_delete_subagent():
    create_subagent_definition(name="Deleter Bot")
    assert delete_subagent_definition("deleter-bot") is True
    assert delete_subagent_definition("deleter-bot") is False


def test_create_duplicate_subagent():
    create_subagent_definition(name="Dup Bot")
    with pytest.raises(ValueError, match="already exists"):
        create_subagent_definition(name="Dup Bot")


# ── Tools ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_subagents_tool():
    create_subagent_definition(name="Tool Bot")
    result = await list_subagents_tool()
    assert len(result["subagents"]) >= 1


@pytest.mark.asyncio
async def test_delegate_tool():
    result = await delegate_to_subagent(subagent_name="test", task="do something")
    assert result["status"] == "not_implemented"
