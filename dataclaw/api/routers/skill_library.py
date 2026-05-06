"""Skill library router — browse and install community skills."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from dataclaw.storage.skill_library import (
    install_library_skill,
    list_library_skills,
    read_library_skill,
)

router = APIRouter()


@router.get("")
async def list_library() -> list[dict[str, Any]]:
    return list_library_skills()


@router.get("/{skill_id}")
async def get_library_skill(skill_id: str) -> dict[str, Any]:
    skill = read_library_skill(skill_id)
    if skill is None:
        raise HTTPException(status_code=404, detail="Library skill not found")
    return skill


@router.post("/{skill_id}/install")
async def install_skill(skill_id: str, force: bool = Query(False)) -> dict[str, Any]:
    try:
        path = install_library_skill(skill_id, force=force)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Library skill not found")
    except FileExistsError:
        raise HTTPException(status_code=409, detail="Skill already installed. Use ?force=true to overwrite.")
    return {"id": skill_id, "path": str(path), "status": "installed"}
