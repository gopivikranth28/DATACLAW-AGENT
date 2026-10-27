"""Synchronous Hermes tool handlers that call the Dataclaw bridge."""

from __future__ import annotations

import json
import os
import threading
from contextvars import ContextVar
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from .correlation import decode_correlation

DISPATCH_SCHEMA = {
    "name": "dataclaw_tool",
    "description": (
        "Execute one tool from the enabled Dataclaw catalog. Use the exact "
        "tool_name and argument object supplied by the catalog."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "tool_name": {
                "type": "string",
                "description": "Exact enabled Dataclaw tool name.",
            },
            "params": {
                "type": "object",
                "description": "Arguments matching that tool's input schema.",
            },
        },
        "required": ["tool_name", "params"],
        "additionalProperties": False,
    },
}

_current_tool_call_id: ContextVar[str] = ContextVar(
    "dataclaw_hermes_tool_call_id", default=""
)
_run_locks: dict[str, threading.Lock] = {}
_run_locks_guard = threading.Lock()


def _settings() -> tuple[str, float, dict[str, str]]:
    values: dict[str, Any] = {}
    path = Path(__file__).resolve().parents[1] / ".dataclaw-env.json"
    if path.exists():
        try:
            loaded = json.loads(path.read_text())
            if isinstance(loaded, dict):
                values = loaded
        except Exception:
            values = {}
    base_url = str(
        os.environ.get("DATACLAW_API_URL")
        or values.get("DATACLAW_API_URL")
        or "http://127.0.0.1:8000"
    ).rstrip("/")
    timeout = float(
        os.environ.get("DATACLAW_HERMES_TOOL_TIMEOUT_SECONDS")
        or values.get("DATACLAW_HERMES_TOOL_TIMEOUT_SECONDS")
        or 330
    )
    # Dataclaw's API token, written by the installer next to the extension.
    token = str(os.environ.get("DATACLAW_TOKEN") or values.get("DATACLAW_TOKEN") or "")
    headers = {"X-Dataclaw-Token": token} if token else {}
    return base_url, timeout, headers


def _run_lock(run_id: str) -> threading.Lock:
    with _run_locks_guard:
        return _run_locks.setdefault(run_id, threading.Lock())


def capture_tool_call_id(
    tool_name: str,
    tool_call_id: str = "",
    **kwargs: Any,
) -> None:
    """Capture the stable Hermes id before registry.dispatch drops it."""
    del kwargs
    if tool_name in {"dataclaw_tool", "dataclaw_tool_search"}:
        _current_tool_call_id.set(str(tool_call_id or ""))


def dispatch_tool(params: dict[str, Any], **kwargs: Any) -> str:
    tool_name = str(params.get("tool_name") or "").strip()
    arguments = params.get("params")
    task_id = str(kwargs.get("task_id") or "")
    tool_call_id = _current_tool_call_id.get()
    _current_tool_call_id.set("")
    try:
        if not tool_name:
            raise ValueError("tool_name is required")
        if not isinstance(arguments, dict):
            raise ValueError("params must be an object")
        if not tool_call_id:
            raise ValueError("Hermes did not supply a stable tool_call_id")
        correlation = decode_correlation(task_id)
        run_id = correlation["runId"]
        base_url, timeout, headers = _settings()

        # Acquire before creating/sending the callback request. Time spent
        # queued behind another Dataclaw call does not consume the configured
        # HTTP callback timeout; Hermes may retry if its own outer wait expires.
        with _run_lock(run_id):
            with httpx.Client(
                base_url=base_url, timeout=timeout, headers=headers
            ) as client:
                context_response = client.get(
                    f"/api/hermes/runs/{quote(run_id, safe='')}/context"
                )
                context_response.raise_for_status()
                context = context_response.json()
                body = {
                    "runtimeRunId": context.get("runtimeRunId") or "",
                    "toolCallId": tool_call_id,
                    "runId": run_id,
                    "sessionId": correlation["sessionId"],
                    "projectId": correlation.get("projectId"),
                    "params": arguments,
                }
                response = client.post(
                    "/api/hermes/tools/"
                    + quote(tool_name, safe="")
                    + "/call",
                    json=body,
                )
                response.raise_for_status()
                return json.dumps(response.json(), default=str)
    except Exception as exc:
        return json.dumps(
            {
                "state": "failed",
                "isError": True,
                "content": str(exc)[:1000],
                "guardrailId": None,
            }
        )
