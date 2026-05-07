"""MCP server connector — manages a connection to one MCP server.

Supports stdio (subprocess) and SSE (HTTP) transports.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from dataclaw.providers.tool.provider import ToolProvider

logger = logging.getLogger(__name__)


class MCPConnector:
    """Manages a connection to a single MCP server."""

    def __init__(
        self,
        name: str,
        transport: str,
        command: str = "",
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        url: str = "",
    ) -> None:
        self.name = name
        self.transport = transport
        self.command = command
        self.args = args or []
        self.env = env or {}
        self.url = url

        self._session: Any = None
        self._client: Any = None
        self._connected = False
        self._tools: list[ToolProvider] = []

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def tools(self) -> list[ToolProvider]:
        return list(self._tools)

    @property
    def tool_count(self) -> int:
        return len(self._tools)

    async def connect(self) -> list[ToolProvider]:
        """Connect to the MCP server and discover available tools."""
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client, StdioServerParameters
        from mcp.client.sse import sse_client

        try:
            if self.transport == "stdio":
                server_params = StdioServerParameters(
                    command=self.command,
                    args=self.args,
                    env={**self.env} if self.env else None,
                )
                self._client = stdio_client(server_params)
            elif self.transport == "sse":
                self._client = sse_client(self.url)
            else:
                raise ValueError(f"Unsupported transport: {self.transport}")

            # Enter the client context manager to get read/write streams
            streams = await self._client.__aenter__()
            read_stream, write_stream = streams

            # Create and initialize session
            self._session = ClientSession(read_stream, write_stream)
            await self._session.__aenter__()
            await self._session.initialize()

            # Discover tools
            self._tools = await self._discover_tools()
            self._connected = True
            logger.info(
                "Connected to MCP server %r (%s), discovered %d tool(s)",
                self.name, self.transport, len(self._tools),
            )
            return self._tools

        except Exception:
            logger.exception("Failed to connect to MCP server %r", self.name)
            self._connected = False
            self._tools = []
            raise

    async def disconnect(self) -> None:
        """Disconnect from the MCP server."""
        try:
            if self._session is not None:
                await self._session.__aexit__(None, None, None)
                self._session = None
            if self._client is not None:
                await self._client.__aexit__(None, None, None)
                self._client = None
        except Exception:
            logger.exception("Error disconnecting from MCP server %r", self.name)
        finally:
            self._connected = False
            self._tools = []

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute a tool on the MCP server."""
        if not self._connected or self._session is None:
            raise RuntimeError(f"Not connected to MCP server {self.name!r}")

        result = await self._session.call_tool(tool_name, arguments)

        # Convert MCP result to DataClaw format
        content_parts = []
        for item in result.content:
            if hasattr(item, "text"):
                content_parts.append(item.text)
            elif hasattr(item, "data"):
                content_parts.append(f"[binary: {item.mimeType or 'unknown'}]")
            else:
                content_parts.append(str(item))

        return {
            "content": "\n".join(content_parts),
            "is_error": result.isError or False,
        }

    async def _discover_tools(self) -> list[ToolProvider]:
        """Fetch the tool list from the MCP server and wrap as ToolProviders."""
        if self._session is None:
            return []

        result = await self._session.list_tools()
        tools: list[ToolProvider] = []

        for mcp_tool in result.tools:
            # Prefix tool name with server name to avoid collisions
            prefixed_name = f"mcp_{self.name}_{mcp_tool.name}"
            original_name = mcp_tool.name
            source = f"mcp:{self.name}"

            # Build JSON Schema from MCP tool schema
            parameters = mcp_tool.inputSchema or {
                "type": "object",
                "properties": {},
            }

            # Create a closure to capture the original tool name
            async def _execute(
                _original=original_name,
                _connector=self,
                **kwargs: Any,
            ) -> dict[str, Any]:
                return await _connector.call_tool(_original, kwargs)

            tool = ToolProvider(
                name=prefixed_name,
                description=mcp_tool.description or f"MCP tool: {mcp_tool.name}",
                parameters=parameters,
                fn=_execute,
                source=source,
            )
            tools.append(tool)

        return tools
