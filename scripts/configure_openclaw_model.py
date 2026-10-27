#!/usr/bin/env python3
"""Bundled-image bootstrap: configure OpenClaw's OpenRouter provider from env.

Runs from the entrypoint (before the gateway starts) when
``OPENROUTER_API_KEY`` or ``DATACLAW_OPENCLAW_MODEL`` is set. Uses the same
code path as ``POST /api/openclaw/model``
(:func:`dataclaw_openclaw.openrouter_config.bootstrap_from_env`):

- ``OPENROUTER_API_KEY`` is stored in OpenClaw's auth-profile store (piped on
  stdin to ``openclaw models auth paste-api-key``) only when OpenClaw has no
  OpenRouter credential yet — a key set later in the UI is never clobbered.
- ``DATACLAW_OPENCLAW_MODEL`` (e.g. ``openrouter/anthropic/claude-opus-5.5``)
  is applied as the primary model on every start. Without it, a fresh key
  with no primary model defaults to ``openrouter/auto``.

The key is never printed.
"""

from __future__ import annotations

import asyncio
import sys


async def main() -> int:
    from dataclaw_openclaw.openrouter_config import OpenClawCommandError, bootstrap_from_env

    try:
        for line in await bootstrap_from_env(["openclaw"]):
            print(f"[openrouter] {line}", flush=True)
    except OpenClawCommandError as exc:
        print(f"[openrouter] ERROR: {exc}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
