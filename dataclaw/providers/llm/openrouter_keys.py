"""OpenRouter key management: provision, inspect and rotate inference keys.

A management key (formerly "provisioning key") can only manage keys; it
cannot call models.  DataClaw uses one, when the user supplies it, to create
an inference key for itself and stores only that inference key.

Handling of the management key: it is passed in as an argument (or read from
``OPENROUTER_MANAGEMENT_KEY`` on demand), used for the ``Authorization``
header of the requests below, and never written to config, logged, returned,
or included in an exception message.  Errors are raised with ``from None``
so no httpx exception (whose request carries the header) is chained, and any
upstream text is passed through ``redact`` first.

Wire format (https://openrouter.ai/openapi.json, checked 2026-10-26;
https://openrouter.ai/docs/guides/overview/auth/management-api-keys.md):

- ``POST /api/v1/keys`` (management key): body ``{"name", "limit"?: USD,
  "limit_reset"?: "daily"|"weekly"|"monthly"|null, "expires_at"?: ISO 8601
  UTC with seconds}``; ``201`` with ``{"key": <plaintext, shown once>,
  "data": {"hash", "name", "label", "limit", "limit_reset", "expires_at",
  ...}}``.
- ``GET /api/v1/keys/{hash}`` → ``{"data": {...}}``;
  ``DELETE /api/v1/keys/{hash}`` → ``200``.
- ``GET /api/v1/key`` (the inference key itself) → ``{"data": {"label",
  "limit", "limit_remaining", "limit_reset", "usage", "usage_daily",
  "usage_weekly", "usage_monthly", "is_free_tier", "is_management_key",
  "expires_at", ...}}``.
- Errors: ``{"error": {"code", "message"}}``.
"""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

from dataclaw.providers.llm.openrouter import DEFAULT_ATTRIBUTION_HEADERS, OPENROUTER_API_BASE

MANAGEMENT_KEY_ENV = "OPENROUTER_MANAGEMENT_KEY"
LIMIT_RESETS = ("daily", "weekly", "monthly")
REDACTED = "[redacted]"
_TIMEOUT = 20.0
# Default httpx transport for these calls (tests install a mock here).
TRANSPORT: httpx.AsyncBaseTransport | None = None

# Fields of GET /api/v1/key reported by the key-status endpoint.
KEY_STATUS_FIELDS = (
    "label",
    "limit",
    "limit_remaining",
    "limit_reset",
    "usage",
    "usage_daily",
    "usage_weekly",
    "usage_monthly",
    "is_free_tier",
    "is_management_key",
    "expires_at",
)


class OpenRouterKeyError(Exception):
    """A key-management request failed; ``message`` is safe to show and log."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


@dataclass
class CreatedKey:
    """A newly created inference key.  ``key`` is the plaintext secret."""

    key: str = field(repr=False)
    hash: str
    name: str
    label: str = ""
    limit: float | None = None
    limit_reset: str | None = None
    expires_at: str | None = None

    def public(self) -> dict[str, Any]:
        """Everything except the secret."""
        return {
            "key_hash": self.hash,
            "key_name": self.name,
            "key_label": self.label,
            "limit": self.limit,
            "limit_reset": self.limit_reset,
            "expires_at": self.expires_at,
        }


def redact(text: str, *secrets: str | None) -> str:
    """``text`` with every occurrence of each secret replaced."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, REDACTED)
    return text


def management_key_from_env() -> str:
    """``OPENROUTER_MANAGEMENT_KEY``, read on demand and never stored."""
    return os.environ.get(MANAGEMENT_KEY_ENV, "").strip()


def default_key_name() -> str:
    host = "".join(c if c.isalnum() or c in "-_." else "-" for c in socket.gethostname()).strip("-.") or "host"
    return f"dataclaw-{host}"[:100]


def normalize_limit(limit_usd: Any) -> float | None:
    if limit_usd is None or limit_usd == "":
        return None
    if isinstance(limit_usd, bool):
        raise OpenRouterKeyError(422, "The spending limit must be a number of US dollars.")
    try:
        value = float(limit_usd)
    except (TypeError, ValueError):
        raise OpenRouterKeyError(422, "The spending limit must be a number of US dollars.") from None
    if value != value or value < 0:
        raise OpenRouterKeyError(422, "The spending limit must be zero or more US dollars.")
    return value


def normalize_limit_reset(limit_reset: Any) -> str | None:
    if limit_reset in (None, "", "never", "none"):
        return None
    value = str(limit_reset).strip().lower()
    if value not in LIMIT_RESETS:
        raise OpenRouterKeyError(422, f"The limit reset must be one of {', '.join(LIMIT_RESETS)}, or empty for none.")
    return value


def normalize_expires_at(expires_at: Any) -> str | None:
    """ISO 8601 UTC with seconds (``YYYY-MM-DDTHH:MM:SSZ``), as the API requires."""
    if expires_at in (None, ""):
        return None
    raw = str(expires_at).strip()
    try:
        moment = datetime.fromisoformat(raw.replace("Z", "+00:00").replace("z", "+00:00"))
    except ValueError:
        raise OpenRouterKeyError(422, "The expiry must be an ISO 8601 date and time, e.g. 2027-01-31T00:00:00Z.") from None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    moment = moment.astimezone(timezone.utc)
    if moment <= datetime.now(timezone.utc):
        raise OpenRouterKeyError(422, "The expiry must be in the future.")
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


