"""MCPConnector against a real stdio MCP server (installed mcp SDK)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from dataclaw_custom_tools.mcp_connector import MCPConnector

SERVER = Path(__file__).with_name("mcp_stdio_server.py")


@pytest.mark.asyncio
async def test_stdio_round_trip_discovers_and_calls_tools():
    connector = MCPConnector("t", "stdio", command=sys.executable, args=[str(SERVER)])
    try:
        tools = {t.definition["name"]: t.definition for t in await connector.connect()}
        assert set(tools) == {"mcp_t_add", "mcp_t_fail"}
        assert tools["mcp_t_add"]["parameters"]["properties"].keys() == {"a", "b"}
        assert tools["mcp_t_add"]["description"] == "Add two integers."

        assert await connector.call_tool("add", {"a": 2, "b": 3}) == {"content": "5", "is_error": False}
        assert await connector.call_tool("fail", {}) == {"content": "nope", "is_error": True}
    finally:
        await connector.disconnect()
    assert not connector.connected
