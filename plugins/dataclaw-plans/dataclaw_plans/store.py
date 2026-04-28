"""Plan proposal storage — JSON file backed."""

from __future__ import annotations

import json
from typing import Any

from dataclaw.config.paths import plugin_data_dir


def _proposals_file():
    return plugin_data_dir("plans") / "proposals.json"


def read_proposals() -> list[dict[str, Any]]:
    path = _proposals_file()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def write_proposals(proposals: list[dict[str, Any]]) -> None:
    path = _proposals_file()
    path.write_text(json.dumps(proposals, indent=2, default=str), encoding="utf-8")


def find_proposal(proposal_id: str) -> dict[str, Any]:
    for p in read_proposals():
        if p.get("id") == proposal_id:
            return p
    raise KeyError(f"Plan proposal not found: {proposal_id}")


def get_active_plan_id(session_id: str) -> str | None:
    """Return the ID of the most recent non-denied plan for a session."""
    for p in read_proposals():
        if p.get("session_id") == session_id and p.get("status") != "denied":
            return p["id"]
    return None
