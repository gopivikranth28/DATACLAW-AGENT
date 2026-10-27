"""The token shared between Dataclaw and the OpenClaw ``dataclaw`` plugin.

It is sent in ``X-Dataclaw-Token`` in both directions: Dataclaw → OpenClaw
(``/dataclaw/message``) and OpenClaw → Dataclaw (tool calls and the persist
callback). OpenClaw's calls into Dataclaw must pass API authentication, so
whenever authentication is enforced the shared token *is* the API token.
"""

from __future__ import annotations

import os
from typing import Any

from dataclaw.api import security


def resolve_shared_token(openclaw_cfg: dict[str, Any] | None = None) -> str:
    if security.token_required():
        return security.api_token()
    if openclaw_cfg is None:
        from dataclaw.config.resolver import resolve

        openclaw_cfg = {
            "token": resolve("plugins.openclaw.token", "", ""),
            "frontend_token": resolve("plugins.openclaw.frontend_token", "", ""),
        }
    # Without enforced auth, keep honouring an explicitly configured value so
    # existing OpenClaw installs keep matching until they are reinstalled.
    explicit = (
        os.environ.get("DATACLAW_TOKEN")
        or openclaw_cfg.get("token")
        or openclaw_cfg.get("frontend_token")
    )
    return str(explicit or security.api_token()).strip()
