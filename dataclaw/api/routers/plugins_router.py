"""Plugins router — list installed plugins with UI manifests.

Returns plugin metadata that the frontend uses to:
- Conditionally render nav items and routes for plugin pages
- Render dynamic config sections on the ConfigPage
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("")
async def list_plugins(request: Request) -> list[dict[str, Any]]:
    """List installed plugins with their UI manifests."""
    plugins = getattr(request.app.state, "plugins_list", [])
    result = []
    for plugin in plugins:
        manifest = None
        if hasattr(plugin, "ui_manifest"):
            try:
                m = plugin.ui_manifest()
                if m is not None:
                    manifest = m.to_dict()
            except Exception:
                pass

        result.append({
            "name": plugin.name,
            "depends_on": getattr(plugin, "depends_on", []),
            **(manifest or {"id": plugin.name, "label": plugin.name, "icon": "", "pages": [], "config_schema": None}),
        })
    return result
