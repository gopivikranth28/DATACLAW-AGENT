"""Guardrail enable/disable configuration persistence.

Global config lives at ~/.dataclaw/guardrail-config.json.
Project-level overrides live at {project_dir}/.dataclaw/guardrail-config.json.
Session-level overrides live on the session JSON object (``guardrailConfig`` key).

Resolution order (highest wins):
    session > project > global > default (enabled).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from dataclaw.config.paths import guardrail_config_path

logger = logging.getLogger(__name__)


@dataclass
class GuardrailConfig:
    """Global guardrail configuration."""
    disabled: set[str] = field(default_factory=set)


@dataclass
class ProjectGuardrailConfig:
    """Project-level guardrail overrides."""
    disabled: set[str] = field(default_factory=set)
    enabled: set[str] = field(default_factory=set)


@dataclass
class SessionGuardrailConfig:
    """Session-level guardrail overrides."""
    disabled: set[str] = field(default_factory=set)
    enabled: set[str] = field(default_factory=set)


def session_guardrail_config_from_dict(data: dict | None) -> SessionGuardrailConfig | None:
    """Parse a session's ``guardrailConfig`` dict into a SessionGuardrailConfig."""
    if not data:
        return None
    return SessionGuardrailConfig(
        disabled=set(data.get("disabled", [])),
        enabled=set(data.get("enabled", [])),
    )


def session_guardrail_config_to_dict(config: SessionGuardrailConfig) -> dict:
    """Serialize a SessionGuardrailConfig to a plain dict for session JSON storage."""
    return {
        "disabled": sorted(config.disabled),
        "enabled": sorted(config.enabled),
    }


def load_global_guardrail_config() -> GuardrailConfig:
    path = guardrail_config_path()
    if not path.exists():
        return GuardrailConfig()
    try:
        data = json.loads(path.read_text())
        return GuardrailConfig(disabled=set(data.get("disabled", [])))
    except Exception:
        logger.warning("Failed to read guardrail config at %s, using defaults", path)
        return GuardrailConfig()


def save_global_guardrail_config(config: GuardrailConfig) -> None:
    path = guardrail_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "disabled": sorted(config.disabled),
    }, indent=2) + "\n")


def load_project_guardrail_config(project_dir: Path) -> ProjectGuardrailConfig | None:
    path = project_dir / ".dataclaw" / "guardrail-config.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return ProjectGuardrailConfig(
            disabled=set(data.get("disabled", [])),
            enabled=set(data.get("enabled", [])),
        )
    except Exception:
        logger.warning("Failed to read project guardrail config at %s", path)
        return None


def save_project_guardrail_config(project_dir: Path, config: ProjectGuardrailConfig) -> None:
    path = project_dir / ".dataclaw" / "guardrail-config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "disabled": sorted(config.disabled),
        "enabled": sorted(config.enabled),
    }, indent=2) + "\n")


def is_guardrail_enabled(
    guardrail_id: str,
    global_config: GuardrailConfig,
    project_config: ProjectGuardrailConfig | None = None,
    session_config: SessionGuardrailConfig | None = None,
) -> bool:
    """Determine if a guardrail is enabled.

    Resolution order (highest priority first):
    1. Session ``enabled`` / ``disabled``
    2. Project ``enabled`` / ``disabled``
    3. Global ``disabled``
    4. Default: enabled
    """
    if session_config is not None:
        if guardrail_id in session_config.enabled:
            return True
        if guardrail_id in session_config.disabled:
            return False
    if project_config is not None:
        if guardrail_id in project_config.enabled:
            return True
        if guardrail_id in project_config.disabled:
            return False
    return guardrail_id not in global_config.disabled
