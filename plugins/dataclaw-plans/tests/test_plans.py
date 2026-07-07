"""Tests for plans plugin — plan lifecycle and hooks."""

import pytest

import dataclaw.config.paths as paths
from dataclaw_plans.store import (
    read_proposals,
    write_proposals,
    get_active_plan_id,
    read_snapshots,
    find_snapshot,
    SNAPSHOTS_PER_PROPOSAL,
)
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
    assert result["snapshot_id"].startswith("snap-")
    assert result["revision"] == 1
    assert "plan" not in result  # full plan must not be echoed
    # Live plan still has the steps.
    plan = await get_plan(proposal_id=result["proposal_id"])
    assert len(plan["steps"]) == 2


@pytest.mark.asyncio
async def test_propose_plan_return_shape_slim():
    result = await propose_plan(
        name="Plan", description="d",
        steps=[{"name": "s", "description": "d"}], session_id="sess-1",
    )
    assert set(result.keys()) == {"proposal_id", "snapshot_id", "status", "revision", "message"}
    assert "awaiting" in result["message"].lower()


@pytest.mark.asyncio
async def test_propose_plan_persists_snapshot():
    result = await propose_plan(
        name="Plan", description="d",
        steps=[{"name": "s1", "description": "d1"}],
        plan_markdown="# Plan\n\n## QA\n\nCheck row counts before ranking.",
        session_id="sess-1",
    )
    snap = find_snapshot(result["snapshot_id"])
    assert snap["proposal_id"] == result["proposal_id"]
    assert snap["trigger"] == "propose"
    assert snap["plan"]["steps"][0]["name"] == "s1"
    assert "Check row counts" in snap["plan"]["plan_markdown"]


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

    # Same proposal ID, updated revision
    assert r2["proposal_id"] == r1["proposal_id"]
    assert r2["revision"] == 2
    plan = await get_plan(proposal_id=r2["proposal_id"])
    assert plan["name"] == "Plan v2"

    # Only one proposal in store
    assert len(read_proposals()) == 1


@pytest.mark.asyncio
async def test_reproposal_returns_prior_snapshot_and_stable_step_ids():
    """Revision cards can diff against the previous proposal snapshot."""
    r1 = await propose_plan(
        name="Plan v1", description="d",
        steps=[
            {"name": "Keep me", "description": "d1"},
            {"name": "Drop me", "description": "d2"},
        ],
        session_id="sess-1",
    )
    first = await get_plan(proposal_id=r1["proposal_id"])
    kept_id = first["steps"][0]["id"]

    r2 = await propose_plan(
        name="Plan v2", description="d",
        steps=[
            {"name": "Keep me", "description": "d1 updated"},
            {"name": "Add me", "description": "d3"},
        ],
        session_id="sess-1",
    )

    assert r2["previous_snapshot_id"].startswith("snap-")
    prior = find_snapshot(r2["previous_snapshot_id"])
    assert prior["plan"]["name"] == "Plan v1"
    revised = await get_plan(proposal_id=r2["proposal_id"])
    assert revised["steps"][0]["id"] == kept_id
    assert revised["steps"][1]["id"].startswith("step-")


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
    assert result["success"] is True
    assert result["steps_updated"] == 1
    assert result["snapshot_id"].startswith("snap-")
    assert "plan" not in result  # no full echo

    # Snapshot is the temporally-correct view: step 1 completed.
    snap = find_snapshot(result["snapshot_id"])
    assert snap["trigger"] == "update"
    assert snap["plan"]["steps"][0]["status"] == "completed"
    assert snap["plan"]["steps"][0]["summary"] == "Done!"


@pytest.mark.asyncio
async def test_update_plan_new_step():
    r = await propose_plan(name="Plan", description="d", steps=[{"name": "Step 1", "description": "d"}], session_id="sess-1")
    pid = r["proposal_id"]

    result = await update_plan(
        proposal_id=pid,
        step_patches=[{"name": "Step 2", "status": "in_progress", "description": "New step"}],
        session_id="sess-1",
    )
    assert result["success"] is True
    snap = find_snapshot(result["snapshot_id"])
    assert len(snap["plan"]["steps"]) == 2


@pytest.mark.asyncio
async def test_update_plan_not_found_returns_soft_failure():
    """Missing proposal returns success:false, doesn't raise."""
    result = await update_plan(proposal_id="nonexistent", session_id="sess-1")
    assert result == {
        "success": False,
        "proposal_id": "nonexistent",
        "error": "Plan proposal not found",
    }


@pytest.mark.asyncio
async def test_update_plan_snapshots_preserve_history():
    """Each update_plan persists a frozen snapshot — older ones don't mutate."""
    r = await propose_plan(
        name="Plan", description="d",
        steps=[
            {"name": "Step 1", "description": "d1"},
            {"name": "Step 2", "description": "d2"},
        ],
        session_id="sess-1",
    )
    pid = r["proposal_id"]
    propose_snap_id = r["snapshot_id"]

    r1 = await update_plan(
        proposal_id=pid,
        step_patches=[{"name": "Step 1", "status": "completed"}],
        session_id="sess-1",
    )
    r2 = await update_plan(
        proposal_id=pid,
        step_patches=[{"name": "Step 2", "status": "completed"}],
        session_id="sess-1",
    )

    # The second update's snapshot has both steps completed.
    snap2 = find_snapshot(r2["snapshot_id"])
    assert all(s["status"] == "completed" for s in snap2["plan"]["steps"])

    # The first update's snapshot still shows step 2 NOT completed —
    # this is the timeline-preservation property.
    snap1 = find_snapshot(r1["snapshot_id"])
    statuses = {s["name"]: s["status"] for s in snap1["plan"]["steps"]}
    assert statuses["Step 1"] == "completed"
    assert statuses["Step 2"] != "completed"

    # The original propose snapshot is untouched.
    propose_snap = find_snapshot(propose_snap_id)
    assert all(s["status"] == "not_started" for s in propose_snap["plan"]["steps"])


@pytest.mark.asyncio
async def test_snapshot_pruning_caps_at_limit():
    """Snapshots beyond SNAPSHOTS_PER_PROPOSAL for one proposal are dropped (oldest first)."""
    r = await propose_plan(
        name="Plan", description="d",
        steps=[{"name": "Step", "description": "d"}],
        session_id="sess-1",
    )
    pid = r["proposal_id"]
    # The propose call already added 1 snapshot. Push past the cap.
    extra = SNAPSHOTS_PER_PROPOSAL  # → total = SNAPSHOTS_PER_PROPOSAL + 1, then prune to cap
    for _ in range(extra):
        await update_plan(
            proposal_id=pid,
            step_patches=[{"name": "Step", "status": "in_progress"}],
            session_id="sess-1",
        )

    proposal_snaps = [s for s in read_snapshots() if s["proposal_id"] == pid]
    assert len(proposal_snaps) == SNAPSHOTS_PER_PROPOSAL
    # Oldest dropped: the original propose snapshot is gone.
    assert all(s["id"] != r["snapshot_id"] for s in proposal_snaps)


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
