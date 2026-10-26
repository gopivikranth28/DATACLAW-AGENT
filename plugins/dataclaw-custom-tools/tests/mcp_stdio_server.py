"""Minimal stdio MCP server used by test_mcp_connector.py."""

from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, TextContent

server = MCPServer("dataclaw-test")


@server.tool()
def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


@server.tool()
def fail() -> CallToolResult:
    """Return a tool-level error."""
    return CallToolResult(content=[TextContent(type="text", text="nope")], is_error=True)


if __name__ == "__main__":
    server.run()
