"""Tests for projects and subagents plugin."""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import dataclaw.config.paths as paths
from dataclaw_projects.registry import (
    list_projects, get_project, create_project, delete_project, list_project_files,
)
from dataclaw_projects.subagents import (
    list_subagent_definitions, get_subagent_definition,
    create_subagent_definition, update_subagent_definition, delete_subagent_definition,
)
from dataclaw_projects.tools import list_subagents_tool, make_delegate_to_subagent


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


# ── Delegate tool fixtures ──────────────────────────────────────────────────


def _make_mock_sub_agent_result():
    """Create a mock SubAgentResult."""
    from dataclaw.providers.sub_agent.provider import SubAgentResult
    return SubAgentResult(status="completed", result="Task done.", turns_used=2)


def _make_mock_provider(agent_type="llm"):
    """Create a mock SubAgentProvider."""
    provider = MagicMock()
    provider.agent_type = agent_type
    provider.run = AsyncMock(return_value=_make_mock_sub_agent_result())
    provider.config_schema = MagicMock(return_value=[])
    return provider


@pytest.fixture
def mock_providers_and_registry():
    """Create mock providers and tool registry for delegate tests."""
    from dataclaw.providers.sub_agent.registry import SubAgentRegistry
    from dataclaw.hooks.sub_agent_hooks import SubAgentHookRegistry

    providers = MagicMock()
    providers.sub_agent_registry = SubAgentRegistry()
    providers.sub_agent_registry.register(_make_mock_provider("llm"))
    providers.sub_agent_hooks = SubAgentHookRegistry()

    # Create a mock tool registry with a couple of tools
    mock_tool_a = MagicMock()
    mock_tool_a.definition = {"name": "search", "description": "Search", "parameters": {}}
    mock_tool_a.execute = AsyncMock(return_value={"results": []})

    mock_tool_b = MagicMock()
    mock_tool_b.definition = {"name": "read_file", "description": "Read a file", "parameters": {}}
    mock_tool_b.execute = AsyncMock(return_value={"content": ""})

    tool_registry = MagicMock()
    tool_registry._tools = {"search": mock_tool_a, "read_file": mock_tool_b}

    return providers, tool_registry


# ── Delegate tool tests ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delegate_tool(mock_providers_and_registry):
    providers, tool_registry = mock_providers_and_registry
    create_subagent_definition(name="Test Bot", allowed_tools=["search"])
    delegate = make_delegate_to_subagent(providers, tool_registry)

    result = await delegate(subagent_name="test-bot", task="do something")
    assert result["status"] == "completed"
    assert result["result"] == "Task done."

    # Verify the provider.run was called with filtered tools via context
    mock_provider = providers.sub_agent_registry.get("llm")
    call_kwargs = mock_provider.run.call_args
    context = call_kwargs.kwargs["context"]
    tool_names = [t["name"] for t in context.tools]
    assert "search" in tool_names
    assert "read_file" not in tool_names


@pytest.mark.asyncio
async def test_delegate_tool_unknown_subagent(mock_providers_and_registry):
    providers, tool_registry = mock_providers_and_registry
    delegate = make_delegate_to_subagent(providers, tool_registry)

    result = await delegate(subagent_name="nonexistent", task="do something")
    assert result["status"] == "error"
    assert "not found" in result["message"].lower()


@pytest.mark.asyncio
async def test_delegate_tool_unknown_agent_type(mock_providers_and_registry):
    """When the subagent's agent_type has no registered provider."""
    providers, tool_registry = mock_providers_and_registry
    create_subagent_definition(name="Rag Bot", agent_type="rag")
    delegate = make_delegate_to_subagent(providers, tool_registry)

    result = await delegate(subagent_name="rag-bot", task="find papers")
    assert result["status"] == "error"
    assert "rag" in result["message"].lower()


@pytest.mark.asyncio
async def test_delegate_tool_no_allowed_tools_passes_all(mock_providers_and_registry):
    """When allowed_tools is empty, subagent gets all tools (except delegate_to_subagent)."""
    providers, tool_registry = mock_providers_and_registry
    create_subagent_definition(name="All Tools Bot", allowed_tools=[])
    delegate = make_delegate_to_subagent(providers, tool_registry)

    result = await delegate(subagent_name="all-tools-bot", task="do something")
    assert result["status"] == "completed"

    mock_provider = providers.sub_agent_registry.get("llm")
    context = mock_provider.run.call_args.kwargs["context"]
    tool_names = [t["name"] for t in context.tools]
    assert "search" in tool_names
    assert "read_file" in tool_names


