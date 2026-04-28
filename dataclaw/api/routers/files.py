"""Workspace file serving — serves files from workspace directories."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from dataclaw.config.paths import workspaces_dir

router = APIRouter()


def _allowed_roots() -> list[Path]:
    """Build the list of directories from which files may be served."""
    roots = [
        workspaces_dir().resolve(),
        (Path.home() / "dataclaw-projects").resolve(),
    ]

    # Also allow every registered project directory (projects can live anywhere)
    try:
        from dataclaw_projects.registry import _read_registry
        for entry in _read_registry():
            d = entry.get("directory", "")
            if d:
                roots.append(Path(d).resolve())
    except Exception:
        pass

    return roots


@router.get("/files")
async def serve_file(path: str = Query(..., description="Absolute or workspace-relative file path")) -> FileResponse:
    """Serve a file from the workspace. Validates the path is within workspace bounds."""
    file_path = Path(path).expanduser().resolve()

    if not any(str(file_path).startswith(str(root)) for root in _allowed_roots()):
        raise HTTPException(403, "File path is outside allowed directories")

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(404, f"File not found: {path}")

    return FileResponse(file_path)
