"""Default tool availability provider — registry-based resolver."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Awaitable

from dataclaw.state import AgentState
from dataclaw.providers.tool.provider import ToolProvider
from dataclaw.providers.tool.tool_config import (
    ToolConfig,
    ProjectToolConfig,
    is_tool_enabled,
    load_global_tool_config,
    save_global_tool_config,
    load_project_tool_config,
    save_project_tool_config,
    bump_version,
)
from dataclaw.schema import ToolDefinition

logger = logging.getLogger(__name__)


def _load_session_data(session_id: str) -> dict[str, Any] | None:
    """Load session JSON data synchronously (for use in resolve_tools)."""
    if not session_id:
        return None
    try:
        import json
        from dataclaw.config.paths import sessions_dir
        path = sessions_dir() / f"{session_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text())
    except Exception:
        return None


def _resolve_project_dir(project_id: str) -> Path | None:
    """Look up the filesystem directory for a project. Returns None on failure."""
    try:
        from dataclaw_projects.registry import get_project
        project = get_project(project_id)
        directory = project.get("directory")
        if directory:
            return Path(directory)
    except Exception:
        pass
    return None


class DefaultToolAvailability:
    """Resolves tools from a registry of ToolProvider instances.

    Supports enable/disable filtering at global and project level,
    and a monotonic version counter for change detection (OpenClaw polling).
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolProvider] = {}
        self._tool_config: ToolConfig = load_global_tool_config()

    @property
    def version(self) -> int:
        return self._tool_config.version

    def register_tool(self, tool: ToolProvider) -> None:
        """Register a tool provider and bump version."""
        self._tools[tool.name] = tool
        self._bump()

    def unregister_tool(self, name: str) -> None:
        """Remove a tool by name and bump version."""
        if self._tools.pop(name, None) is not None:
            self._bump()

    def has_tool(self, name: str) -> bool:
        """Return True if a tool with this name is registered.

        Independent of session/project enable state — use this to distinguish
        "tool exists but is disabled for the active session" from "no such
        tool was ever registered" when surfacing API errors.
        """
        return name in self._tools

    def seed_plugin_defaults(
        self, plugin_id: str, default_disabled: list[str] | tuple[str, ...]
    ) -> None:
        """Apply a plugin's default-disabled tool list — once per install.

        Called from a plugin's ``register()`` after its tools are registered.
        On the first call for a given ``plugin_id`` (i.e. when the id isn't
        yet in ``_tool_config.seeded_plugins``), every name in
        ``default_disabled`` is added to the global disabled set and the
        plugin id is recorded as seeded. Subsequent calls are no-ops, so
        the user's later explicit enables (via the Tools page UI) are not
        clobbered when the plugin loads again.
        """
        plugin_id = (plugin_id or "").strip()
        if not plugin_id:
            return
        if plugin_id in self._tool_config.seeded_plugins:
            return
        added = False
        for name in default_disabled:
            if not name:
                continue
            if name not in self._tool_config.disabled:
                self._tool_config.disabled.add(name)
                added = True
        self._tool_config.seeded_plugins.add(plugin_id)
        # Persist via _bump so the version counter advances and any UI poll
        # sees the change (same path register_tool already uses).
        if added:
            self._bump()
        else:
            # Still need to persist seeded_plugins so we don't re-seed on
            # next start, even when nothing newly went into `disabled`
            # (e.g., user already manually disabled them all).
            save_global_tool_config(self._tool_config)

    def set_tool_enabled(
        self,
        name: str,
        enabled: bool,
        project_id: str | None = None,
    ) -> None:
        """Enable or disable a tool at global or project level."""
        if project_id:
            project_dir = _resolve_project_dir(project_id)
            if project_dir is None:
                raise ValueError(f"Unknown project: {project_id}")
            cfg = load_project_tool_config(project_dir) or ProjectToolConfig()
            if enabled:
                cfg.disabled.discard(name)
                cfg.enabled.add(name)
            else:
                cfg.enabled.discard(name)
                cfg.disabled.add(name)
            save_project_tool_config(project_dir, cfg)
        else:
            if enabled:
                self._tool_config.disabled.discard(name)
            else:
                self._tool_config.disabled.add(name)
            save_global_tool_config(self._tool_config)
        self._bump()

    def get_all_tools_with_status(
        self,
        project_id: str | None = None,
        session_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return all tools with their enabled status (for the tools listing API)."""
        project_config = None
        if project_id:
            project_dir = _resolve_project_dir(project_id)
            if project_dir:
                project_config = load_project_tool_config(project_dir)

        session_config = _load_session_tool_config(session_id) if session_id else None

        result = []
        for tool in self._tools.values():
            d = dict(tool.definition)
            d["enabled"] = is_tool_enabled(
                tool.name, self._tool_config, project_config, session_config,
            )
            result.append(d)
        return result

    async def resolve_tools(
        self,
        state: AgentState,
    ) -> tuple[list[ToolDefinition], dict[str, Callable[..., Awaitable[dict[str, Any]]]]]:
        """Return enabled tools for this turn.

        Filtering layers (highest priority first):
        1. Session ``toolIds`` allowlist (from session JSON)
        2. Project ``tool_ids`` allowlist (from project metadata)
        3. Global disabled list (from tool-config.json)
        """
        # Load session data for toolIds allowlist
        allowed_ids: list[str] | None = None
        session_id = state.get("session_id")
        if session_id:
            session_data = _load_session_data(session_id)
            if session_data:
                session_tool_ids = session_data.get("toolIds")
                if session_tool_ids is not None:
                    allowed_ids = session_tool_ids

        # Fall back to project-level allowlist
        if allowed_ids is None:
            project_id = state.get("project_id")
            if project_id:
                try:
                    from dataclaw_projects.registry import get_project
                    proj = get_project(project_id)
                    project_tool_ids = proj.get("tool_ids")
                    if project_tool_ids is not None:
                        allowed_ids = project_tool_ids
                except Exception:
                    pass

        definitions: list[ToolDefinition] = []
        callables: dict[str, Callable[..., Awaitable[dict[str, Any]]]] = {}
        for name, tool in self._tools.items():
            # If an allowlist is active, tool must be in it
            if allowed_ids is not None and name not in allowed_ids:
                continue
            # Also respect global disabled list
            if name in self._tool_config.disabled:
                continue
            definitions.append(tool.definition)
            callables[name] = tool.execute
        return definitions, callables

    def _bump(self) -> None:
        """Increment version counter and persist config."""
        self._tool_config = bump_version(self._tool_config)
