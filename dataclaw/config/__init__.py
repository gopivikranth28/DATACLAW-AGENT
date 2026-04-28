"""Configuration system — paths, schema, and resolution."""

from dataclaw.config.paths import DATACLAW_HOME, config_path, sessions_dir, skills_dir, workspaces_dir, plugins_dir, plugin_data_dir
from dataclaw.config.schema import DataclawConfig
from dataclaw.config.resolver import resolve, resolve_bool

__all__ = [
    "DATACLAW_HOME",
    "config_path",
    "sessions_dir",
    "skills_dir",
    "workspaces_dir",
    "DataclawConfig",
    "resolve",
    "resolve_bool",
]
