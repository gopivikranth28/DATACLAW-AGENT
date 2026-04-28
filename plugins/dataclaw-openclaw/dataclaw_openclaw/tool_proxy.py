"""Tool proxy router — receives tool calls from OpenClaw, executes them
directly, emits events to the RunTracker, and returns the result.

No bridge needed — tools are executed inline and results returned immediately.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from dataclaw.api.run_tracker import get_run_tracker
from dataclaw.events.emitter import AgentEventEmitter
from dataclaw.storage import sessions

logger = logging.getLogger(__name__)

router = APIRouter()


class ToolCallBody(BaseModel):
    """Request body from OpenClaw's dataclaw-tools plugin."""
    params: dict[str, Any] = Field(default_factory=dict)
    project_id: str | None = None
    workspace_id: str | None = None
    session_id: str | None = None
    titan_session_id: str | None = None  # backward compat
    openclaw_session_key: str | None = None
    openclaw_agent_id: str | None = None


def _extract_from_session_key(key: str) -> str | None:
    """Extract raw session id from an OpenClaw session key like 'agent:main:explicit:{id}'."""
    if ":explicit:" in key:
        return key.split(":explicit:")[-1]
    return None


def _resolve_session_id(body: ToolCallBody) -> str | None:
    """Return the best session_id candidate from the request."""
    for value in [body.openclaw_session_key, body.session_id, body.titan_session_id,
                  body.workspace_id, body.project_id]:
        if not value:
            continue
        extracted = _extract_from_session_key(value)
        if extracted:
            return extracted
        return value
    return None


# Context keys to strip from tool params
_CONTEXT_KEYS = {"titan_session_id", "dataclaw_session_id", "session_id",
                 "openclaw_session_key", "openclaw_agent_id"}


@router.post("/tools/{tool_name}/call")
async def tool_call_proxy(tool_name: str, body: ToolCallBody, request: Request) -> dict[str, Any]:
    """Receive a tool call from OpenClaw. Execute directly and emit events to tracker."""
    session_id = _resolve_session_id(body)
    if not session_id:
        raise HTTPException(400, "Cannot resolve session_id from request")

    providers = request.app.state.providers
    hooks = request.app.state.hooks
    tracker = get_run_tracker()

    # Resolve project_id from session
    project_id: str | None = None
    try:
        session_data = await sessions.get_session(session_id)
        if session_data:
            project_id = session_data.get("projectId")
    except Exception:
        pass

    call_id = f"oc-{uuid.uuid4().hex[:8]}"
    clean_params = {k: v for k, v in body.params.items() if k not in _CONTEXT_KEYS}

    # Build state and run preToolCallHook (injects session/project context into tool params)
    state: dict[str, Any] = {
        "session_id": session_id,
        "project_id": project_id or "",
        "messages": [],
        "tools": [],
        "tool_callables": {},
        "pending_tool_calls": [{
            "tool_name": tool_name,
            "tool_input": clean_params,
            "call_id": call_id,
        }],
    }
    state = await hooks.run("preToolCallHook", state)

    # Read back patched params (hooks may inject session_id, proposal_id, etc.)
    patched_calls = state.get("pending_tool_calls", [])
    if patched_calls:
        clean_params = patched_calls[0].get("tool_input", clean_params)

    # Resolve tool callable
    _, tool_callables = await providers.tool_availability.resolve_tools(state)
    fn = tool_callables.get(tool_name)
    if fn is None:
        raise HTTPException(404, f"Unknown tool: {tool_name}")

    # Emit tool call start events to tracker (if a run is active for this session)
    run = tracker.get_run(session_id)
    emitter: AgentEventEmitter | None = None
    if run and run.status == "running":
        emitter = AgentEventEmitter(session_id, run.run_id)
        tracker.append_event(session_id, emitter.tool_call_start(call_id, tool_name))
        tracker.append_event(session_id, emitter.tool_call_args(
            call_id, json.dumps(clean_params, default=str),
        ))
        tracker.append_event(session_id, emitter.tool_call_end(call_id))

    # Execute tool
    try:
        result = await fn(**clean_params)
        result_json = json.dumps(result, default=str)
        status = "complete"
    except Exception as e:
        logger.exception("Tool %s failed", tool_name)
        result = {"error": str(e)}
        result_json = json.dumps(result)
        status = "error"

    # Emit result event to tracker
    if emitter:
        tracker.append_event(session_id, emitter.tool_call_result(call_id, result_json))

    # Persist to session storage
    await sessions.append_message(session_id, {
        "role": "tool_call", "messageId": f"tc-{call_id}",
        "toolCallId": call_id, "toolName": tool_name,
        "args": json.dumps(clean_params, default=str),
        "result": result_json, "status": status,
    })

    if status == "error":
        raise HTTPException(500, result.get("error", "Tool execution failed"))

    return {"ok": True, "result": result}
