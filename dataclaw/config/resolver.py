"""Config resolution: env var > config file > default.

Usage:
    from dataclaw.config.resolver import resolve
    api_key = resolve("llm.anthropic.api_key", "ANTHROPIC_API_KEY", "")
"""

from __future__ import annotations

import json
import os
from typing import Any

from dataclaw.config.paths import config_path

_config_cache: dict[str, Any] | None = None


def _read_config_file() -> dict[str, Any]:
    """Read and cache the config file. Returns empty dict if missing."""
    global _config_cache
    if _config_cache is not None:
        return _config_cache

    path = config_path()
    if path.exists():
        _config_cache = json.loads(path.read_text())
    else:
        _config_cache = {}
    return _config_cache


def invalidate_cache() -> None:
    """Clear the config file cache (useful after writes)."""
    global _config_cache
    _config_cache = None


def resolve(dot_path: str, env_var: str, default: Any = None) -> Any:
    """Resolve a config value: env var takes precedence, then config file, then default."""
    val = os.environ.get(env_var)
    if val is not None:
        return val

    raw: Any = _read_config_file()
    for part in dot_path.split("."):
        if not isinstance(raw, dict):
            return default
        raw = raw.get(part)
        if raw is None:
            return default
    return raw if raw is not None else default


def resolve_bool(dot_path: str, env_var: str, default: bool = False) -> bool:
    """Resolve a boolean config value with env var coercion."""
    val = resolve(dot_path, env_var, None)
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() in ("true", "1", "yes")
    return bool(val)
