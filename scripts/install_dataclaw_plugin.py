#!/usr/bin/env python3
"""Bundled-image bootstrap: install the dataclaw plugin via the canonical
``install_plugin_atomic`` flow — the same code path the UI's Install button
runs via ``POST /api/openclaw/plugins/dataclaw/install``.

Calling the canonical function (instead of replicating the steps in bash)
keeps the bundled image's bootstrap behaviorally identical to the UI flow:

- Regenerate ``tool-manifest.generated.ts`` and ``openclaw.plugin.json
  contracts.tools`` from the live in-process tool registry. The committed
  ``tool-manifest.ts`` is just a re-export of the generated file (which is
  gitignored), so without this step the bundled image's plugin would load
  with zero tools registered.
- Clear orphan ``channels.<id>`` left behind by a prior failed install.
- ``npm run build``.
- ``openclaw plugins install <dir> --force``.
- Wait for gateway restart.
- Atomic batch config write: ``channels.<id>.*``,
  ``plugins.entries.<id>.config.*``, the right tool-allowlist field
  (``tools.alsoAllow`` when ``tools.profile`` is set, ``tools.allow``
  otherwise), ``plugins.entries.<id>.enabled``, and ``plugins.allow`` —
  each entry written only when it would actually change a value, with
  additive merges that preserve user customizations.

To populate the live tool registry without spinning up the FastAPI app,
``bootstrap_tool_registry`` runs the same provider-init + plugin-discovery
sequence ``dataclaw.api.app`` does at startup, then snapshots
``get_all_tools_with_status()`` for hand-off to ``install_plugin_atomic``.

Reads connection settings from environment so the entrypoint can pass
through DATACLAW_TOKEN / DATACLAW_API_URL / OPENCLAW_GATEWAY_PORT.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

PLUGIN_ID = "dataclaw"
PLUGIN_DIR = Path("/dataclaw/openclaw-plugins") / PLUGIN_ID


def bootstrap_tool_registry() -> list[dict]:
    """Mirror dataclaw.api.app's startup sequence just far enough to populate
    the tool registry, then return the snapshot.

    Plugins register their tools through ``ctx.tool_registry``; some also
    call ``ctx.include_api_router`` which goes through the FastAPI app.
    We hand them a real but otherwise unused ``FastAPI()`` so router
    registration is a harmless no-op (the app is discarded after).
    """
    from fastapi import FastAPI

    from dataclaw.api.deps import init_providers
    from dataclaw.config.schema import DataclawConfig
    from dataclaw.guardrails.registry import GuardrailRegistry
    from dataclaw.hooks.registry import HookRegistry
    from dataclaw.plugins.base import PluginContext
    from dataclaw.plugins.loader import discover_plugins
    from dataclaw.plugins.registry import ProviderRegistry

    registry = ProviderRegistry()
    hooks = HookRegistry()
    tool_registry = init_providers(registry)

    ctx = PluginContext(
        hooks=hooks,
        providers=registry,
        app=FastAPI(),
        config=DataclawConfig(),
        tool_registry=tool_registry,
        guardrail_registry=GuardrailRegistry(),
    )

    for plugin in discover_plugins():
        try:
            plugin.register(ctx)
        except Exception as exc:
            print(
                f"[install] warning: plugin {plugin.name!r} failed to register: {exc}",
                flush=True,
            )

    return tool_registry.get_all_tools_with_status()


async def main() -> int:
    from dataclaw_openclaw import openclaw_install_service

    # The bundled entrypoint runs this BEFORE starting the gateway — there's no
    # /healthz endpoint to poll. install_plugin_atomic calls _wait_for_gateway
    # twice (after `plugins install` and after the post-install batch config
    # set) to let an already-running gateway re-load on its own time. With no
    # gateway up, we replace those waits with a no-op so the bootstrap doesn't
    # stall for ~30s per call.
    async def _no_wait(_url: str):
        if False:
            yield {}

    openclaw_install_service._wait_for_gateway = _no_wait  # type: ignore[assignment]

    gateway_port = os.environ.get("OPENCLAW_GATEWAY_PORT", "18789")
    cfg = {
        "token": os.environ.get("DATACLAW_TOKEN", "dataclaw-local"),
        "tools_api_url": os.environ.get(
            "DATACLAW_API_URL",
            f"http://127.0.0.1:{os.environ.get('DATACLAW_PORT', '8000')}",
        ),
        "url": os.environ.get(
            "OPENCLAW_GATEWAY_URL", f"http://127.0.0.1:{gateway_port}"
        ),
        "tools_prefix": "dataclaw_",
        "tools_optional": False,
    }

    print("[install] bootstrapping tool registry...", flush=True)
    try:
        tools = bootstrap_tool_registry()
        print(f"[install] discovered {len(tools)} tools", flush=True)
    except Exception as exc:
        print(
            f"[install] WARNING: tool registry bootstrap failed ({exc}); "
            "falling back to existing on-disk manifest",
            file=sys.stderr,
            flush=True,
        )
        tools = None

    exit_code = 0
    async for event in openclaw_install_service.install_plugin_atomic(
        plugin_dir=PLUGIN_DIR,
        openclaw_cfg=cfg,
        argv=["openclaw"],
        also_allow_addition=PLUGIN_ID,
        tools=tools,
        install_dir=PLUGIN_DIR,
    ):
        if "error" in event:
            print(f"[install] ERROR: {event['error']}", file=sys.stderr, flush=True)
            exit_code = int(event.get("exit_code") or 1)
        elif "line" in event:
            print(f"[install] {event['line']}", flush=True)
        elif "exit_code" in event:
            exit_code = int(event["exit_code"])
    return exit_code


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
