"""Load user-defined tools from Python files in the tools directory.

Scans ``~/.dataclaw/tools/*.py`` for functions decorated with
``@dataclaw.tools.tool`` and wraps each as a ``PythonTool``.
"""

from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from dataclaw.providers.tool.implementations.python_tool import PythonTool

logger = logging.getLogger(__name__)


def _load_module(path: Path) -> ModuleType | None:
    """Import a single .py file into its own module namespace."""
    module_name = f"dataclaw_custom_tool_{path.stem}"
    try:
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            logger.warning("Cannot create module spec for %s", path)
            return None
        module = importlib.util.module_from_spec(spec)
        # Make dataclaw importable inside the tool file
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module
    except Exception:
        logger.exception("Failed to load custom tool from %s", path)
        return None


def _extract_tools(module: ModuleType, file_path: Path) -> list[PythonTool]:
    """Find all @tool-decorated functions in a module and wrap as PythonTools."""
    tools: list[PythonTool] = []
    for attr_name in dir(module):
        obj = getattr(module, attr_name)
        meta: dict[str, Any] | None = getattr(obj, "_dataclaw_tool", None)
        if meta is None or not callable(obj):
            continue
        try:
            tool = PythonTool(
                name=meta["name"],
                description=meta["description"],
                fn=obj,
                parameters=meta.get("parameters"),
                source="custom",
            )
            tools.append(tool)
            logger.info("Loaded custom tool %r from %s", meta["name"], file_path)
        except Exception:
            logger.exception(
                "Failed to wrap tool %r from %s", meta.get("name"), file_path
            )
    return tools


def load_custom_tools(tools_dir: Path) -> list[PythonTool]:
    """Scan a directory for .py files and load all @tool-decorated functions."""
    if not tools_dir.is_dir():
        return []

    all_tools: list[PythonTool] = []
    for py_file in sorted(tools_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        module = _load_module(py_file)
        if module is not None:
            all_tools.extend(_extract_tools(module, py_file))

    logger.info("Loaded %d custom tool(s) from %s", len(all_tools), tools_dir)
    return all_tools
