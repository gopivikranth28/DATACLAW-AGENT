"""Tool enable/disable configuration persistence.

Global config lives at ~/.dataclaw/tool-config.json.
Project-level overrides live at {project_dir}/.dataclaw/tool-config.json.
Session-level overrides live on the session JSON object (``toolConfig`` key).

Resolution order (highest wins):
    session > project > global > default (enabled).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from dataclaw.config.paths import tool_config_path

logger = logging.getLogger(__name__)


@dataclass
class ToolConfig:
    """Global tool configuration."""
    disabled: set[str] = field(default_factory=set)
    version: int = 1
    # Plugin ids whose default-disabled tool list has been seeded into
    # `disabled` already. Used so that a plugin can opt individual tools
    # into "off by default" once, without overriding the user's later
    # explicit enables. Once a plugin id is in this set, the corresponding
    # `seed_plugin_defaults()` call is a no-op.
    seeded_plugins: set[str] = field(default_factory=set)


@dataclass
class ProjectToolConfig:
    """Project-level tool overrides."""
    disabled: set[str] = field(default_factory=set)
    enabled: set[str] = field(default_factory=set)


@dataclass
class SessionToolConfig:
    """Session-level (chat-level) tool overrides."""
    disabled: set[str] = field(default_factory=set)
    enabled: set[str] = field(default_factory=set)


def session_tool_config_from_dict(data: dict | None) -> SessionToolConfig | None:
    """Parse a session's ``toolConfig`` dict into a SessionToolConfig."""
    if not data:
        return None
    return SessionToolConfig(
        disabled=set(data.get("disabled", [])),
        enabled=set(data.get("enabled", [])),
    )


def session_tool_config_to_dict(config: SessionToolConfig) -> dict:
    """Serialize a SessionToolConfig to a plain dict for session JSON storage."""
    return {
        "disabled": sorted(config.disabled),
        "enabled": sorted(config.enabled),
    }


def load_global_tool_config() -> ToolConfig:
    path = tool_config_path()
    if not path.exists():
        return ToolConfig()
    try:
        data = json.loads(path.read_text())
        return ToolConfig(
            disabled=set(data.get("disabled", [])),
            version=data.get("version", 1),
            seeded_plugins=set(data.get("seeded_plugins", [])),
        )
    except Exception:
        logger.warning("Failed to read tool config at %s, using defaults", path)
        return ToolConfig()


def save_global_tool_config(config: ToolConfig) -> None:
    path = tool_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "disabled": sorted(config.disabled),
        "version": config.version,
        "seeded_plugins": sorted(config.seeded_plugins),
    }, indent=2) + "\n")


def load_project_tool_config(project_dir: Path) -> ProjectToolConfig | None:
    path = project_dir / ".dataclaw" / "tool-config.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return ProjectToolConfig(
            disabled=set(data.get("disabled", [])),
            enabled=set(data.get("enabled", [])),
        )
    except Exception:
        logger.warning("Failed to read project tool config at %s", path)
        return None


def save_project_tool_config(project_dir: Path, config: ProjectToolConfig) -> None:
    path = project_dir / ".dataclaw" / "tool-config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "disabled": sorted(config.disabled),
        "enabled": sorted(config.enabled),
    }, indent=2) + "\n")


def is_tool_enabled(
    name: str,
    global_config: ToolConfig,
    project_config: ProjectToolConfig | None = None,
    session_config: SessionToolConfig | None = None,
) -> bool:
    """Determine if a tool is enabled.

    Resolution order (highest priority first):
    1. Session ``enabled`` / ``disabled``
    2. Project ``enabled`` / ``disabled``
    3. Global ``disabled``
    4. Default: enabled
    """
    if session_config is not None:
        if name in session_config.enabled:
            return True
        if name in session_config.disabled:
            return False
    if project_config is not None:
        if name in project_config.enabled:
            return True
        if name in project_config.disabled:
            return False
    return name not in global_config.disabled


def bump_version(config: ToolConfig) -> ToolConfig:
    """Increment the version counter and persist."""
    config.version += 1
    save_global_tool_config(config)
    return config
