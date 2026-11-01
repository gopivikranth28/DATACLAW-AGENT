"""OKF bundle registry backed by JSON under DATACLAW_HOME."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dataclaw.config.paths import plugin_data_dir


def okf_root() -> Path:
    return plugin_data_dir("okf")


def bundles_root() -> Path:
    path = okf_root() / "bundles"
    path.mkdir(parents=True, exist_ok=True)
    return path


def exports_root() -> Path:
    path = okf_root() / "exports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def registry_path() -> Path:
    return okf_root() / "bundles.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip().lower()).strip("-")
    return slug or "untitled"


def read_bundles() -> list[dict[str, Any]]:
    path = registry_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def write_bundles(bundles: list[dict[str, Any]]) -> None:
    path = registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(bundles, indent=2, default=str), encoding="utf-8")


def find_bundle(bundle_id: str) -> dict[str, Any]:
    for bundle in read_bundles():
        if bundle.get("id") == bundle_id:
            return bundle
    raise ValueError(f"OKF bundle not found: {bundle_id}")


def find_bundle_for_dataset(dataset_id: str) -> dict[str, Any] | None:
    for bundle in read_bundles():
        if bundle.get("dataset_id") == dataset_id:
            return bundle
    return None


def upsert_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    bundles = read_bundles()
    for idx, existing in enumerate(bundles):
        if existing.get("id") == bundle.get("id"):
            bundles[idx] = bundle
            write_bundles(bundles)
            return bundle
    bundles.append(bundle)
    write_bundles(bundles)
    return bundle


def new_bundle_id(dataset_name: str) -> str:
    return f"okf-{slugify(dataset_name)[:32]}-{uuid.uuid4().hex[:8]}"
