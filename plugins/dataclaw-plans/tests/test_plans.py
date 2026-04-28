"""Tests for plans plugin — plan lifecycle and hooks."""

import pytest

import dataclaw.config.paths as paths
from dataclaw_plans.store import read_proposals, write_proposals, get_active_plan_id
from dataclaw_plans.tools import propose_plan, update_plan, get_plan_decision, list_plans, get_plan
from dataclaw_plans.hooks import active_plan_context_hook


@pytest.fixture(autouse=True)
def tmp_home(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DATACLAW_HOME", tmp_path)
    return tmp_path


# ── Propose ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_propose_plan():
    result = await propose_plan(
        name="Analysis Plan",
        description="Analyze sales data",
        steps=[
            {"name": "Load data", "description": "Load CSV"},
            {"name": "Profile", "description": "Run profiling"},
        ],
        session_id="sess-1",
    )
    assert result["status"] == "pending"
    assert result["proposal_id"].startswith("plan-")
    assert len(result["plan"]["steps"]) == 2


@pytest.mark.asyncio
async def test_propose_plan_validation():
    with pytest.raises(ValueError, match="name is required"):
        await propose_plan(name="", description="x", steps=[{"name": "s", "description": "d"}])

    with pytest.raises(ValueError, match="description is required"):
        await propose_plan(name="x", description="", steps=[{"name": "s", "description": "d"}])

    with pytest.raises(ValueError, match="At least one step"):
        await propose_plan(name="x", description="x", steps=[])


@pytest.mark.asyncio
async def test_propose_plan_auto_resolve():
    """Re-proposing overwrites the existing unapproved plan."""
    r1 = await propose_plan(name="Plan v1", description="d", steps=[{"name": "s1", "description": "d1"}], session_id="sess-1")
    r2 = await propose_plan(name="Plan v2", description="d", steps=[{"name": "s2", "description": "d2"}], session_id="sess-1")

    # Same proposal ID, updated
    assert r2["proposal_id"] == r1["proposal_id"]
    assert r2["plan"]["name"] == "Plan v2"
    assert r2["plan"]["revision"] == 2

    # Only one proposal in store
    assert len(read_proposals()) == 1


# ── Update ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_plan():
    r = await propose_plan(name="Plan", description="d", steps=[{"name": "Step 1", "description": "d"}], session_id="sess-1")
    pid = r["proposal_id"]

    result = await update_plan(
        proposal_id=pid,
        step_patches=[{"name": "Step 1", "status": "completed", "summary": "Done!"}],
        session_id="sess-1",
    )
    assert result["plan"]["steps"][0]["status"] == "completed"
    assert result["plan"]["steps"][0]["summary"] == "Done!"


@pytest.mark.asyncio
async def test_update_plan_new_step():
    r = await propose_plan(name="Plan", description="d", steps=[{"name": "Step 1", "description": "d"}], session_id="sess-1")
    pid = r["proposal_id"]

    result = await update_plan(
        proposal_id=pid,
        step_patches=[{"name": "Step 2", "status": "in_progress", "description": "New step"}],
        session_id="sess-1",
    )
    assert len(result["plan"]["steps"]) == 2


@pytest.mark.asyncio
async def test_update_plan_not_found():
    with pytest.raises(KeyError, match="not found"):
        await update_plan(proposal_id="nonexistent", session_id="sess-1")


# ── Query ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_plan_decision():
    r = await propose_plan(name="Plan", description="d", steps=[{"name": "s", "description": "d"}], session_id="sess-1")
    result = await get_plan_decision(proposal_id=r["proposal_id"])
    assert result["status"] == "pending"
    assert result["decision"] is None


@pytest.mark.asyncio
async def test_list_plans():
    await propose_plan(name="Plan A", description="d", steps=[{"name": "s", "description": "d"}], session_id="sess-1")
    await propose_plan(name="Plan B", description="d", steps=[{"name": "s", "description": "d"}], session_id="sess-2")

    result = await list_plans(session_id="sess-1")
    assert result["total"] == 1
    assert result["plans"][0]["name"] == "Plan A"

    result = await list_plans()
    assert result["total"] == 2


@pytest.mark.asyncio
async def test_get_plan():
    r = await propose_plan(name="Plan", description="d", steps=[{"name": "s", "description": "d"}], session_id="sess-1")
    plan = await get_plan(proposal_id=r["proposal_id"])
    assert plan["name"] == "Plan"


# ── Active plan ID ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_active_plan_id():
    r = await propose_plan(name="Plan", description="d", steps=[{"name": "s", "description": "d"}], session_id="sess-1")
    assert get_active_plan_id("sess-1") == r["proposal_id"]
    assert get_active_plan_id("sess-other") is None


# ── Hook ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_active_plan_context_hook():
    r = await propose_plan(name="Plan", description="d", steps=[{"name": "s", "description": "d"}], session_id="sess-1")
    pid = r["proposal_id"]

    state = {
        "session_id": "sess-1",
        "messages": [],
        "pending_tool_calls": [
            {"tool_name": "update_plan", "tool_input": {"step_patches": []}},
        ],
    }
    updated = await active_plan_context_hook(state)
    # Should have injected proposal_id
    assert updated["pending_tool_calls"][0]["tool_input"]["proposal_id"] == pid


@pytest.mark.asyncio
async def test_hook_injects_session_id():
    """Hook injects session_id into propose_plan calls."""
    state = {
        "session_id": "real-sess",
        "messages": [],
        "pending_tool_calls": [
            {"tool_name": "propose_plan", "tool_input": {"name": "P", "description": "d", "steps": []}},
        ],
    }
    updated = await active_plan_context_hook(state)
    assert updated["pending_tool_calls"][0]["tool_input"]["session_id"] == "real-sess"


@pytest.mark.asyncio
async def test_active_plan_context_hook_noop():
    """Hook doesn't touch non-update_plan calls."""
    state = {
        "session_id": "sess-1",
        "messages": [],
        "pending_tool_calls": [
            {"tool_name": "ws_exec", "tool_input": {"command": "ls"}},
        ],
    }
    updated = await active_plan_context_hook(state)
    assert updated["pending_tool_calls"][0]["tool_input"] == {"command": "ls"}
