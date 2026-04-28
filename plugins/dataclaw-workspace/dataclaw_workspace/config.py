"""Workspace plugin configuration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from dataclaw.config.schema import DataclawConfig


@dataclass
class WorkspaceConfig:
    """Runtime configuration for workspace tools."""
    max_read_bytes: int = 1_048_576       # 1 MB
    max_write_bytes: int = 2_097_152      # 2 MB
    max_list_entries: int = 1000
    max_exec_output_bytes: int = 262_144  # 256 KB
    exec_timeout_default: int = 120       # seconds
    exec_timeout_max: int = 300           # seconds


def load_config(app_config: DataclawConfig) -> WorkspaceConfig:
    """Load workspace config from the plugins section."""
    raw: dict[str, Any] = app_config.plugins.get("workspace", {})
    return WorkspaceConfig(
        max_read_bytes=int(raw.get("max_read_bytes", 1_048_576)),
        max_write_bytes=int(raw.get("max_write_bytes", 2_097_152)),
        max_list_entries=int(raw.get("max_list_entries", 1000)),
        max_exec_output_bytes=int(raw.get("max_exec_output_bytes", 262_144)),
        exec_timeout_default=int(raw.get("exec_timeout_default", 120)),
        exec_timeout_max=int(raw.get("exec_timeout_max", 300)),
    )
