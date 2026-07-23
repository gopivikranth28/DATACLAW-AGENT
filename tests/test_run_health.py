"""Run-health and request-scoped tool-progress regression coverage."""

from __future__ import annotations

import asyncio
from contextlib import suppress

import pytest

from dataclaw.api.routers import chat
from dataclaw.api.run_tracker import get_run_tracker
from dataclaw.tool_progress import emit_tool_progress, tool_progress_context


def test_tool_progress_context_is_scoped_and_best_effort():
    updates: list[dict] = []

    emit_tool_progress("ignored", "No active tool")
    with tool_progress_context(updates.append):
        emit_tool_progress("drafting", "Drafting the report", outputChars=1200)
    emit_tool_progress("ignored", "Context has ended")

    assert updates == [{
        "phase": "drafting",
        "label": "Drafting the report",
        "outputChars": 1200,
    }]


@pytest.mark.asyncio
async def test_agent_status_exposes_task_and_active_tool_health():
    tracker = get_run_tracker()
    session_id = "run-health-session"
    task = asyncio.create_task(asyncio.sleep(60))
    try:
        run = tracker.start_run(session_id, "run-health-run", task)
        tracker.start_tool(session_id, "call-health", "report_design_report")
        tracker.update_tool_progress(session_id, "call-health", {
            "toolCallId": "call-health",
            "toolName": "report_design_report",
            "phase": "drafting",
            "label": "Drafting the report document",
            "activity": "receiving",
            "outputChars": 4200,
        })

        status = await chat.agent_status(session_id)

        assert status["running"] is True
        assert status["healthy"] is True
        assert status["task_status"] == "running"
        assert status["started_at"] == run.started_at
        assert status["last_event_at"]
        assert status["last_progress_at"]
        assert status["server_time"]
        assert status["active_tool"] == {
            "toolCallId": "call-health",
            "toolName": "report_design_report",
            "startedAt": status["active_tool"]["startedAt"],
            "phase": "drafting",
            "label": "Drafting the report document",
            "activity": "receiving",
            "outputChars": 4200,
            "updatedAt": status["active_tool"]["updatedAt"],
        }
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        tracker.finish_run(session_id)
