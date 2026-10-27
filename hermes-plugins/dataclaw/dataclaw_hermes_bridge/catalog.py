"""Hermes handler for Dataclaw's session-scoped tool catalog."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx

from .correlation import decode_correlation

SEARCH_SCHEMA = {
    "name": "dataclaw_tool_search",
    "description": (
        "Search the Dataclaw tools enabled for this run. A search miss returns "
        "the complete enabled catalog."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 100,
                "default": 8,
            },
        },
        "additionalProperties": False,
    },
}


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
    return (
        str(
            os.environ.get("DATACLAW_API_URL")
            or values.get("DATACLAW_API_URL")
            or "http://127.0.0.1:8000"
        ).rstrip("/"),
        float(
            os.environ.get("DATACLAW_HERMES_TOOL_TIMEOUT_SECONDS")
            or values.get("DATACLAW_HERMES_TOOL_TIMEOUT_SECONDS")
            or 330
        ),
        _auth_headers(values),
    )


def _auth_headers(values: dict[str, Any]) -> dict[str, str]:
    # Dataclaw's API token, written by the installer next to the extension.
    token = str(os.environ.get("DATACLAW_TOKEN") or values.get("DATACLAW_TOKEN") or "")
    return {"X-Dataclaw-Token": token} if token else {}


def search_catalog(params: dict[str, Any], **kwargs: Any) -> str:
    try:
        correlation = decode_correlation(str(kwargs.get("task_id") or ""))
        base_url, timeout, headers = _settings()
        body = {
            **correlation,
            "query": str(params.get("query") or "")[:2000],
            "limit": max(1, min(int(params.get("limit") or 8), 100)),
        }
        with httpx.Client(base_url=base_url, timeout=timeout, headers=headers) as client:
            response = client.post("/api/hermes/tools/search", json=body)
            response.raise_for_status()
            return json.dumps(response.json(), default=str)
    except Exception as exc:
        return json.dumps({"tools": [], "error": str(exc)[:1000]})
