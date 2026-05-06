"""MCP server registry — manages multiple MCP server connections."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dataclaw.config.paths import mcp_servers_path
from dataclaw.providers.tool.implementations.registry import DefaultToolAvailability

from dataclaw_custom_tools.mcp_connector import MCPConnector

logger = logging.getLogger(__name__)


@dataclass
class MCPServerConfig:
    """Configuration for a single MCP server."""
    name: str
    transport: str  # "stdio" | "sse"
    command: str = ""
    args: list[str] | None = None
    env: dict[str, str] | None = None
    url: str = ""
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "transport": self.transport,
            "enabled": self.enabled,
        }
        if self.transport == "stdio":
            d["command"] = self.command
            if self.args:
                d["args"] = self.args
            if self.env:
                d["env"] = self.env
        elif self.transport == "sse":
            d["url"] = self.url
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> MCPServerConfig:
        return cls(
            name=d["name"],
            transport=d["transport"],
            command=d.get("command", ""),
            args=d.get("args"),
            env=d.get("env"),
            url=d.get("url", ""),
            enabled=d.get("enabled", True),
        )


class MCPRegistry:
    """Manages multiple MCP server connections and their tool registration."""

    def __init__(self, tool_registry: DefaultToolAvailability) -> None:
        self._tool_registry = tool_registry
        self._connectors: dict[str, MCPConnector] = {}
        self._configs: dict[str, MCPServerConfig] = {}
        self._loaded = False  # True after load_and_connect runs

    @property
    def servers(self) -> dict[str, MCPConnector]:
        return dict(self._connectors)

    async def add_server(self, config: MCPServerConfig) -> MCPConnector:
        """Add, connect, and register tools from an MCP server."""
        if config.name in self._connectors:
            await self.remove_server(config.name)

        connector = MCPConnector(
            name=config.name,
            transport=config.transport,
            command=config.command,
            args=config.args,
            env=config.env,
            url=config.url,
        )

        self._configs[config.name] = config

        if config.enabled:
            tools = await connector.connect()
            for tool in tools:
                self._tool_registry.register_tool(tool)

        self._connectors[config.name] = connector
        self._save_config()
        return connector

    async def remove_server(self, name: str) -> None:
        """Disconnect and remove an MCP server."""
        connector = self._connectors.pop(name, None)
        self._configs.pop(name, None)

        if connector is not None:
            # Unregister its tools
            for tool in connector.tools:
                self._tool_registry.unregister_tool(tool.name)
            await connector.disconnect()

        self._save_config()

    async def reconnect_server(self, name: str) -> MCPConnector:
        """Force reconnect to an MCP server."""
        config = self._configs.get(name)
        if config is None:
            raise ValueError(f"Unknown MCP server: {name}")

        connector = self._connectors.get(name)
        if connector is not None:
            for tool in connector.tools:
                self._tool_registry.unregister_tool(tool.name)
            await connector.disconnect()

        connector = MCPConnector(
            name=config.name,
            transport=config.transport,
            command=config.command,
            args=config.args,
            env=config.env,
            url=config.url,
        )
        tools = await connector.connect()
        for tool in tools:
            self._tool_registry.register_tool(tool)

        self._connectors[name] = connector
        return connector

    def list_servers(self) -> list[dict[str, Any]]:
        """Return status info for all configured servers."""
        results = []
        for name, config in self._configs.items():
            connector = self._connectors.get(name)
            results.append({
                "name": name,
                "transport": config.transport,
                "enabled": config.enabled,
                "connected": connector.connected if connector else False,
                "tool_count": connector.tool_count if connector else 0,
                "tools": [t.name for t in connector.tools] if connector else [],
            })
        return results

    async def load_and_connect(self) -> None:
        """Load server configs from disk and connect to enabled servers."""
        path = mcp_servers_path()
        if not path.exists():
            self._loaded = True
            return

        try:
            data = json.loads(path.read_text())
            for entry in data:
                config = MCPServerConfig.from_dict(entry)
                try:
                    await self.add_server(config)
                except Exception:
                    logger.exception("Failed to connect MCP server %r", config.name)
        except Exception:
            logger.exception("Failed to load MCP server configs from %s", path)
        self._loaded = True

    async def shutdown(self) -> None:
        """Disconnect all servers."""
        for name in list(self._connectors):
            try:
                connector = self._connectors[name]
                for tool in connector.tools:
                    self._tool_registry.unregister_tool(tool.name)
                await connector.disconnect()
            except Exception:
                logger.exception("Error shutting down MCP server %r", name)
        self._connectors.clear()

    def _save_config(self) -> None:
        """Persist server configs to disk.

        Skips writing if load_and_connect hasn't run yet, to avoid
        overwriting the config file with an empty or partial list.
        """
        if not self._loaded:
            return
        path = mcp_servers_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        data = [config.to_dict() for config in self._configs.values()]
        path.write_text(json.dumps(data, indent=2) + "\n")
