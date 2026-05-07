"""DataClaw Custom Tools Plugin.

Provides:
- User-defined Python tools loaded from ~/.dataclaw/tools/
- MCP server connections as tool sources
- API routes for custom tool and MCP server management
"""

from __future__ import annotations

import asyncio
import logging

from dataclaw.config.paths import tools_dir
from dataclaw.plugins.base import (
    DataclawPlugin,
    PluginContext,
    PluginPage,
    PluginUIManifest,
)
from dataclaw.providers.tool.implementations.custom_loader import load_custom_tools

logger = logging.getLogger(__name__)


class CustomToolsPlugin:
    name = "dataclaw-custom-tools"
    depends_on: list[str] = []

    def register(self, ctx: PluginContext) -> None:
        # Load user-defined Python tools
        custom_tools = load_custom_tools(tools_dir())
        for tool in custom_tools:
            ctx.tool_registry.register_tool(tool)

        # Set up MCP registry and store on app state for router access
        from dataclaw_custom_tools.mcp_registry import MCPRegistry
        mcp_registry = MCPRegistry(ctx.tool_registry)
        ctx.app.state.mcp_registry = mcp_registry

        # Register API routes for custom tool + MCP management
        from dataclaw_custom_tools.router import router as custom_router
        ctx.include_api_router(custom_router, prefix="/tools", tags=["custom-tools"])

        # Schedule MCP server connections after startup
        @ctx.app.on_event("startup")
        async def _connect_mcp_servers():
            try:
                await mcp_registry.load_and_connect()
            except Exception:
                logger.exception("Failed to initialize MCP servers")

        @ctx.app.on_event("shutdown")
        async def _shutdown_mcp_servers():
            try:
                await mcp_registry.shutdown()
            except Exception:
                logger.exception("Error shutting down MCP servers")

        self._ctx = ctx

    def ui_manifest(self) -> PluginUIManifest:
        return PluginUIManifest(
            id="custom-tools",
            label="Tools",
            icon="tool",
            pages=[PluginPage(path="/tools", label="Tools")],
        )
