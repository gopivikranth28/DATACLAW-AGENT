"""Artifact tools."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
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


_STRUCTURED_REPORT_RE = re.compile(r"<script\b(?=[^>]*\bdata-dc-section-meta\b)", re.IGNORECASE)


def _report_receipt_error(code: str, message: str) -> dict[str, Any]:
    return {"success": False, "error": {"code": code, "message": message}}


def _validate_structured_report_receipt(
    *,
    html: str,
    source_path: str | None,
    report_receipt_path: str | None,
    session_id: str,
    project_id: str | None,
) -> dict[str, Any] | None:
    """Require a current workspace publish receipt for structured reports.

    Report-builder HTML is recognised from its typed section metadata.  It must
    have passed ``report_publish`` for the exact HTML bytes before artifact
    publication can create a version.  Generic hand-authored artifacts retain
    the normal artifact validator workflow.
    """
    if not _STRUCTURED_REPORT_RE.search(html):
        return None

    if report_receipt_path is None and source_path:
        report_receipt_path = str(Path(source_path).with_suffix(".publish.json"))
    if not report_receipt_path:
        return _report_receipt_error(
            "report_publish_receipt_missing",
            "Structured report publication requires report_receipt_path from report_publish.",
        )
    try:
        receipt_path = resolve_workspace_path(
            report_receipt_path,
            session_id=session_id,
            project_id=project_id,
        )
    except ValueError:
        return _report_receipt_error(
            "report_publish_receipt_invalid",
            "The report publish receipt path is outside the allowed workspace.",
        )
    if not receipt_path.is_file():
        return _report_receipt_error(
            "report_publish_receipt_missing",
            "Structured report publication requires a current report_publish receipt.",
        )
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _report_receipt_error(
            "report_publish_receipt_invalid",
            "The report publish receipt is not valid JSON.",
        )
    if not isinstance(receipt, dict) or receipt.get("status") != "published":
        return _report_receipt_error(
            "report_publish_receipt_invalid",
            "The report publish receipt does not record a successful publication.",
        )
    expected_hash = str(receipt.get("html_sha256") or "").strip().lower()
    actual_hash = hashlib.sha256(html.encode("utf-8")).hexdigest()
    if not expected_hash or expected_hash != actual_hash:
        return _report_receipt_error(
            "report_publish_receipt_stale",
            "The report HTML has changed since report_publish; publish it again before creating an artifact.",
        )
    review = receipt.get("analytical_review")
    if not isinstance(review, dict):
        return _report_receipt_error(
            "report_publish_receipt_invalid",
            "The report publish receipt has no analytical-review record.",
        )
    required = [
        finding for finding in review.get("findings", [])
        if isinstance(finding, dict)
        and str(finding.get("severity") or "").strip().lower() == "required"
        and str(finding.get("lifecycle_status") or "open") != "accepted_with_rationale"
    ]
    if required:
        return _report_receipt_error(
            "report_publish_review_blocked",
            "The report publish receipt contains unresolved required analytical-review findings.",
        )
    return None


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
    report_receipt_path: str | None = None,
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

    receipt_error = _validate_structured_report_receipt(
        html=html or "",
        source_path=source_path,
        report_receipt_path=report_receipt_path,
        session_id=session_id,
        project_id=project_id,
    )
    if receipt_error:
        return receipt_error

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
