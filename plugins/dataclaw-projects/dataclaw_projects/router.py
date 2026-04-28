"""Projects and subagents routers."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from dataclaw_projects.registry import (
    list_projects, get_project, create_project, update_project, delete_project, list_project_files,
)
from dataclaw_projects.subagents import (
    list_subagent_definitions, get_subagent_definition,
    create_subagent_definition, update_subagent_definition, delete_subagent_definition,
)

projects_router = APIRouter()
subagents_router = APIRouter()


# ── Projects ────────────────────────────────────────────────────────────────


class ProjectCreateRequest(BaseModel):
    name: str
    description: str = ""
    directory: str = ""
    python_version: str = ""
    kernel_mode: str = "new_env"  # "new_env" | "system" | "custom"
    kernel_python: str = ""       # path to python binary (only for "custom")
    packages: list[str] | None = None  # None = default DS libraries


@projects_router.get("/")
async def list_all_projects() -> list[dict[str, Any]]:
    return list_projects()


@projects_router.post("/")
async def create_new_project(req: ProjectCreateRequest) -> dict[str, Any]:
    return create_project(
        name=req.name, description=req.description, directory=req.directory,
        python_version=req.python_version, kernel_mode=req.kernel_mode,
        kernel_python=req.kernel_python, packages=req.packages,
    )


@projects_router.get("/{project_id}")
async def get_one_project(project_id: str) -> dict[str, Any]:
    try:
        return get_project(project_id)
    except KeyError:
        raise HTTPException(404, "Project not found")


class ProjectUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    dataset_ids: list[str] | None = None


@projects_router.patch("/{project_id}")
async def update_one_project(project_id: str, req: ProjectUpdateRequest) -> dict[str, Any]:
    try:
        return update_project(project_id, req.model_dump(exclude_unset=True))
    except KeyError:
        raise HTTPException(404, "Project not found")


@projects_router.delete("/{project_id}")
async def delete_one_project(project_id: str) -> dict[str, str]:
    try:
        delete_project(project_id)
        return {"deleted": project_id}
    except KeyError:
        raise HTTPException(404, "Project not found")


@projects_router.get("/{project_id}/files")
async def get_project_files(project_id: str) -> dict[str, Any]:
    try:
        return list_project_files(project_id)
    except KeyError:
        raise HTTPException(404, "Project not found")


# ── Subagents ───────────────────────────────────────────────────────────────


class SubagentCreateRequest(BaseModel):
    name: str
    description: str = ""
    agent_type: str = "llm"
    allowed_tools: list[str] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)


class SubagentUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    agent_type: str | None = None
    allowed_tools: list[str] | None = None
    config: dict[str, Any] | None = None


@subagents_router.get("/")
async def list_all_subagents() -> list[dict[str, Any]]:
    return list_subagent_definitions()


@subagents_router.get("/{subagent_id}")
async def get_one_subagent(subagent_id: str) -> dict[str, Any]:
    try:
        return get_subagent_definition(subagent_id)
    except KeyError:
        raise HTTPException(404, "Subagent not found")


@subagents_router.post("/")
async def create_new_subagent(req: SubagentCreateRequest) -> dict[str, Any]:
    try:
        return create_subagent_definition(
            name=req.name, description=req.description,
            agent_type=req.agent_type, allowed_tools=req.allowed_tools, config=req.config,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@subagents_router.put("/{subagent_id}")
async def update_one_subagent(subagent_id: str, req: SubagentUpdateRequest) -> dict[str, Any]:
    try:
        return update_subagent_definition(subagent_id, req.model_dump(exclude_unset=True))
    except KeyError:
        raise HTTPException(404, "Subagent not found")


@subagents_router.delete("/{subagent_id}")
async def delete_one_subagent(subagent_id: str) -> dict[str, str]:
    if not delete_subagent_definition(subagent_id):
        raise HTTPException(404, "Subagent not found")
    return {"deleted": subagent_id}
