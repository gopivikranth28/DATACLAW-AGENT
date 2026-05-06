"""Guardrails router — list and configure guardrail enable/disable settings."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from dataclaw.guardrails.config import (
    GuardrailConfig,
    ProjectGuardrailConfig,
    SessionGuardrailConfig,
    is_guardrail_enabled,
    load_global_guardrail_config,
    load_project_guardrail_config,
    save_global_guardrail_config,
    save_project_guardrail_config,
    session_guardrail_config_from_dict,
    session_guardrail_config_to_dict,
)

router = APIRouter()


def _resolve_project_dir(project_id: str) -> Path | None:
    try:
        from dataclaw_projects.registry import get_project
        project = get_project(project_id)
        directory = project.get("directory")
        if directory:
            return Path(directory)
    except Exception:
        pass
    return None


# ── List guardrails ──────────────────────────────────────────────────────────


@router.get("")
async def list_guardrails(
    request: Request,
    project_id: str | None = Query(None),
    session_id: str | None = Query(None),
) -> dict[str, Any]:
    """List all registered guardrails with enabled status."""
    registry = request.app.state.guardrail_registry
    if registry is None:
        return {"guardrails": []}

    global_config = load_global_guardrail_config()

    project_config: ProjectGuardrailConfig | None = None
    if project_id:
        project_dir = _resolve_project_dir(project_id)
        if project_dir:
            project_config = load_project_guardrail_config(project_dir)

    session_config: SessionGuardrailConfig | None = None
    if session_id:
        from dataclaw.storage import sessions
        session = await sessions.get_session(session_id)
        if session:
            session_config = session_guardrail_config_from_dict(
                session.get("guardrailConfig")
            )

    guardrails = []
    for g in registry.guardrails:
        guardrails.append({
            "id": g.id,
            "phase": g.phase,
            "mode": g.mode,
            "enabled": is_guardrail_enabled(
                g.id, global_config, project_config, session_config,
            ),
        })
    return {"guardrails": guardrails}


# ── Global config ────────────────────────────────────────────────────────────


@router.get("/config")
async def get_guardrail_config() -> dict[str, Any]:
    """Return global guardrail enable/disable config."""
    cfg = load_global_guardrail_config()
    return {"disabled": sorted(cfg.disabled)}


class GuardrailConfigPatch(BaseModel):
    disabled: list[str] | None = None


@router.patch("/config")
async def update_guardrail_config(body: GuardrailConfigPatch) -> dict[str, Any]:
    """Update global guardrail enable/disable config."""
    cfg = load_global_guardrail_config()
    if body.disabled is not None:
        cfg.disabled = set(body.disabled)
        save_global_guardrail_config(cfg)
    return {"disabled": sorted(cfg.disabled)}


# ── Project config ───────────────────────────────────────────────────────────


@router.get("/config/project/{project_id}")
async def get_project_guardrail_config(project_id: str) -> dict[str, Any]:
    """Return project-level guardrail overrides."""
    project_dir = _resolve_project_dir(project_id)
    if project_dir is None:
        raise HTTPException(404, f"Unknown project: {project_id}")

    cfg = load_project_guardrail_config(project_dir)
    if cfg is None:
        return {"disabled": [], "enabled": []}
    return {"disabled": sorted(cfg.disabled), "enabled": sorted(cfg.enabled)}


class ProjectGuardrailConfigPatch(BaseModel):
    disabled: list[str] | None = None
    enabled: list[str] | None = None


@router.patch("/config/project/{project_id}")
async def update_project_guardrail_config(
    project_id: str, body: ProjectGuardrailConfigPatch,
) -> dict[str, Any]:
    """Update project-level guardrail overrides."""
    project_dir = _resolve_project_dir(project_id)
    if project_dir is None:
        raise HTTPException(404, f"Unknown project: {project_id}")

    cfg = load_project_guardrail_config(project_dir) or ProjectGuardrailConfig()
    if body.disabled is not None:
        cfg.disabled = set(body.disabled)
    if body.enabled is not None:
        cfg.enabled = set(body.enabled)
    save_project_guardrail_config(project_dir, cfg)
    return {"disabled": sorted(cfg.disabled), "enabled": sorted(cfg.enabled)}


# ── Session config ───────────────────────────────────────────────────────────


@router.get("/config/session/{session_id}")
async def get_session_guardrail_config(session_id: str) -> dict[str, Any]:
    """Return session-level guardrail overrides."""
    from dataclaw.storage import sessions
    session = await sessions.get_session(session_id)
    if session is None:
        raise HTTPException(404, f"Unknown session: {session_id}")

    cfg = session.get("guardrailConfig") or {}
    return {
        "disabled": cfg.get("disabled", []),
        "enabled": cfg.get("enabled", []),
    }


class SessionGuardrailConfigPatch(BaseModel):
    disabled: list[str] | None = None
    enabled: list[str] | None = None


@router.patch("/config/session/{session_id}")
async def update_session_guardrail_config(
    session_id: str, body: SessionGuardrailConfigPatch,
) -> dict[str, Any]:
    """Update session-level guardrail overrides."""
    from dataclaw.storage import sessions

    session = await sessions.get_session(session_id)
    if session is None:
        raise HTTPException(404, f"Unknown session: {session_id}")

    existing = session_guardrail_config_from_dict(
        session.get("guardrailConfig")
    ) or SessionGuardrailConfig()
    if body.disabled is not None:
        existing.disabled = set(body.disabled)
    if body.enabled is not None:
        existing.enabled = set(body.enabled)

    await sessions.update_session(
        session_id, {"guardrailConfig": session_guardrail_config_to_dict(existing)}
    )
    return {"disabled": sorted(existing.disabled), "enabled": sorted(existing.enabled)}
