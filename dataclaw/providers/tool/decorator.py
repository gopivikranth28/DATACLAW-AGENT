"""Decorator for marking async functions as DataClaw tools.

Tool functions run in the FastAPI event loop. **Do not block** —
use async libraries (``httpx.AsyncClient``, ``aiofiles``) or wrap
sync calls in ``asyncio.to_thread`` so other chat sessions and
endpoints aren't frozen while your tool runs.

Usage in user tool files (e.g. ``~/.dataclaw/tools/my_tool.py``)::

    from dataclaw.tools import tool

    @tool(name="fetch_weather", description="Get current weather for a city")
    async def fetch_weather(city: str) -> dict:
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"https://wttr.in/{city}?format=j1")
        return {"content": resp.text}

    # For unavoidable sync calls:
    #   import asyncio, subprocess
    #   result = await asyncio.to_thread(subprocess.run, [...], capture_output=True)
"""

from __future__ import annotations

from typing import Any, Callable


def tool(
    name: str,
    description: str,
    parameters: dict[str, Any] | None = None,
) -> Callable:
    """Decorator to mark an async function as a DataClaw tool.

    Args:
        name: Tool name (used in agent tool calls).
        description: Human-readable description shown to the LLM.
        parameters: Optional JSON Schema for the tool's parameters.
                    If omitted, a schema is inferred from the function signature.
    """
    def wrapper(fn: Callable) -> Callable:
        fn._dataclaw_tool = {  # type: ignore[attr-defined]
            "name": name,
            "description": description,
            "parameters": parameters,
        }
        return fn
    return wrapper
