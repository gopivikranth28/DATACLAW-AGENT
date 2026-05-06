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
    """Request body from OpenClaw's dataclaw plugin (tools surface)."""
    params: dict[str, Any] = Field(default_factory=dict)
    project_id: str | None = None
    workspace_id: str | None = None
    session_id: str | None = None
    titan_session_id: str | None = None  # backward compat
    openclaw_session_key: str | None = None
    openclaw_agent_id: str | None = None


def _extract_from_session_key(key: str) -> str | None:
    """Extract the dataclaw chat id from an OpenClaw session key.

    Recognizes both the new shape ``agent:<agentId>:dataclaw:channel:<chat_id>``
    (used since OpenClaw 2026.5 routing through ``peer.kind: "channel"``) and
    the legacy ``agent:<agentId>:explicit:<chat_id>``. Strips an optional
    ``:thread:<id>`` suffix that may be appended for forked subsessions.
    """
    for marker in (":dataclaw:channel:", ":explicit:"):
        if marker in key:
            tail = key.split(marker, 1)[1]
            return tail.split(":thread:", 1)[0]
    return None


def _looks_like_chat_id(value: str) -> bool:
    """Heuristic: a bare chat id has no OpenClaw session-key separators."""
    return ":" not in value


def _resolve_session_id(body: ToolCallBody) -> str | None:
    """Return the best dataclaw chat id candidate from the request.

    Preference order:
      1. ``session_id`` / ``titan_session_id`` if they look like a bare chat
         id — the openclaw plugin client already extracts the chat id and
         sends it under those keys.
      2. ``openclaw_session_key`` parsed via ``_extract_from_session_key``,
         which now recognizes both ``:dataclaw:channel:`` and the legacy
         ``:explicit:`` markers.
      3. Anything left, taken verbatim (workspace/project ids fall back here).
    """
    for value in (body.session_id, body.titan_session_id):
        if value and _looks_like_chat_id(value):
            return value
    if body.openclaw_session_key:
        extracted = _extract_from_session_key(body.openclaw_session_key)
        if extracted:
            return extracted
    for value in (body.session_id, body.titan_session_id, body.workspace_id, body.project_id):
        if not value:
            continue
        extracted = _extract_from_session_key(value)
        return extracted or value
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

    # Honor guardrail decisions: the guardrail pre-hook removes blocked calls
    # from `pending_tool_calls` and appends to `guardrail_verdicts`. If our
    # call disappeared from `pending_tool_calls`, the guardrail blocked it.
    # Without this check the proxy would happily run the tool anyway —
    # bypassing every pre-phase guardrail (file delete, outside project,
    # etc.) for calls that come through the openclaw bridge.
    patched_calls = state.get("pending_tool_calls", [])
    matched = next(
        (c for c in patched_calls if c.get("call_id") == call_id),
        None,
    )
    if matched is None:
        verdict = next(
            (
                v for v in state.get("guardrail_verdicts", [])
                if v.get("tool_call_id") == call_id
            ),
            None,
        )
        message = (
            verdict.get("message")
            if isinstance(verdict, dict) and verdict.get("message")
            else "Tool call blocked by guardrail"
        )
        raise HTTPException(403, message)

    # Read back patched params (hooks may inject session_id, proposal_id, etc.)
    clean_params = matched.get("tool_input", clean_params)

    # Resolve tool callable. resolve_tools(state) returns the *enabled* set
    # (filtered by session.toolIds, project.tool_ids, and the global disabled
    # list), so a missing entry can mean either "tool was never registered"
    # or "tool is registered but disabled for this session". The openclaw
    # agent surfaces our error message verbatim — distinguish them so the
    # agent can react accordingly instead of telling the user the tool
    # doesn't exist.
    _, tool_callables = await providers.tool_availability.resolve_tools(state)
    fn = tool_callables.get(tool_name)
    if fn is None:
        if providers.tool_availability.has_tool(tool_name):
            raise HTTPException(
                403,
                f"Tool '{tool_name}' is registered but disabled for this session",
            )
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
