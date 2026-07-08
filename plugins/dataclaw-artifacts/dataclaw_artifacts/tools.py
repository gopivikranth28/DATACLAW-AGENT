"""Artifact tools."""

from __future__ import annotations

from typing import Any

from dataclaw_artifacts.store import (
    append_living_report_event,
    delete_artifact_record,
    list_artifact_records,
    read_meta,
    read_source,
    resolve_workspace_path,
    write_artifact_version,
)
from dataclaw_artifacts.validator import ArtifactValidationError, validate_and_prepare_html


def _emit_artifact_published(result: dict[str, Any], title: str, description: str) -> None:
    try:
        from dataclaw.api.context import current_emitter, current_thread_id
        from dataclaw.api.run_tracker import get_run_tracker

        emitter = current_emitter.get()
        thread_id = current_thread_id.get()
        event = emitter.custom("artifact_published", {
            "artifact_id": result["artifact_id"],
            "version": result["version"],
            "url": result["url"],
            "title": title,
            "description": description,
        })
        get_run_tracker().append_event(thread_id, event)
    except LookupError:
        return
    except Exception:
        return


async def publish_artifact(
    *,
    title: str,
    description: str = "",
    source_path: str | None = None,
    html: str | None = None,
    artifact_id: str | None = None,
    label: str = "",
    base_version: int | None = None,
    session_id: str = "default",
    project_id: str | None = None,
    **_: Any,
) -> dict[str, Any]:
    if not title.strip():
        raise ValueError("title is required")
    if bool(source_path) == bool(html):
        raise ValueError("Provide exactly one of source_path or html")

    base_dir = None
    if source_path:
        source = resolve_workspace_path(source_path, session_id=session_id, project_id=project_id)
        if not source.exists() or not source.is_file():
            raise ValueError(f"Source file not found: {source_path}")
        html = source.read_text(encoding="utf-8", errors="replace")
        base_dir = source.parent

    try:
        prepared = validate_and_prepare_html(
            html or "",
            base_dir=base_dir,
            session_id=session_id,
            project_id=project_id,
        )
    except ArtifactValidationError as exc:
        return {"success": False, "error": exc.to_dict()}

    result = write_artifact_version(
        title=title,
        description=description,
        html=prepared,
        source_path=source_path,
        artifact_id=artifact_id,
        label=label,
        base_version=base_version,
        session_id=session_id,
        project_id=project_id,
    )
    if result.get("success"):
        _emit_artifact_published(result, title, description)
    return result


async def read_artifact(
    *,
    artifact_id: str,
    version: int | None = None,
    **_: Any,
) -> dict[str, Any]:
    meta = read_meta(artifact_id)
    version = version or int(meta.get("latest_version") or 0)
    return {
        "artifact_id": artifact_id,
        "version": version,
        "title": meta.get("title", ""),
        "description": meta.get("description", ""),
        "source_path": meta.get("source_path", ""),
        "html": read_source(artifact_id, version),
    }


async def list_artifacts(
    *,
    session_id: str = "",
    limit: int = 100,
    **_: Any,
) -> dict[str, Any]:
    artifacts = []
    for meta in list_artifact_records(session_id=session_id, limit=limit):
        latest = int(meta.get("latest_version") or 0)
        is_living = meta.get("kind") == "living_report"
        artifacts.append({
            "artifact_id": meta.get("id"),
            "kind": meta.get("kind", "artifact"),
            "title": meta.get("title", ""),
            "description": meta.get("description", ""),
            "session_id": meta.get("session_id", ""),
            "project_id": meta.get("project_id", ""),
            "latest_version": latest,
            "versions": meta.get("versions", []),
            "source_path": meta.get("source_path", ""),
            "updated_at": meta.get("updated_at", ""),
            "url": f"/api/artifacts/{meta.get('id')}/living" if is_living else f"/api/artifacts/{meta.get('id')}?version={latest}" if latest else "",
        })
    return {"artifacts": artifacts, "total": len(artifacts)}


async def delete_artifact(
    *,
    artifact_id: str,
    **_: Any,
) -> dict[str, Any]:
    deleted = delete_artifact_record(artifact_id)
    return {"artifact_id": artifact_id, "deleted": deleted, "success": deleted}


async def report_note(
    *,
    page: str,
    markdown: str,
    plan_step_id: str = "",
    session_id: str = "default",
    project_id: str | None = None,
    **_: Any,
) -> dict[str, Any]:
    # Persist the same append-only event shape the compiler and hooks consume.
    artifact_id, event = append_living_report_event(session_id=session_id, project_id=project_id, event={
        "kind": "note",
        "page": page,
        "plan_step_id": plan_step_id,
        "status": "active",
        "session_id": session_id,
        "project_id": project_id,
        "payload": {"md": markdown},
    })
    return {"success": True, "artifact_id": artifact_id, "url": f"/api/artifacts/{artifact_id}/living", "event": event}
