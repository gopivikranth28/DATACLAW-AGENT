"""Tools router — list, call, and configure registered tools."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

router = APIRouter()


# ── List tools ────────────────────────────────────────────────────────────────

@router.get("")
async def list_tools(
    request: Request,
    project_id: str | None = Query(None),
    session_id: str | None = Query(None),
) -> dict[str, Any]:
    """List all registered tools with enabled status and version counter."""
    registry = request.app.state.providers.tool_availability
    if registry is None:
        return {"version": 0, "tools": []}

    tools = registry.get_all_tools_with_status(
        project_id=project_id, session_id=session_id,
    )
    return {"version": registry.version, "tools": tools}


# ── Invoke tool ───────────────────────────────────────────────────────────────

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


# ── Tool config (enable / disable) ───────────────────────────────────────────

@router.get("/config")
async def get_tool_config(request: Request) -> dict[str, Any]:
    """Return global tool enable/disable config."""
    registry = request.app.state.providers.tool_availability
    cfg = registry._tool_config
    return {"disabled": sorted(cfg.disabled), "version": cfg.version}


class ToolConfigPatch(BaseModel):
    disabled: list[str] | None = None


@router.patch("/config")
async def update_tool_config(body: ToolConfigPatch, request: Request) -> dict[str, Any]:
    """Update global tool enable/disable config."""
    registry = request.app.state.providers.tool_availability
    if body.disabled is not None:
        registry._tool_config.disabled = set(body.disabled)
        from dataclaw.providers.tool.tool_config import save_global_tool_config
        save_global_tool_config(registry._tool_config)
        registry._bump()
    cfg = registry._tool_config
    return {"disabled": sorted(cfg.disabled), "version": cfg.version}


@router.get("/config/project/{project_id}")
async def get_project_tool_config(project_id: str, request: Request) -> dict[str, Any]:
    """Return project-level tool overrides."""
    from dataclaw.providers.tool.tool_config import load_project_tool_config
    from dataclaw.providers.tool.implementations.registry import _resolve_project_dir

    project_dir = _resolve_project_dir(project_id)
    if project_dir is None:
        raise HTTPException(404, f"Unknown project: {project_id}")

    cfg = load_project_tool_config(project_dir)
    if cfg is None:
        return {"disabled": [], "enabled": []}
    return {"disabled": sorted(cfg.disabled), "enabled": sorted(cfg.enabled)}


class ProjectToolConfigPatch(BaseModel):
    disabled: list[str] | None = None
    enabled: list[str] | None = None


@router.patch("/config/project/{project_id}")
async def update_project_tool_config(
    project_id: str,
    body: ProjectToolConfigPatch,
    request: Request,
) -> dict[str, Any]:
    """Update project-level tool overrides."""
    from dataclaw.providers.tool.tool_config import (
        ProjectToolConfig,
        load_project_tool_config,
        save_project_tool_config,
    )
    from dataclaw.providers.tool.implementations.registry import _resolve_project_dir

    project_dir = _resolve_project_dir(project_id)
    if project_dir is None:
        raise HTTPException(404, f"Unknown project: {project_id}")

    cfg = load_project_tool_config(project_dir) or ProjectToolConfig()
    if body.disabled is not None:
        cfg.disabled = set(body.disabled)
    if body.enabled is not None:
        cfg.enabled = set(body.enabled)
    save_project_tool_config(project_dir, cfg)

    registry = request.app.state.providers.tool_availability
    registry._bump()

    return {"disabled": sorted(cfg.disabled), "enabled": sorted(cfg.enabled)}


# ── Session-level tool config ────────────────────────────────────────────────

@router.get("/config/session/{session_id}")
async def get_session_tool_config(session_id: str, request: Request) -> dict[str, Any]:
    """Return session-level tool overrides."""
    from dataclaw.storage import sessions
    session = await sessions.get_session(session_id)
    if session is None:
        raise HTTPException(404, f"Unknown session: {session_id}")

    tool_cfg = session.get("toolConfig") or {}
    return {
        "disabled": tool_cfg.get("disabled", []),
        "enabled": tool_cfg.get("enabled", []),
    }


class SessionToolConfigPatch(BaseModel):
    disabled: list[str] | None = None
    enabled: list[str] | None = None


@router.patch("/config/session/{session_id}")
async def update_session_tool_config(
    session_id: str,
    body: SessionToolConfigPatch,
    request: Request,
) -> dict[str, Any]:
    """Update session-level tool overrides."""
    from dataclaw.storage import sessions
    from dataclaw.providers.tool.tool_config import (
        SessionToolConfig,
        session_tool_config_from_dict,
        session_tool_config_to_dict,
    )

    session = await sessions.get_session(session_id)
    if session is None:
        raise HTTPException(404, f"Unknown session: {session_id}")

    existing = session_tool_config_from_dict(session.get("toolConfig")) or SessionToolConfig()
    if body.disabled is not None:
        existing.disabled = set(body.disabled)
    if body.enabled is not None:
        existing.enabled = set(body.enabled)

    await sessions.update_session(session_id, {"toolConfig": session_tool_config_to_dict(existing)})

    return {"disabled": sorted(existing.disabled), "enabled": sorted(existing.enabled)}
