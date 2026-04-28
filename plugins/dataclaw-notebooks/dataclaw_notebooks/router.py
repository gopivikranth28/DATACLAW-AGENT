"""Notebooks router — list open notebooks."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from dataclaw_notebooks import tools

router = APIRouter()


@router.get("")
async def list_open_notebooks() -> dict[str, Any]:
    return {"notebooks": tools._mgr().list_notebooks()}
