"""Subagent definition CRUD — JSON file storage."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dataclaw.config.paths import plugin_data_dir


def _subagents_dir() -> Path:
    d = plugin_data_dir("projects") / "subagents"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _slugify(name: str) -> str:
    slug = name.lower().replace(" ", "-").replace("_", "-")
    return "".join(c for c in slug if c.isalnum() or c == "-") or "subagent"


def list_subagent_definitions() -> list[dict[str, Any]]:
    results = []
    for path in sorted(_subagents_dir().glob("*.json")):
        try:
            data = json.loads(path.read_text())
            data.setdefault("id", path.stem)
            data.pop("config", None)  # Omit for listing
            results.append(data)
        except Exception:
            continue
    return results


def get_subagent_definition(subagent_id: str) -> dict[str, Any]:
    path = _subagents_dir() / f"{subagent_id}.json"
    if not path.exists():
        raise KeyError(f"Subagent not found: {subagent_id}")
    data = json.loads(path.read_text())
    data.setdefault("id", path.stem)
    return data


def create_subagent_definition(
    name: str,
    description: str = "",
    agent_type: str = "llm",
    allowed_tools: list[str] | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    subagent_id = _slugify(name)
    path = _subagents_dir() / f"{subagent_id}.json"
    if path.exists():
        raise ValueError(f"Subagent '{subagent_id}' already exists")
    now = datetime.now(timezone.utc).isoformat()
    definition = {
        "id": subagent_id,
        "name": name,
        "description": description,
        "agent_type": agent_type,
        "allowed_tools": allowed_tools or [],
        "config": config or {},
        "created_at": now,
        "updated_at": now,
    }
    path.write_text(json.dumps(definition, indent=2))
    return definition


def update_subagent_definition(subagent_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    path = _subagents_dir() / f"{subagent_id}.json"
    if not path.exists():
        raise KeyError(f"Subagent not found: {subagent_id}")
    existing = json.loads(path.read_text())
    for key, value in updates.items():
        if key not in ("id", "created_at") and value is not None:
            existing[key] = value
    existing["updated_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(existing, indent=2))
    return existing


def delete_subagent_definition(subagent_id: str) -> bool:
    path = _subagents_dir() / f"{subagent_id}.json"
    if not path.exists():
        return False
    path.unlink()
    return True
