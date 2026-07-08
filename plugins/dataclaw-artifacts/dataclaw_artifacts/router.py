"""Artifact API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, Response

from dataclaw_artifacts.compiler import compile_living_report
from dataclaw_artifacts.store import (
    MAX_EXPORTED_ARTIFACT_BYTES,
    delete_artifact_record,
    latest_version,
    list_artifact_records,
    read_meta,
    read_source,
)
from dataclaw_artifacts.wrapper import artifact_csp, artifact_host_shell, export_shell, new_nonce, plotly_runtime_js

router = APIRouter()


def _headers(disposition: str | None = None, *, nonce: str | None = None) -> dict[str, str]:
    headers = {
        "Content-Security-Policy": artifact_csp(nonce),
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "no-store",
    }
    if disposition:
        headers["Content-Disposition"] = disposition
    return headers


@router.get("")
async def list_artifacts(session_id: str = "", limit: int = 100) -> dict[str, Any]:
    artifacts = []
    for meta in list_artifact_records(session_id=session_id, limit=limit):
        latest = int(meta.get("latest_version") or 0)
        artifact_id = meta.get("id")
        is_living = meta.get("kind") == "living_report"
        artifacts.append({
            "artifact_id": artifact_id,
            "kind": meta.get("kind", "artifact"),
            "title": meta.get("title", ""),
            "description": meta.get("description", ""),
            "session_id": meta.get("session_id", ""),
            "project_id": meta.get("project_id", ""),
            "latest_version": latest,
            "versions": meta.get("versions", []),
            "source_path": meta.get("source_path", ""),
            "updated_at": meta.get("updated_at", ""),
            "url": f"/api/artifacts/{artifact_id}/living" if is_living and artifact_id else f"/api/artifacts/{artifact_id}?version={latest}" if artifact_id and latest else "",
        })
    return {"artifacts": artifacts, "total": len(artifacts)}


@router.get("/artifact-runtime/plotly.min.js")
async def plotly_runtime() -> Response:
    return Response(
        plotly_runtime_js(),
        media_type="application/javascript; charset=utf-8",
        headers={
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )


@router.get("/{artifact_id}/living")
async def serve_living_report(artifact_id: str) -> HTMLResponse:
    try:
        meta = read_meta(artifact_id)
        if meta.get("kind") != "living_report":
            raise KeyError(artifact_id)
        source = compile_living_report(artifact_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Living report not found")
    nonce = new_nonce()
    html = artifact_host_shell(
        artifact_id=artifact_id,
        version=0,
        title=str(meta.get("title") or "Living Report"),
        source=source,
        nonce=nonce,
    )
    return HTMLResponse(html, headers=_headers(nonce=nonce))


@router.get("/{artifact_id}")
async def serve_artifact(
    artifact_id: str,
    version: int | None = Query(default=None),
) -> HTMLResponse:
    try:
        meta = read_meta(artifact_id)
        resolved_version = version or latest_version(artifact_id)
        source = read_source(artifact_id, resolved_version)
    except KeyError:
        raise HTTPException(status_code=404, detail="Artifact not found")
    nonce = new_nonce()
    html = artifact_host_shell(
        artifact_id=artifact_id,
        version=resolved_version,
        title=str(meta.get("title") or artifact_id),
        source=source,
        nonce=nonce,
    )
    return HTMLResponse(html, headers=_headers(nonce=nonce))


@router.get("/{artifact_id}/source")
async def get_artifact_source(
    artifact_id: str,
    version: int | None = Query(default=None),
) -> dict[str, Any]:
    try:
        meta = read_meta(artifact_id)
        resolved_version = version or latest_version(artifact_id)
        source = read_source(artifact_id, resolved_version)
    except KeyError:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return {
        "artifact_id": artifact_id,
        "version": resolved_version,
        "title": meta.get("title", ""),
        "description": meta.get("description", ""),
        "source_path": meta.get("source_path", ""),
        "html": source,
    }


@router.get("/{artifact_id}/export")
async def export_artifact(
    artifact_id: str,
    version: int | None = Query(default=None),
) -> Response:
    try:
        meta = read_meta(artifact_id)
        resolved_version = version or latest_version(artifact_id)
        source = read_source(artifact_id, resolved_version)
    except KeyError:
        raise HTTPException(status_code=404, detail="Artifact not found")
    title = str(meta.get("title") or artifact_id)
    nonce = new_nonce()
    html = export_shell(
        artifact_id=artifact_id,
        version=resolved_version,
        title=title,
        source=source,
        nonce=nonce,
    )
    export_bytes = len(html.encode("utf-8"))
    if export_bytes > MAX_EXPORTED_ARTIFACT_BYTES:
        raise HTTPException(
            status_code=413,
            detail={
                "code": "export_size_limit",
                "message": (
                    f"Export is too large ({export_bytes} bytes, max {MAX_EXPORTED_ARTIFACT_BYTES})"
                ),
                "bytes": export_bytes,
                "max_bytes": MAX_EXPORTED_ARTIFACT_BYTES,
            },
        )
    filename = f"{artifact_id}-v{resolved_version}.html"
    return Response(
        html,
        media_type="text/html; charset=utf-8",
        headers=_headers(f'attachment; filename="{filename}"', nonce=nonce),
    )


@router.delete("/{artifact_id}")
async def delete_artifact(artifact_id: str) -> dict[str, Any]:
    deleted = delete_artifact_record(artifact_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return {"artifact_id": artifact_id, "deleted": True}
