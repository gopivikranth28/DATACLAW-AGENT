"""PythonTool — wraps an async Python function as a ToolProvider."""

from __future__ import annotations

import inspect
from typing import Any, Callable, Awaitable

from dataclaw.providers.tool.provider import ToolProvider


class PythonTool(ToolProvider):
    """Wraps an async Python function as a dataclaw tool.

    If no parameters schema is provided, one is inferred from the
    function signature (all params as strings, no validation).
    """

    def __init__(
        self,
        name: str,
        description: str,
        fn: Callable[..., Awaitable[dict[str, Any]]],
        parameters: dict[str, Any] | None = None,
    ) -> None:
        if parameters is None:
            parameters = self._infer_parameters(fn)
        super().__init__(name=name, description=description, parameters=parameters, fn=fn)

    @staticmethod
    def _infer_parameters(fn: Callable[..., Any]) -> dict[str, Any]:
        """Infer a basic JSON Schema from function signature."""
        sig = inspect.signature(fn)
        properties: dict[str, Any] = {}
        required: list[str] = []
        for param_name, param in sig.parameters.items():
            if param_name in ("self", "cls"):
                continue
            properties[param_name] = {"type": "string"}
            if param.default is inspect.Parameter.empty:
                required.append(param_name)
        return {
            "type": "object",
            "properties": properties,
            "required": required,
        }
