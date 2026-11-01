"""FastAPI routes for OKF bundles."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from dataclaw_okf.generator import generate_bundle, is_bundle_stale
from dataclaw_okf.registry import find_bundle, read_bundles
from dataclaw_okf.tools import (
    okf_export_bundle,
    okf_read_bundle,
    okf_search_bundle,
)

router = APIRouter()


class GenerateRequest(BaseModel):
    dataset_id: str
    force: bool = False


@router.get("/bundles")
async def list_bundles() -> list[dict[str, Any]]:
    return [{**bundle, "stale": is_bundle_stale(bundle)} for bundle in read_bundles()]


@router.post("/bundles/generate")
async def generate(req: GenerateRequest) -> dict[str, Any]:
    try:
        return generate_bundle(req.dataset_id, force=req.force)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/bundles/{bundle_id}")
async def get_bundle(bundle_id: str) -> dict[str, Any]:
    try:
        bundle = find_bundle(bundle_id)
        return {**bundle, "stale": is_bundle_stale(bundle)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/bundles/{bundle_id}/files")
async def list_files(bundle_id: str) -> dict[str, Any]:
    try:
        return await okf_read_bundle(bundle_id=bundle_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/bundles/{bundle_id}/file")
async def read_file(bundle_id: str, path: str) -> dict[str, Any]:
    try:
        return await okf_read_bundle(bundle_id=bundle_id, path=path)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/bundles/{bundle_id}/search")
async def search(bundle_id: str, q: str, limit: int = 10) -> dict[str, Any]:
    try:
        return await okf_search_bundle(bundle_id=bundle_id, query=q, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/bundles/{bundle_id}/export")
async def export(bundle_id: str) -> FileResponse:
    try:
        result = await okf_export_bundle(bundle_id=bundle_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    archive = Path(result["archive_path"])
    return FileResponse(
        archive,
        filename=archive.name,
        media_type="application/zip",
    )
