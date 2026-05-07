"""Plan proposal storage — JSON file backed."""

from __future__ import annotations

import copy
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from dataclaw.config.paths import plugin_data_dir

# Per-proposal snapshot cap. Bounds growth on long agent runs while still
# preserving plenty of timeline history for chat scrollback.
SNAPSHOTS_PER_PROPOSAL = 200


def _proposals_file():
    return plugin_data_dir("plans") / "proposals.json"


def _snapshots_file():
    return plugin_data_dir("plans") / "plan_snapshots.json"


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


# ── Snapshots ───────────────────────────────────────────────────────────────


def read_snapshots() -> list[dict[str, Any]]:
    path = _snapshots_file()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def write_snapshots(snapshots: list[dict[str, Any]]) -> None:
    path = _snapshots_file()
    path.write_text(json.dumps(snapshots, indent=2, default=str), encoding="utf-8")


def append_snapshot(proposal: dict[str, Any], trigger: str) -> dict[str, Any]:
    """Persist a deep-copied snapshot of `proposal` and return the snapshot record.

    Snapshots are append-only chat history per tool call. Older snapshots
    beyond SNAPSHOTS_PER_PROPOSAL for the same proposal_id are dropped.
    """
    proposal_id = proposal.get("id")
    if not proposal_id:
        raise ValueError("Cannot snapshot proposal without an id")
    snapshot = {
        "id": f"snap-{uuid.uuid4().hex[:8]}",
        "proposal_id": proposal_id,
        "taken_at": datetime.now(timezone.utc).isoformat(),
        "trigger": trigger,
        "plan": copy.deepcopy(proposal),
    }
    all_snaps = read_snapshots()
    all_snaps.append(snapshot)

    # Prune oldest snapshots for this proposal beyond the cap. Other proposals
    # are untouched. Order within the proposal is taken_at-ascending (insertion
    # order); we keep the most recent SNAPSHOTS_PER_PROPOSAL.
    same_proposal_indices = [i for i, s in enumerate(all_snaps) if s.get("proposal_id") == proposal_id]
    excess = len(same_proposal_indices) - SNAPSHOTS_PER_PROPOSAL
    if excess > 0:
        drop = set(same_proposal_indices[:excess])
        all_snaps = [s for i, s in enumerate(all_snaps) if i not in drop]

    write_snapshots(all_snaps)
    return snapshot


def find_snapshot(snapshot_id: str) -> dict[str, Any]:
    for s in read_snapshots():
        if s.get("id") == snapshot_id:
            return s
    raise KeyError(f"Plan snapshot not found: {snapshot_id}")
