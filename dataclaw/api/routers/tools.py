"""Tools router — list and directly call registered tools."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()


@router.get("")
async def list_tools(request: Request) -> list[dict[str, Any]]:
    """List all registered tool definitions."""
    providers = request.app.state.providers
    tool_availability = providers.tool_availability
    if tool_availability is None:
        return []

    # Resolve tools with empty state to get the full list
    from dataclaw.state import AgentState
    empty_state: AgentState = {
        "session_id": "",
        "messages": [],
        "tools": [],
        "tool_callables": {},
    }
    definitions, _ = await tool_availability.resolve_tools(empty_state)
    return [dict(d) for d in definitions]


class ToolCallRequest(BaseModel):
    params: dict[str, Any] = {}
    session_id: str = ""


@router.post("/{tool_name}/invoke")
async def call_tool(tool_name: str, body: ToolCallRequest, request: Request) -> dict[str, Any]:
    """Call a tool directly by name. Runs preToolCallHook for context injection."""
    providers = request.app.state.providers
    hooks = request.app.state.hooks

    # Resolve project_id from session
    project_id: str | None = None
    if body.session_id:
        try:
            from dataclaw.storage import sessions
            session_data = await sessions.get_session(body.session_id)
            if session_data:
                project_id = session_data.get("projectId")
        except Exception:
            pass

    # Build state and run preToolCallHook (injects project/session context)
    state: dict[str, Any] = {
        "session_id": body.session_id,
        "project_id": project_id or "",
        "messages": [],
        "tools": [],
        "tool_callables": {},
    }
    state = await hooks.run("preToolCallHook", state)

    # Resolve tool callable
    _, tool_callables = await providers.tool_availability.resolve_tools(state)
    fn = tool_callables.get(tool_name)
    if fn is None:
        raise HTTPException(404, f"Unknown tool: {tool_name}")

    try:
        result = await fn(**body.params)
        return {"ok": True, "result": result}
    except Exception as e:
        raise HTTPException(500, str(e))
