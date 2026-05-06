"""Kaggle plugin — FastAPI router for UI endpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from dataclaw_kaggle import registry
from dataclaw_kaggle.client import run_kaggle, get_config, reset_api

router = APIRouter()

# Module-level config ref, set by plugin register().
_plugin_cfg: dict[str, Any] = {}


def set_plugin_cfg(cfg: dict[str, Any]) -> None:
    global _plugin_cfg
    _plugin_cfg = cfg


def _creds() -> dict[str, str]:
    u, k = get_config(_plugin_cfg)
    return {"username": u, "key": k}


# ── Request models ──────────────────────────────────────────────────────────


class CompetitionDownloadRequest(BaseModel):
    file_name: str | None = None
    force: bool = False
    register_dataset: bool = True


class DatasetDownloadRequest(BaseModel):
    force: bool = False
    register_dataset: bool = True


class SubmissionRequest(BaseModel):
    competition: str
    file_path: str
    message: str


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.get("/status")
async def auth_status() -> dict[str, Any]:
    """Check if Kaggle credentials are configured and valid."""
    try:
        results = await run_kaggle("competitions_list", page=1, **_creds())
        return {"authenticated": True, "status": "ok"}
    except Exception as exc:
        return {"authenticated": False, "error": str(exc)}


@router.get("/competitions")
async def list_competitions() -> dict[str, Any]:
    """List tracked competitions from the local registry."""
    return {"competitions": registry.list_competitions()}


@router.get("/competitions/{slug}")
async def get_competition(slug: str) -> dict[str, Any]:
    """Get competition details, fetching from Kaggle API and caching in registry."""
    try:
        response = await run_kaggle("competition_list_files", slug, **_creds())
        raw_files = getattr(response, "files", None) or response or []
        file_list = [
            {"name": getattr(f, "name", str(f)), "size": getattr(f, "total_bytes", 0)}
            for f in raw_files
        ]
        entry = registry.track_competition(slug, {
            "url": f"https://www.kaggle.com/c/{slug}",
            "files_info": file_list,
        })
        return {"competition": entry, "files": file_list}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/competitions/{slug}/download")
async def download_competition(slug: str, body: CompetitionDownloadRequest) -> dict[str, Any]:
    """Trigger download of competition data files."""
    from dataclaw_kaggle.tools import kaggle_download_competition
    return await kaggle_download_competition(
        competition=slug,
        file_name=body.file_name or "",
        force=body.force,
    )


@router.get("/datasets")
async def list_datasets() -> dict[str, Any]:
    """List tracked Kaggle dataset downloads from the local registry."""
    return {"datasets": registry.list_datasets()}


@router.post("/datasets/{ref:path}/download")
async def download_dataset(ref: str, body: DatasetDownloadRequest) -> dict[str, Any]:
    """Trigger download of a Kaggle dataset."""
    from dataclaw_kaggle.tools import kaggle_download_dataset
    return await kaggle_download_dataset(
        dataset=ref,
        force=body.force,
    )


@router.get("/submissions")
async def list_submissions(competition: str | None = None) -> dict[str, Any]:
    """List submissions, optionally filtered by competition."""
    return {"submissions": registry.list_submissions(competition)}


@router.post("/submissions")
async def submit(body: SubmissionRequest) -> dict[str, Any]:
    """Submit a prediction file to a competition."""
    from dataclaw_kaggle.tools import kaggle_submit
    return await kaggle_submit(
        competition=body.competition,
        file_path=body.file_path,
        message=body.message,
    )


@router.delete("/downloads/{kind}/{key:path}")
async def delete_download(kind: str, key: str, remove_files: bool = False) -> dict[str, Any]:
    """Remove a download record from the registry."""
    if kind not in ("competitions", "datasets"):
        raise HTTPException(status_code=400, detail="kind must be 'competitions' or 'datasets'")
    deleted = registry.delete_download(kind, key, remove_files=remove_files)
    if not deleted:
        raise HTTPException(status_code=404, detail="Download not found")
    return {"deleted": True, "kind": kind, "key": key}
