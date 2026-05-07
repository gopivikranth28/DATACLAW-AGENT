"""Codex auth bridge — resolves credentials for OpenAI API access.

All Codex auth state lives under ``DATACLAW_HOME/codex/`` so the
system-installed ``codex`` CLI (which uses ``~/.codex``) is never
affected.  Interactive login writes ``auth.json`` there via the
app-server with ``CODEX_HOME`` pointed at this directory.

Two auth modes:
- default: reads the OAuth access_token from auth.json (populated
  by interactive login).  Hits the ChatGPT backend Responses API.
- api_key: uses a provided OpenAI API key with the standard API.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from dataclaw.config.paths import DATACLAW_HOME

logger = logging.getLogger(__name__)

CODEX_HOME = DATACLAW_HOME / "codex"

# ChatGPT backend Responses API (used with OAuth tokens)
CODEX_BASE_URL = "https://chatgpt.com/backend-api/codex"


@dataclass
class CodexCredentials:
    """Resolved credentials for calling the OpenAI API."""
    api_key: str
    base_url: str
    headers: dict[str, str] = field(default_factory=dict)


def resolve_codex_credentials(
    *,
    auth_mode: str = "default",
    api_key: str = "",
) -> CodexCredentials:
    """Resolve an API key, base URL, and headers for the Codex/OpenAI backend.

    - ``default``: reads the OAuth access_token from
      ``~/.dataclaw/codex/auth.json`` (written by interactive login).
      Uses the ChatGPT backend Responses API with attribution headers.
    - ``api_key``: uses the provided key with the standard OpenAI API.
    """
    if auth_mode == "api_key":
        if not api_key:
            raise ValueError("Codex auth_mode is 'api_key' but no API key provided")
        return CodexCredentials(
            api_key=api_key,
            base_url="https://api.openai.com/v1",
        )

    if auth_mode == "default":
        token = _read_access_token()
        if not token:
            raise ValueError(
                "No Codex OAuth credentials found. Please log in first "
                "via the config page or POST /api/codex/login/start."
            )
        return CodexCredentials(
            api_key=token,
            base_url=CODEX_BASE_URL,
            headers={
                "User-Agent": "dataclaw/1.0",
                "originator": "dataclaw",
            },
        )

    raise ValueError(f"Unknown Codex auth_mode: {auth_mode!r}")


def prepare_codex_env() -> dict[str, str]:
    """Return env overrides for the Codex app-server (used by login manager)."""
    CODEX_HOME.mkdir(parents=True, exist_ok=True)
    return {"CODEX_HOME": str(CODEX_HOME)}


def _read_access_token() -> str | None:
    """Read the OAuth access_token from auth.json."""
    auth_path = CODEX_HOME / "auth.json"
    if not auth_path.exists():
        logger.warning("No auth.json at %s", auth_path)
        return None

    try:
        data = json.loads(auth_path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to read auth.json: %s", e)
        return None

    tokens = data.get("tokens", {})
    access = tokens.get("access_token", "")
    if not access:
        logger.warning("auth.json exists but access_token is empty")
        return None

    return access
