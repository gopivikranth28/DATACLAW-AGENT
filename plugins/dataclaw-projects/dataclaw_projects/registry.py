"""Project registry — JSON file storage for project metadata."""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dataclaw.config.paths import plugin_data_dir

META_DIR_NAME = ".dataclaw"


def _registry_file() -> Path:
    return plugin_data_dir("projects") / "registry.json"


def _read_registry() -> list[dict[str, Any]]:
    path = _registry_file()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _write_registry(entries: list[dict[str, Any]]) -> None:
    path = _registry_file()
    path.write_text(json.dumps(entries, indent=2, default=str))


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower().strip()).strip("-")
    return slug or "project"


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text()) if path.exists() else (default if default is not None else {})
    except Exception:
        return default if default is not None else {}


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, default=str))


# ── CRUD ────────────────────────────────────────────────────────────────────


def list_projects() -> list[dict[str, Any]]:
    results = []
    for entry in _read_registry():
        meta_dir = Path(entry["directory"]) / META_DIR_NAME
        meta = _read_json(meta_dir / "project.json", entry)
        results.append(meta)
    return results


def get_project(project_id: str) -> dict[str, Any]:
    entry = _find_entry(project_id)
    meta_dir = Path(entry["directory"]) / META_DIR_NAME
    return _read_json(meta_dir / "project.json", entry)


# Required — always installed (DataClaw runtime + experiment tracking)
REQUIRED_PACKAGES = [
    "ipykernel",       # Jupyter kernel support
    "requests",        # DataClaw runtime API calls
    "duckdb",          # DataClaw SQL queries
    "mlflow",          # Experiment logging
]

# Default optional — installed by default, user can remove
DEFAULT_OPTIONAL_PACKAGES = [
    # Data Manipulation & Analysis
    "pandas", "numpy", "polars",
    # Visualization
    "matplotlib", "seaborn", "plotly",
    # Machine Learning & Statistics
    "scikit-learn", "statsmodels", "xgboost", "lightgbm", "catboost",
    # Scientific Computing
    "scipy",
    # Data Access
    "beautifulsoup4", "sqlalchemy",
]

DEFAULT_PACKAGES = REQUIRED_PACKAGES + DEFAULT_OPTIONAL_PACKAGES


def create_project(
    name: str,
    description: str = "",
    directory: str = "",
    python_version: str = "",
    kernel_mode: str = "new_env",
    kernel_python: str = "",
    packages: list[str] | None = None,
) -> dict[str, Any]:
    """Create a new project.

    kernel_mode: "new_env" (isolated venv, default), "system", or "custom".
    """
    slug = _slugify(name)
    now = datetime.now(timezone.utc).isoformat()

    if directory:
        user_dir = Path(directory).expanduser().resolve()
    else:
        user_dir = Path.home() / "dataclaw-projects" / slug

    user_dir.mkdir(parents=True, exist_ok=True)
    meta_dir = user_dir / META_DIR_NAME
    meta_dir.mkdir(exist_ok=True)

    if packages is None:
        packages = list(DEFAULT_PACKAGES)
    # Always ensure required packages are present
    for pkg in REQUIRED_PACKAGES:
        if pkg not in packages:
            packages.append(pkg)

    meta: dict[str, Any] = {
        "id": slug,
        "name": name,
        "description": description,
        "directory": str(user_dir),
        "created_at": now,
        "kernel": {
            "mode": kernel_mode,
            "python_version": python_version,
            "python_path": kernel_python if kernel_mode == "custom" else "",
            "packages": packages,
        },
    }
    _write_json(meta_dir / "project.json", meta)

    registry = _read_registry()
    if not any(e["id"] == slug for e in registry):
        registry.append({"id": slug, "directory": str(user_dir)})
        _write_registry(registry)

    return meta


def update_project(project_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    """Update project metadata fields (name, description, dataset_ids, etc.)."""
    entry = _find_entry(project_id)
    meta_dir = Path(entry["directory"]) / META_DIR_NAME
    meta = _read_json(meta_dir / "project.json", entry)
    for key in ("name", "description", "dataset_ids"):
        if key in updates:
            meta[key] = updates[key]
    meta["updated_at"] = datetime.now(timezone.utc).isoformat()
    _write_json(meta_dir / "project.json", meta)
    return meta


def delete_project(project_id: str) -> bool:
    entry = _find_entry(project_id)
    meta_dir = Path(entry["directory"]) / META_DIR_NAME
    if meta_dir.exists():
        shutil.rmtree(meta_dir)
    registry = [e for e in _read_registry() if e.get("id") != project_id]
    _write_registry(registry)
    return True


def _find_entry(project_id: str) -> dict[str, Any]:
    entry = next((e for e in _read_registry() if e.get("id") == project_id), None)
    if not entry:
        raise KeyError(f"Project not found: {project_id}")
    return entry


# ── Files ───────────────────────────────────────────────────────────────────


def list_project_files(project_id: str) -> dict[str, Any]:
    entry = _find_entry(project_id)
    user_dir = Path(entry["directory"])

    def scan(root: Path) -> list[dict[str, Any]]:
        if not root.exists():
            return []
        items = []
        try:
            for p in sorted(root.iterdir()):
                if p.name.startswith(".") or p.name == "__pycache__":
                    continue
                item: dict[str, Any] = {
                    "name": p.name,
                    "path": str(p),
                    "is_dir": p.is_dir(),
                    "size": p.stat().st_size if p.is_file() else 0,
                }
                if p.is_dir():
                    item["children"] = scan(p)
                items.append(item)
        except Exception:
            pass
        return items

    return {"project": scan(user_dir) if user_dir.exists() else []}
