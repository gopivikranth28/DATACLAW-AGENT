"""Dataclaw directory paths.

All runtime data is stored under DATACLAW_HOME, which defaults to
~/.dataclaw and can be overridden via the DATACLAW_HOME env var.
"""

from __future__ import annotations

import os
from pathlib import Path

DATACLAW_HOME = Path(os.environ.get("DATACLAW_HOME", Path.home() / ".dataclaw"))


def config_path() -> Path:
    """Path to the main config file."""
    return DATACLAW_HOME / "dataclaw.config.json"


def sessions_dir() -> Path:
    """Directory for chat session JSON files."""
    return DATACLAW_HOME / "sessions"


def skills_dir() -> Path:
    """Directory for skill markdown files."""
    return DATACLAW_HOME / "skills"


def workspaces_dir() -> Path:
    """Directory for per-workspace file storage."""
    return DATACLAW_HOME / "workspaces"


def plugins_dir() -> Path:
    """Base directory for plugin data."""
    return DATACLAW_HOME / "plugins"


def plugin_data_dir(plugin_name: str) -> Path:
    """Data directory for a specific plugin. Created on first access."""
    d = plugins_dir() / plugin_name
    d.mkdir(parents=True, exist_ok=True)
    return d


def tools_dir() -> Path:
    """Directory for user-defined custom tool Python files."""
    return DATACLAW_HOME / "tools"


def tool_config_path() -> Path:
    """Path to the global tool enable/disable config."""
    return DATACLAW_HOME / "tool-config.json"


def guardrail_config_path() -> Path:
    """Path to the global guardrail enable/disable config."""
    return DATACLAW_HOME / "guardrail-config.json"


def mcp_servers_path() -> Path:
    """Path to the MCP server configuration file."""
    return DATACLAW_HOME / "mcp-servers.json"


def skill_library_dir() -> Path:
    """Directory containing the bundled skill library (in the repo)."""
    return Path(__file__).resolve().parent.parent.parent / "skill-library"


def ensure_dirs() -> None:
    """Create all required directories if they don't exist."""
    for d in [DATACLAW_HOME, sessions_dir(), skills_dir(), workspaces_dir(), plugins_dir(), tools_dir()]:
        d.mkdir(parents=True, exist_ok=True)