async def create_key(
    management_key: str,
    *,
    name: str,
    limit_usd: float | None = None,
    limit_reset: str | None = None,
    expires_at: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> CreatedKey:
    """``POST /api/v1/keys``: create an inference key (the secret is in the
    response only this once)."""
    _require_management_key(management_key)
    body: dict[str, Any] = {"name": name}
    if limit_usd is not None:
        body["limit"] = limit_usd
    if limit_reset is not None:
        body["limit_reset"] = limit_reset
    if expires_at is not None:
        body["expires_at"] = expires_at
    data = await _request(
        "POST", "/keys", management_key, json=body, transport=transport,
        action="create the key", forbidden="This is not a management key. Create one under openrouter.ai → Settings → Management keys.",
    )
    key = data.get("key") if isinstance(data, dict) else None
    info = data.get("data") if isinstance(data, dict) else None
    if not isinstance(key, str) or not key or not isinstance(info, dict) or not info.get("hash"):
        raise OpenRouterKeyError(502, "OpenRouter returned an unexpected response when creating the key.")
    return CreatedKey(
        key=key,
        hash=str(info["hash"]),
        name=str(info.get("name") or name),
        label=str(info.get("label") or ""),
        limit=_number(info.get("limit")),
        limit_reset=info.get("limit_reset") if isinstance(info.get("limit_reset"), str) else None,
        expires_at=info.get("expires_at") if isinstance(info.get("expires_at"), str) else None,
    )


async def get_key(
    management_key: str, key_hash: str, *, transport: httpx.AsyncBaseTransport | None = None
) -> dict[str, Any]:
    """``GET /api/v1/keys/{hash}``: a key's settings (no secret)."""
    _require_management_key(management_key)
    data = await _request("GET", f"/keys/{_hash_path(key_hash)}", management_key, transport=transport, action="read the key")
    info = data.get("data") if isinstance(data, dict) else None
    return info if isinstance(info, dict) else {}


async def delete_key(
    management_key: str, key_hash: str, *, transport: httpx.AsyncBaseTransport | None = None
) -> None:
    """``DELETE /api/v1/keys/{hash}``."""
    _require_management_key(management_key)
    await _request("DELETE", f"/keys/{_hash_path(key_hash)}", management_key, transport=transport, action="delete the old key")


async def key_status(api_key: str, *, transport: httpx.AsyncBaseTransport | None = None) -> dict[str, Any]:
    """``GET /api/v1/key`` with the inference key: usage, limit and remaining."""
    data = await _request("GET", "/key", api_key, transport=transport, action="read the key status", rejected="OpenRouter rejected the configured API key.")
    info = data.get("data") if isinstance(data, dict) else None
    if not isinstance(info, dict):
        raise OpenRouterKeyError(502, "OpenRouter returned an unexpected key status.")
    return {name: info.get(name) for name in KEY_STATUS_FIELDS}


async def _request(
    method: str,
    path: str,
    bearer: str,
    *,
    action: str,
    json: dict[str, Any] | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    rejected: str = "OpenRouter rejected the management key.",
    forbidden: str | None = None,
) -> Any:
    headers = {
        **DEFAULT_ATTRIBUTION_HEADERS,
        "Authorization": f"Bearer {bearer}",
        "Accept": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, transport=transport or TRANSPORT) as client:
            response = await client.request(method, f"{OPENROUTER_API_BASE}{path}", headers=headers, json=json)
    except httpx.HTTPError as exc:
        # No chaining: the exception's request holds the Authorization header.
        raise OpenRouterKeyError(502, f"Unable to reach OpenRouter to {action} ({type(exc).__name__}).") from None

    if response.status_code == 401:
        raise OpenRouterKeyError(401, rejected)
    if response.status_code == 403:
        raise OpenRouterKeyError(403, forbidden or f"OpenRouter refused to {action}: {_upstream_message(response, bearer)}")
    if response.status_code == 404:
        raise OpenRouterKeyError(404, f"OpenRouter could not find the key (while trying to {action}).")
    if response.status_code == 429:
        raise OpenRouterKeyError(429, "OpenRouter rate-limited the request. Try again shortly.")
    if response.is_error:
        status = 400 if response.status_code < 500 else 502
        raise OpenRouterKeyError(status, f"OpenRouter could not {action}: {_upstream_message(response, bearer)}")
    if response.status_code == 204 or not response.content:
        return {}
    try:
        return response.json()
    except ValueError:
        raise OpenRouterKeyError(502, f"OpenRouter returned an invalid response when asked to {action}.") from None


def _upstream_message(response: httpx.Response, *secrets: str) -> str:
    try:
        body = response.json()
    except ValueError:
        body = None
    message = None
    if isinstance(body, dict):
        error = body.get("error")
        message = error.get("message") if isinstance(error, dict) else error if isinstance(error, str) else body.get("message")
    text = str(message or f"HTTP {response.status_code}")
    return redact(text, *secrets)[:300]


def _require_management_key(management_key: str) -> None:
    if not management_key or not management_key.strip():
        raise OpenRouterKeyError(
            400, f"A management key is required: enter it, or set {MANAGEMENT_KEY_ENV} on the server."
        )


def _hash_path(key_hash: str) -> str:
    value = str(key_hash or "").strip()
    if not value or not all(c.isalnum() or c in "-_" for c in value):
        raise OpenRouterKeyError(400, "The stored OpenRouter key hash is invalid.")
    return value


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)
