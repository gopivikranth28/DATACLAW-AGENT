"""Artifact tools."""

from __future__ import annotations

from typing import Any

from dataclaw_artifacts.store import (
    MAX_EXPORTED_ARTIFACT_BYTES,
    append_living_report_event,
    delete_artifact_record,
    ensure_artifact_session,
    ensure_living_report,
    artifact_export_url,
    artifact_url,
    living_report_url,
    list_artifact_records,
    latest_version,
    read_meta,
    read_source,
    resolve_workspace_path,
    write_artifact_version,
)
from dataclaw_artifacts.validator import ArtifactValidationError, strip_dataclaw_runtime_scripts, validate_and_prepare_html
from dataclaw_artifacts.wrapper import export_shell, new_nonce


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
            "session_id": result.get("session_id"),
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
            strip_dataclaw_runtime_scripts(html or ""),
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
    session_id: str = "default",
    **_: Any,
) -> dict[str, Any]:
    meta = read_meta(artifact_id)
    ensure_artifact_session(meta, session_id)
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
    project_id: str | None = None,
    limit: int = 100,
    **_: Any,
) -> dict[str, Any]:
    if session_id:
        ensure_living_report(session_id, project_id, touch=False)
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
            "url": living_report_url(str(meta.get("id")), session_id or str(meta.get("session_id") or "default")) if is_living else artifact_url(str(meta.get("id")), latest, session_id or str(meta.get("session_id") or "default")) if latest else "",
        })
    return {"artifacts": artifacts, "total": len(artifacts)}


async def export_artifact(
    *,
    artifact_id: str,
    version: int | None = None,
    session_id: str = "default",
    **_: Any,
) -> dict[str, Any]:
    meta = read_meta(artifact_id)
    ensure_artifact_session(meta, session_id)
    resolved_version = version or latest_version(artifact_id)
    source = read_source(artifact_id, resolved_version)
    html = export_shell(
        artifact_id=artifact_id,
        version=resolved_version,
        title=str(meta.get("title") or artifact_id),
        source=source,
        nonce=new_nonce(),
    )
    export_bytes = len(html.encode("utf-8"))
    if export_bytes > MAX_EXPORTED_ARTIFACT_BYTES:
        return {
            "success": False,
            "artifact_id": artifact_id,
            "version": resolved_version,
            "error": {
                "code": "export_size_limit",
                "message": f"Export is too large ({export_bytes} bytes, max {MAX_EXPORTED_ARTIFACT_BYTES})",
                "bytes": export_bytes,
                "max_bytes": MAX_EXPORTED_ARTIFACT_BYTES,
            },
        }
    filename = f"{artifact_id}-v{resolved_version}.html"
    download_url = artifact_export_url(artifact_id, resolved_version, session_id)
    return {
        "success": True,
        "artifact_id": artifact_id,
        "version": resolved_version,
        "session_id": session_id,
        "filename": filename,
        "bytes": export_bytes,
        "download_url": download_url,
        "url": download_url,
    }


async def delete_artifact(
    *,
    artifact_id: str,
    session_id: str = "default",
    **_: Any,
) -> dict[str, Any]:
    meta = read_meta(artifact_id)
    ensure_artifact_session(meta, session_id)
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
    return {"success": True, "artifact_id": artifact_id, "session_id": session_id, "url": living_report_url(artifact_id, session_id), "event": event}
