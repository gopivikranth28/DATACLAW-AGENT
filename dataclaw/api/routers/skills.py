"""Skills router — CRUD for skill files."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from dataclaw.storage.skills import delete_skill, list_skill_files, read_skill, write_skill

router = APIRouter()


class SkillRequest(BaseModel):
    name: str = ""
    description: str = ""
    tags: list[str] = []
    body: str = ""


@router.get("")
async def list_skills() -> list[dict[str, Any]]:
    return list_skill_files()


@router.get("/{skill_id}")
async def get_skill(skill_id: str) -> dict[str, Any]:
    skill = read_skill(skill_id)
    if skill is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    return skill


@router.post("/{skill_id}")
async def create_skill(skill_id: str, req: SkillRequest) -> dict[str, Any]:
    meta = {"name": req.name or skill_id, "description": req.description, "tags": req.tags}
    path = write_skill(skill_id, meta, req.body)
    return {"id": skill_id, "path": str(path), "status": "created"}


@router.put("/{skill_id}")
async def update_skill(skill_id: str, req: SkillRequest) -> dict[str, Any]:
    meta = {"name": req.name or skill_id, "description": req.description, "tags": req.tags}
    path = write_skill(skill_id, meta, req.body)
    return {"id": skill_id, "path": str(path), "status": "updated"}


@router.delete("/{skill_id}")
async def remove_skill(skill_id: str) -> dict[str, str]:
    if not delete_skill(skill_id):
        raise HTTPException(status_code=404, detail="Skill not found")
    return {"status": "deleted"}
