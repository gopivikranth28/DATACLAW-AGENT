#!/usr/bin/env python3
"""Synchronize the local Dataclaw OpenClaw plugin through its governed flow.

Run this instead of calling ``openclaw plugins install`` directly.  The
OpenClaw CLI only installs the files already on disk; it cannot refresh
Dataclaw's generated tool schema.  This command mirrors the Config UI's
``POST /api/openclaw/plugins/dataclaw/install`` path: it snapshots the live
tool registry, validates the governed report transaction, regenerates the
TypeScript manifest and tool contracts, builds the plugin, and then installs
it through OpenClaw.

It deliberately reads the user's existing Dataclaw OpenClaw configuration and
does not print its token.
"""

from __future__ import annotations

import asyncio
import json
import shlex
from pathlib import Path
from typing import Any

from dataclaw.config.paths import config_path
from dataclaw_openclaw.openclaw_install_service import install_plugin_atomic
from scripts.install_dataclaw_plugin import bootstrap_tool_registry


PLUGIN_ID = "dataclaw"
DEFAULT_PLUGIN_SOURCE_ROOT = Path(__file__).resolve().parents[1] / "openclaw-plugins"


def _openclaw_config() -> dict[str, Any]:
    """Read only the configured OpenClaw plugin block, with safe defaults."""
    path = config_path()
    try:
        document = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, json.JSONDecodeError):
        document = {}
    plugins = document.get("plugins") if isinstance(document, dict) else {}
    configured = plugins.get("openclaw") if isinstance(plugins, dict) else {}
    return dict(configured) if isinstance(configured, dict) else {}


async def _sync() -> int:
    cfg = _openclaw_config()
    source_root = Path(cfg.get("plugins_source_dir") or DEFAULT_PLUGIN_SOURCE_ROOT).expanduser()
    plugin_dir = source_root / PLUGIN_ID
    openclaw_root = str(cfg.get("openclaw_plugins_dir") or "").strip()
    install_dir = Path(openclaw_root).expanduser() / PLUGIN_ID if openclaw_root else plugin_dir
    argv = shlex.split(str(cfg.get("openclaw_cmd") or "openclaw"))

    tools = bootstrap_tool_registry()
    print(f"Discovered {len(tools)} live Dataclaw tools; synchronizing {PLUGIN_ID}.")
    exit_code = 0
    async for event in install_plugin_atomic(
        plugin_dir=plugin_dir,
        openclaw_cfg=cfg,
        argv=argv,
        also_allow_addition=PLUGIN_ID,
        tools=tools,
        install_dir=install_dir,
    ):
        if "line" in event:
            print(event["line"])
        if "error" in event:
            print(f"ERROR: {event['error']}")
            exit_code = int(event.get("exit_code") or 1)
        if "exit_code" in event:
            exit_code = int(event["exit_code"])
    return exit_code


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_sync()))
