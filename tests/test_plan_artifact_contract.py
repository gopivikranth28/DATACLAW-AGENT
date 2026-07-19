from __future__ import annotations

import pytest

import dataclaw.config.paths as paths
from dataclaw_artifacts.hooks import artifact_context_hook
from dataclaw_artifacts.store import read_manifest_events
from dataclaw_artifacts.tools import report_note
from dataclaw_plans.hooks import active_plan_context_hook
from dataclaw_plans.tools import get_plan, propose_plan, update_plan


@pytest.mark.asyncio
async def test_renamed_plan_step_context_attaches_report_note_to_stable_id(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DATACLAW_HOME", tmp_path)
    (tmp_path / "workspaces").mkdir()

    proposed = await propose_plan(
        name="Plan",
        description="d",
        steps=[{"name": "Original step", "description": "d"}],
        session_id="sess-contract",
    )
    plan = await get_plan(proposal_id=proposed["proposal_id"])
    step_id = plan["steps"][0]["plan_step_id"]

    await update_plan(
        proposal_id=proposed["proposal_id"],
        step_patches=[{"plan_step_id": step_id, "name": "Renamed evidence step", "status": "in_progress"}],
        session_id="sess-contract",
    )

    state = {
        "session_id": "sess-contract",
        "pending_tool_calls": [{
            "tool_name": "report_note",
            "tool_input": {"page": "analyses", "markdown": "Evidence after rename."},
        }],
    }
    state = await active_plan_context_hook(state)
    state = await artifact_context_hook(state)
    note_input = state["pending_tool_calls"][0]["tool_input"]

    assert state["active_plan_step_id"] == step_id
    assert note_input["plan_step_id"] == step_id

    note = await report_note(**note_input)
    events = read_manifest_events(note["artifact_id"])

    assert events[0]["plan_step_id"] == step_id
    assert events[0]["plan_step_id"] != "Renamed evidence step"
