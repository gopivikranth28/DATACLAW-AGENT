"""Disk store for DataClaw artifacts."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from dataclaw.config.paths import workspaces_dir

MAX_PUBLISHED_ARTIFACT_BYTES = 25 * 1024 * 1024
MAX_EXPORTED_ARTIFACT_BYTES = 25 * 1024 * 1024
MAX_ARTIFACT_BYTES = MAX_PUBLISHED_ARTIFACT_BYTES
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_id(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in value.strip())
    return safe or "default"


def artifacts_root() -> Path:
    root = workspaces_dir() / "artifacts"
    root.mkdir(parents=True, exist_ok=True)
    return root


def artifact_dir(artifact_id: str) -> Path:
    if not re.fullmatch(r"art-[a-f0-9]{8}", artifact_id):
        raise ValueError(f"Invalid artifact_id: {artifact_id}")
    return artifacts_root() / artifact_id


def new_artifact_id() -> str:
    return f"art-{uuid.uuid4().hex[:8]}"


def living_report_id(session_id: str) -> str:
    return f"art-{sha256((session_id or 'default').encode('utf-8')).hexdigest()[:8]}"


def _artifact_lock(artifact_id: str) -> threading.Lock:
    with _locks_guard:
        lock = _locks.get(artifact_id)
        if lock is None:
            lock = threading.Lock()
            _locks[artifact_id] = lock
        return lock


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        try:
            dir_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _version_files(path: Path) -> list[Path]:
    return sorted(
        path.glob("v*.html"),
        key=lambda p: int(p.stem[1:]) if p.stem[1:].isdigit() else -1,
    )


def latest_version(artifact_id: str) -> int:
    path = artifact_dir(artifact_id)
    versions = [
        int(p.stem[1:])
        for p in path.glob("v*.html")
        if p.stem[1:].isdigit()
    ]
    if not versions:
        raise KeyError(f"Artifact not found: {artifact_id}")
    return max(versions)


def read_meta(artifact_id: str) -> dict[str, Any]:
    path = artifact_dir(artifact_id)
    meta_path = path / "meta.json"
    if not meta_path.exists():
        raise KeyError(f"Artifact not found: {artifact_id}")
    meta = _read_json(meta_path, {})
    if not isinstance(meta, dict):
        raise ValueError(f"Corrupt artifact metadata: {artifact_id}")
    return meta


def read_source(artifact_id: str, version: int | None = None) -> str:
    version = version or latest_version(artifact_id)
    path = artifact_dir(artifact_id) / f"v{version}.html"
    if not path.exists():
        raise KeyError(f"Artifact version not found: {artifact_id} v{version}")
    return path.read_text(encoding="utf-8")


def read_manifest_events(artifact_id: str) -> list[dict[str, Any]]:
    path = artifact_dir(artifact_id) / "manifest.jsonl"
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def get_project_dir(project_id: str | None) -> Path | None:
    if not project_id:
        return None
    try:
        from dataclaw_projects.registry import get_project
        project = get_project(project_id)
        directory = project.get("directory")
        if directory:
            return Path(directory).expanduser().resolve()
    except Exception:
        return None
    return None


def workspace_base(session_id: str = "default", project_id: str | None = None) -> Path:
    project_dir = get_project_dir(project_id)
    if project_dir is not None:
        project_dir.mkdir(parents=True, exist_ok=True)
        return project_dir
    base = workspaces_dir() / _safe_id(session_id or "default")
    base.mkdir(parents=True, exist_ok=True)
    return base


def allowed_roots() -> list[Path]:
    roots = [
        workspaces_dir().resolve(),
        artifacts_root().resolve(),
        (Path.home() / "dataclaw-projects").resolve(),
    ]
    try:
        from dataclaw_projects.registry import _read_registry
        for entry in _read_registry():
            directory = entry.get("directory", "")
            if directory:
                roots.append(Path(directory).expanduser().resolve())
    except Exception:
        pass
    return roots


def ensure_allowed_path(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    for root in allowed_roots():
        try:
            resolved.relative_to(root)
            return resolved
        except ValueError:
            continue
    raise ValueError("Path is outside allowed directories")


def resolve_workspace_path(
    path: str,
    *,
    session_id: str = "default",
    project_id: str | None = None,
) -> Path:
    raw = Path(path).expanduser()
    if raw.is_absolute():
        return ensure_allowed_path(raw)
    return ensure_allowed_path(workspace_base(session_id, project_id) / raw)


def canonical_source_path(
    *,
    artifact_id: str,
    title: str,
    source_path: str | None,
    session_id: str,
    project_id: str | None,
) -> Path:
    if source_path:
        return resolve_workspace_path(source_path, session_id=session_id, project_id=project_id)
    slug = _safe_id(title.lower())[:48].strip("-_") or artifact_id
    return workspace_base(session_id, project_id) / "artifacts" / f"{slug}-{artifact_id}.html"


def write_artifact_version(
    *,
    title: str,
    html: str,
    description: str = "",
    source_path: str | None = None,
    artifact_id: str | None = None,
    label: str = "",
    base_version: int | None = None,
    session_id: str = "default",
    project_id: str | None = None,
) -> dict[str, Any]:
    encoded = html.encode("utf-8")
    if len(encoded) > MAX_PUBLISHED_ARTIFACT_BYTES:
        raise ValueError(
            f"Artifact is too large ({len(encoded)} bytes, max {MAX_PUBLISHED_ARTIFACT_BYTES})"
        )

    artifact_id = artifact_id or new_artifact_id()
    path = artifact_dir(artifact_id)
    source = canonical_source_path(
        artifact_id=artifact_id,
        title=title,
        source_path=source_path,
        session_id=session_id,
        project_id=project_id,
    )

    with _artifact_lock(artifact_id):
        path.mkdir(parents=True, exist_ok=True)
        meta_path = path / "meta.json"
        versions = _version_files(path)
        latest = int(versions[-1].stem[1:]) if versions else 0

        if base_version is not None and latest and base_version != latest:
            return {
                "success": False,
                "error": {
                    "code": "version_conflict",
                    "message": f"Artifact {artifact_id} is at v{latest}, not v{base_version}",
                    "latest_version": latest,
                    "base_version": base_version,
                },
            }

        digest = sha256(encoded).hexdigest()
        meta = _read_json(meta_path, {}) if meta_path.exists() else {}
        existing_versions = meta.get("versions", []) if isinstance(meta, dict) else []
        for record in existing_versions:
            if record.get("sha256") == digest:
                version = int(record.get("version") or 0)
                _atomic_write_text(source, html)
                return {
                    "success": True,
                    "artifact_id": artifact_id,
                    "version": version,
                    "url": f"/api/artifacts/{artifact_id}?version={version}",
                    "source_path": str(source),
                    "deduped": True,
                }

        version = latest + 1
        _atomic_write_text(path / f"v{version}.html", html)
        _atomic_write_text(source, html)

        now = _now_iso()
        if not meta:
            meta = {
                "id": artifact_id,
                "title": title,
                "description": description,
                "session_id": session_id,
                "project_id": project_id,
                "created_at": now,
                "versions": [],
            }
        meta.update({
            "id": artifact_id,
            "title": title,
            "description": description,
            "session_id": session_id,
            "project_id": project_id,
            "source_path": str(source),
            "latest_version": version,
            "updated_at": now,
        })
        meta.setdefault("versions", []).append({
            "version": version,
            "label": label,
            "sha256": digest,
            "bytes": len(encoded),
            "created_at": now,
        })
        _atomic_write_text(meta_path, json.dumps(meta, indent=2, default=str))

    return {
        "success": True,
        "artifact_id": artifact_id,
        "version": version,
        "url": f"/api/artifacts/{artifact_id}?version={version}",
        "source_path": str(source),
        "deduped": False,
    }


def list_artifact_records(session_id: str = "", limit: int = 100) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    root = artifacts_root()
    for meta_file in root.glob("art-*/meta.json"):
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        if session_id and meta.get("session_id") != session_id:
            continue
        records.append(meta)
    living = [r for r in records if r.get("kind") == "living_report"]
    others = [r for r in records if r.get("kind") != "living_report"]
    others.sort(key=lambda r: str(r.get("updated_at") or r.get("created_at") or ""), reverse=True)
    records = living + others
    return records[: max(limit, 0)]


def delete_artifact_record(artifact_id: str) -> bool:
    path = artifact_dir(artifact_id)
    if not path.exists():
        return False
    with _artifact_lock(artifact_id):
        shutil.rmtree(path)
    return True


def ensure_living_report(session_id: str, project_id: str | None = None) -> dict[str, Any]:
    artifact_id = living_report_id(session_id)
    path = artifact_dir(artifact_id)
    path.mkdir(parents=True, exist_ok=True)
    meta_path = path / "meta.json"
    now = _now_iso()
    meta = _read_json(meta_path, {}) if meta_path.exists() else {}
    if not isinstance(meta, dict):
        meta = {}
    if not meta:
        meta = {
            "id": artifact_id,
            "kind": "living_report",
            "title": "Living Report",
            "description": "Current investigation narrative compiled from artifact events.",
            "session_id": session_id,
            "project_id": project_id,
            "created_at": now,
            "versions": [],
            "latest_version": 0,
        }
    meta.update({
        "id": artifact_id,
        "kind": "living_report",
        "session_id": session_id,
        "project_id": project_id,
        "updated_at": now,
        "url": f"/api/artifacts/{artifact_id}/living",
    })
    _atomic_write_text(meta_path, json.dumps(meta, indent=2, default=str))
    return meta


def append_manifest_event(artifact_id: str, event: dict[str, Any]) -> dict[str, Any]:
    path = artifact_dir(artifact_id)
    path.mkdir(parents=True, exist_ok=True)
    event = {
        "id": event.get("id") or f"e-{uuid.uuid4().hex[:8]}",
        "ts": event.get("ts") or _now_iso(),
        **event,
    }
    line = json.dumps(event, default=str)
    manifest = path / "manifest.jsonl"
    with _artifact_lock(artifact_id):
        with manifest.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())
    return event


def append_living_report_event(
    *,
    session_id: str,
    project_id: str | None = None,
    event: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    meta = ensure_living_report(session_id, project_id)
    appended = append_manifest_event(str(meta["id"]), event)
    ensure_living_report(session_id, project_id)
    return str(meta["id"]), appended
