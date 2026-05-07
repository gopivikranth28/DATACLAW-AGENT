"""Public API for user-defined tools.

Users import from here in their custom tool files::

    from dataclaw.tools import tool

    @tool(name="my_tool", description="Does something useful")
    async def my_tool(arg: str) -> dict:
        return {"content": f"Result: {arg}"}
"""

from dataclaw.providers.tool.decorator import tool  # noqa: F401
