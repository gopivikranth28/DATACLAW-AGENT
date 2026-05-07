"""Kaggle registry — JSON file storage for tracked competitions, datasets, and submissions."""

from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dataclaw.config.paths import plugin_data_dir

_REGISTRY_FILE = "registry.json"


def _registry_path() -> Path:
    return plugin_data_dir("kaggle") / _REGISTRY_FILE


def _empty_registry() -> dict[str, Any]:
    return {"competitions": {}, "datasets": {}, "submissions": []}


def read_registry() -> dict[str, Any]:
    path = _registry_path()
    if not path.exists():
        return _empty_registry()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else _empty_registry()
    except Exception:
        return _empty_registry()


def write_registry(data: dict[str, Any]) -> None:
    path = _registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


# ── Competitions ────────────────────────────────────────────────────────────


def track_competition(slug: str, metadata: dict[str, Any]) -> dict[str, Any]:
    """Add or update a competition entry in the registry."""
    reg = read_registry()
    now = datetime.now(timezone.utc).isoformat()
    existing = reg["competitions"].get(slug, {})
    entry = {**existing, **metadata, "slug": slug, "fetched_at": now}
    reg["competitions"][slug] = entry
    write_registry(reg)
    return entry


def get_competition(slug: str) -> dict[str, Any] | None:
    return read_registry()["competitions"].get(slug)


def list_competitions() -> list[dict[str, Any]]:
    return list(read_registry()["competitions"].values())


# ── Datasets ────────────────────────────────────────────────────────────────


def track_dataset(ref: str, metadata: dict[str, Any]) -> dict[str, Any]:
    """Add or update a dataset entry in the registry."""
    reg = read_registry()
    now = datetime.now(timezone.utc).isoformat()
    existing = reg["datasets"].get(ref, {})
    entry = {**existing, **metadata, "ref": ref, "fetched_at": now}
    reg["datasets"][ref] = entry
    write_registry(reg)
    return entry


def get_dataset(ref: str) -> dict[str, Any] | None:
    return read_registry()["datasets"].get(ref)


def list_datasets() -> list[dict[str, Any]]:
    return list(read_registry()["datasets"].values())


# ── Downloads (shared by competitions and datasets) ─────────────────────────


def record_download(
    kind: str,
    key: str,
    download_path: str,
    files: list[str],
    dataclaw_dataset_id: str | None = None,
) -> dict[str, Any]:
    """Mark a competition or dataset as downloaded."""
    reg = read_registry()
    now = datetime.now(timezone.utc).isoformat()
    collection = reg.get(kind, {})
    entry = collection.get(key, {})
    entry.update({
        "downloaded": True,
        "download_path": download_path,
        "files": files,
        "downloaded_at": now,
    })
    if dataclaw_dataset_id:
        entry["dataclaw_dataset_id"] = dataclaw_dataset_id
    collection[key] = entry
    reg[kind] = collection
    write_registry(reg)
    return entry


def delete_download(kind: str, key: str, remove_files: bool = False) -> bool:
    """Remove a download record. Optionally delete the files on disk."""
    reg = read_registry()
    collection = reg.get(kind, {})
    entry = collection.get(key)
    if not entry:
        return False
    if remove_files:
        dl_path = entry.get("download_path", "")
        if dl_path:
            p = Path(dl_path)
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            elif p.is_file():
                p.unlink(missing_ok=True)
    del collection[key]
    write_registry(reg)
    return True


# ── Submissions ─────────────────────────────────────────────────────────────


def record_submission(
    competition: str,
    file_path: str,
    message: str,
    result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    reg = read_registry()
    entry: dict[str, Any] = {
        "id": f"sub_{uuid.uuid4().hex[:8]}",
        "competition": competition,
        "file_path": file_path,
        "message": message,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
    }
    if result:
        entry.update(result)
    reg["submissions"].append(entry)
    write_registry(reg)
    return entry


def list_submissions(competition: str | None = None) -> list[dict[str, Any]]:
    subs = read_registry()["submissions"]
    if competition:
        subs = [s for s in subs if s.get("competition") == competition]
    return subs
