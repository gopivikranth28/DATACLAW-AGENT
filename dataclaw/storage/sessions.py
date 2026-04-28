"""Chat session persistence.

Sessions are stored as individual JSON files under ~/.dataclaw/sessions/.
Thread-safe via asyncio.Lock per session.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dataclaw.config.paths import sessions_dir

logger = logging.getLogger(__name__)

_locks: dict[str, asyncio.Lock] = {}


def _get_lock(session_id: str) -> asyncio.Lock:
    if session_id not in _locks:
        _locks[session_id] = asyncio.Lock()
    return _locks[session_id]


def _session_path(session_id: str) -> Path:
    return sessions_dir() / f"{session_id}.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def create_session(
    *,
    session_id: str | None = None,
    project_id: str | None = None,
    title: str = "New Chat",
    dataset_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Create a new chat session."""
    sid = session_id or str(uuid.uuid4())
    sessions_dir().mkdir(parents=True, exist_ok=True)

    session: dict[str, Any] = {
        "id": sid,
        "projectId": project_id,
        "title": title,
        "datasetIds": dataset_ids,
        "messages": [],
        "createdAt": _now_iso(),
        "updatedAt": _now_iso(),
    }

    async with _get_lock(sid):
        _session_path(sid).write_text(json.dumps(session, indent=2, default=str))

    return session


async def get_session(session_id: str) -> dict[str, Any] | None:
    """Load a session by ID."""
    path = _session_path(session_id)
    if not path.exists():
        return None
    async with _get_lock(session_id):
        return json.loads(path.read_text())


async def list_sessions(project_id: str | None = None) -> list[dict[str, Any]]:
    """List all sessions, optionally filtered by project."""
    sdir = sessions_dir()
    if not sdir.exists():
        return []
    sessions = []
    for path in sorted(sdir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(path.read_text())
            if project_id and data.get("projectId") != project_id:
                continue
            # Return without messages for listing
            sessions.append({k: v for k, v in data.items() if k != "messages"})
        except (json.JSONDecodeError, OSError):
            logger.warning("Skipping corrupt session file: %s", path)
    return sessions


async def delete_session(session_id: str) -> bool:
    """Delete a session."""
    path = _session_path(session_id)
    if not path.exists():
        return False
    async with _get_lock(session_id):
        path.unlink()
    _locks.pop(session_id, None)
    return True


async def append_message(session_id: str, message: dict[str, Any]) -> None:
    """Append a message to a session, creating it if needed."""
    path = _session_path(session_id)
    sessions_dir().mkdir(parents=True, exist_ok=True)

    async with _get_lock(session_id):
        if path.exists():
            data = json.loads(path.read_text())
        else:
            data = {
                "id": session_id,
                "projectId": None,
                "title": "New Chat",
                "messages": [],
                "createdAt": _now_iso(),
                "updatedAt": _now_iso(),
            }

        # Dedup by messageId
        msg_id = message.get("messageId")
        if msg_id:
            existing_ids = {m.get("messageId") for m in data["messages"]}
            if msg_id in existing_ids:
                return

        if "timestamp" not in message:
            message["timestamp"] = _now_iso()
        data["messages"].append(message)
        data["updatedAt"] = _now_iso()
        path.write_text(json.dumps(data, indent=2, default=str))


async def update_session(session_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
    """Update session fields (title, projectId, etc.)."""
    path = _session_path(session_id)
    if not path.exists():
        return None

    async with _get_lock(session_id):
        data = json.loads(path.read_text())
        for key, value in updates.items():
            if key not in ("id", "messages", "createdAt"):
                data[key] = value
        data["updatedAt"] = _now_iso()
        path.write_text(json.dumps(data, indent=2, default=str))

    return data