@pytest.mark.asyncio
async def test_delegate_tool_blocks_recursion(mock_providers_and_registry):
    """Subagent should never receive delegate_to_subagent tool."""
    providers, tool_registry = mock_providers_and_registry

    # Add delegate_to_subagent to the registry
    mock_delegate = MagicMock()
    mock_delegate.definition = {"name": "delegate_to_subagent", "description": "Delegate", "parameters": {}}
    mock_delegate.execute = AsyncMock()
    tool_registry._tools["delegate_to_subagent"] = mock_delegate

    create_subagent_definition(name="Recursion Bot", allowed_tools=[])
    delegate = make_delegate_to_subagent(providers, tool_registry)

    await delegate(subagent_name="recursion-bot", task="do something")

    mock_provider = providers.sub_agent_registry.get("llm")
    context = mock_provider.run.call_args.kwargs["context"]
    tool_names = [t["name"] for t in context.tools]
    assert "delegate_to_subagent" not in tool_names


@pytest.mark.asyncio
async def test_delegate_tool_dispatches_by_agent_type(mock_providers_and_registry):
    """Registry dispatches to the correct provider based on agent_type."""
    providers, tool_registry = mock_providers_and_registry

    # Register a second provider type
    rag_provider = _make_mock_provider("rag")
    from dataclaw.providers.sub_agent.provider import SubAgentResult
    rag_provider.run = AsyncMock(return_value=SubAgentResult(
        status="completed", result="Found 3 papers.", turns_used=1,
    ))
    providers.sub_agent_registry.register(rag_provider)

    create_subagent_definition(name="My Rag Bot", agent_type="rag")
    delegate = make_delegate_to_subagent(providers, tool_registry)

    result = await delegate(subagent_name="my-rag-bot", task="find papers")
    assert result["status"] == "completed"
    assert result["result"] == "Found 3 papers."
    rag_provider.run.assert_called_once()


@pytest.mark.asyncio
async def test_delegate_pre_hook_modifies_task(mock_providers_and_registry):
    """Pre-delegate hook can modify the task."""
    providers, tool_registry = mock_providers_and_registry
    create_subagent_definition(name="Hook Bot")

    async def prepend_context(event):
        event.task = f"[CONTEXT] {event.task}"
        return event

    providers.sub_agent_hooks.on_delegate(prepend_context)

    delegate = make_delegate_to_subagent(providers, tool_registry)
    await delegate(subagent_name="hook-bot", task="do something")

    mock_provider = providers.sub_agent_registry.get("llm")
    call_args = mock_provider.run.call_args
    assert call_args.args[0] == "[CONTEXT] do something"


@pytest.mark.asyncio
async def test_delegate_pre_hook_aborts(mock_providers_and_registry):
    """Pre-delegate hook can abort by raising HookError."""
    from dataclaw.hooks.base import HookError
    providers, tool_registry = mock_providers_and_registry
    create_subagent_definition(name="Blocked Bot")

    async def block_all(event):
        raise HookError("Access denied")

    providers.sub_agent_hooks.on_delegate(block_all)

    delegate = make_delegate_to_subagent(providers, tool_registry)
    result = await delegate(subagent_name="blocked-bot", task="do something")
    assert result["status"] == "error"
    assert "blocked by hook" in result["message"].lower()


@pytest.mark.asyncio
async def test_delegate_context_has_hooks_and_config(mock_providers_and_registry):
    """SubAgentContext should carry hooks and config from definition."""
    providers, tool_registry = mock_providers_and_registry
    create_subagent_definition(
        name="Configured Bot",
        config={"max_turns": 5, "custom_field": "value"},
    )
    delegate = make_delegate_to_subagent(providers, tool_registry)

    await delegate(subagent_name="configured-bot", task="do something")

    mock_provider = providers.sub_agent_registry.get("llm")
    context = mock_provider.run.call_args.kwargs["context"]
    assert context.config["max_turns"] == 5
    assert context.config["custom_field"] == "value"
    assert context.sub_agent_hooks is providers.sub_agent_hooks
