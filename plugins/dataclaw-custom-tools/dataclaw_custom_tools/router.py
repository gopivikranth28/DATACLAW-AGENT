"""API routes for custom tool and MCP server management."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from dataclaw.config.paths import tools_dir, mcp_servers_path
from dataclaw.providers.tool.implementations.custom_loader import load_custom_tools

router = APIRouter()


# ── Custom Python tools ──────────────────────────────────────────────────────

@router.get("/custom")
async def list_custom_tools(request: Request) -> list[dict[str, Any]]:
    """List custom tool files with metadata."""
    tdir = tools_dir()
    if not tdir.is_dir():
        return []

    results = []
    for py_file in sorted(tdir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        results.append({
            "file": py_file.name,
            "path": str(py_file),
        })
    return results


class CreateToolBody(BaseModel):
    filename: str
    code: str


@router.post("/custom")
async def create_custom_tool(body: CreateToolBody, request: Request) -> dict[str, Any]:
    """Create a new custom tool file."""
    tdir = tools_dir()
    tdir.mkdir(parents=True, exist_ok=True)

    filename = body.filename
    if not filename.endswith(".py"):
        filename += ".py"

    path = tdir / filename
    if path.exists():
        raise HTTPException(409, f"Tool file already exists: {filename}")

    path.write_text(body.code)

    # Reload and register new tools
    _reload_custom_tools(request)

    return {"file": filename, "path": str(path)}


@router.delete("/custom/{filename}")
async def delete_custom_tool(filename: str, request: Request) -> dict[str, str]:
    """Delete a custom tool file and unregister its tools."""
    tdir = tools_dir()
    path = tdir / filename
    if not path.exists():
        raise HTTPException(404, f"Tool file not found: {filename}")

    # Find tool names from this file before deleting
    from dataclaw.providers.tool.implementations.custom_loader import _load_module, _extract_tools
    module = _load_module(path)
    if module:
        tools = _extract_tools(module, path)
        registry = request.app.state.providers.tool_availability
        for tool in tools:
            registry.unregister_tool(tool.name)

    path.unlink()
    return {"deleted": filename}


@router.post("/custom/reload")
async def reload_custom_tools(request: Request) -> dict[str, Any]:
    """Hot-reload all custom tools from the tools directory."""
    tools = _reload_custom_tools(request)
    return {"reloaded": len(tools), "tools": [t.name for t in tools]}


def _reload_custom_tools(request: Request) -> list:
    """Unregister existing custom tools and re-load from disk."""
    registry = request.app.state.providers.tool_availability

    # Remove existing custom tools
    to_remove = [
        name for name, t in registry._tools.items()
        if t.source == "custom"
    ]
    for name in to_remove:
        registry.unregister_tool(name)

    # Load fresh from disk
    tools = load_custom_tools(tools_dir())
    for tool in tools:
        registry.register_tool(tool)
    return tools


# ── MCP Servers ──────────────────────────────────────────────────────────────


def _get_mcp_registry(request: Request):
    """Retrieve the MCPRegistry from app state."""
    reg = getattr(request.app.state, "mcp_registry", None)
    if reg is None:
        raise HTTPException(503, "MCP registry not initialized")
    return reg


@router.get("/mcp/servers")
async def list_mcp_servers(request: Request) -> list[dict[str, Any]]:
    """List configured MCP servers with connection status."""
    return _get_mcp_registry(request).list_servers()


class AddMCPServerBody(BaseModel):
    name: str
    transport: str  # "stdio" | "sse"
    command: str = ""
    args: list[str] = []
    env: dict[str, str] = {}
    url: str = ""
    enabled: bool = True


@router.post("/mcp/servers")
async def add_mcp_server(body: AddMCPServerBody, request: Request) -> dict[str, Any]:
    """Add a new MCP server, connect, and discover tools."""
    from dataclaw_custom_tools.mcp_registry import MCPServerConfig

    config = MCPServerConfig(
        name=body.name,
        transport=body.transport,
        command=body.command,
        args=body.args or [],
        env=body.env or {},
        url=body.url,
        enabled=body.enabled,
    )
    reg = _get_mcp_registry(request)
    try:
        connector = await reg.add_server(config)
        return {
            "name": body.name,
            "connected": connector.connected,
            "tool_count": connector.tool_count,
            "tools": [t.name for t in connector.tools],
        }
    except Exception as e:
        raise HTTPException(500, f"Failed to connect: {e}")


class UpdateMCPServerBody(BaseModel):
    transport: str | None = None
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    url: str | None = None
    enabled: bool | None = None


@router.put("/mcp/servers/{name}")
async def update_mcp_server(
    name: str, body: UpdateMCPServerBody, request: Request,
) -> dict[str, Any]:
    """Update an MCP server config and reconnect."""
    from dataclaw_custom_tools.mcp_registry import MCPServerConfig

    reg = _get_mcp_registry(request)
    existing = reg._configs.get(name)
    if existing is None:
        raise HTTPException(404, f"Unknown MCP server: {name}")

    config = MCPServerConfig(
        name=name,
        transport=body.transport if body.transport is not None else existing.transport,
        command=body.command if body.command is not None else existing.command,
        args=body.args if body.args is not None else existing.args,
        env=body.env if body.env is not None else existing.env,
        url=body.url if body.url is not None else existing.url,
        enabled=body.enabled if body.enabled is not None else existing.enabled,
    )
    try:
        connector = await reg.add_server(config)
        return {
            "name": name,
            "connected": connector.connected,
            "tool_count": connector.tool_count,
        }
    except Exception as e:
        raise HTTPException(500, f"Failed to reconnect: {e}")


@router.delete("/mcp/servers/{name}")
async def remove_mcp_server(name: str, request: Request) -> dict[str, str]:
    """Disconnect and remove an MCP server."""
    reg = _get_mcp_registry(request)
    if name not in reg._configs:
        raise HTTPException(404, f"Unknown MCP server: {name}")
    await reg.remove_server(name)
    return {"removed": name}


@router.post("/mcp/servers/{name}/reconnect")
async def reconnect_mcp_server(name: str, request: Request) -> dict[str, Any]:
    """Force reconnect to an MCP server."""
    reg = _get_mcp_registry(request)
    try:
        connector = await reg.reconnect_server(name)
        return {
            "name": name,
            "connected": connector.connected,
            "tool_count": connector.tool_count,
            "tools": [t.name for t in connector.tools],
        }
    except Exception as e:
        raise HTTPException(500, f"Failed to reconnect: {e}")
