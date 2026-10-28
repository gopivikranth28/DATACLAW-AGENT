"""Config resolution: env var > config file > default.

Usage:
    from dataclaw.config.resolver import resolve
    api_key = resolve("llm.backends.anthropic.api_key", "ANTHROPIC_API_KEY", "")
"""

from __future__ import annotations

import json
import os
from typing import Any

from dataclaw.config.paths import config_path

_config_cache: dict[str, Any] | None = None
AGENT_RUNTIMES = frozenset({"dataclaw", "openclaw", "hermes", "mock"})


def _utility_backends() -> frozenset[str]:
    # The LLM backend registry is the single list of model backends. Imported
    # lazily: the registry resolves its own settings through this module.
    from dataclaw.providers.llm.registry import utility_backend_ids

    return utility_backend_ids()


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


def resolve_agent_runtime() -> str:
    """Resolve the primary agent runtime with legacy config compatibility."""

    configured = str(
        resolve("agent.runtime", "DATACLAW_AGENT_RUNTIME", "") or ""
    ).strip()
    if configured:
        if configured not in AGENT_RUNTIMES:
            raise ValueError(f"Unknown agent runtime: {configured!r}")
        return configured

    legacy = str(
        resolve("llm.backend", "DATACLAW_LLM_BACKEND", "openclaw")
    ).strip()
    if legacy in {"openclaw", "hermes", "mock"}:
        return legacy
    if legacy in _utility_backends():
        return "dataclaw"
    raise ValueError(f"Unknown legacy runtime/backend: {legacy!r}")


def resolve_utility_backend() -> str:
    """Resolve DataClaw's utility model provider.

    ``DATACLAW_UTILITY_BACKEND`` is the canonical environment override. The
    legacy ``DATACLAW_LLM_BACKEND`` remains accepted when it names a model
    provider rather than an external runtime.
    """

    backends = _utility_backends()
    explicit_env = str(os.environ.get("DATACLAW_UTILITY_BACKEND") or "").strip()
    if explicit_env:
        if explicit_env not in backends:
            raise ValueError(f"Unknown utility backend: {explicit_env!r}")
        return explicit_env

    legacy_env = str(os.environ.get("DATACLAW_LLM_BACKEND") or "").strip()
    if legacy_env in backends:
        return legacy_env

    configured = str(resolve("llm.backend", "", "") or "").strip()
    if configured in backends:
        return configured

    # Read the Hermes aliases only for installations that have not yet run the
    # persisted-config migration.
    legacy_hermes = str(
        resolve(
            "plugins.hermes.utility_backend",
            "DATACLAW_HERMES_UTILITY_BACKEND",
            "",
        )
        or ""
    ).strip()
    if legacy_hermes in backends:
        return legacy_hermes
    raise ValueError(
        "Configure llm.backend with a DataClaw utility provider "
        f"({', '.join(sorted(backends))})"
    )


def resolve_utility_model(backend: str | None = None) -> str:
    """Resolve the selected utility provider's model ID.

    Precedence: the backend's configured model (env var, then
    ``llm.backends.<id>.model``, then legacy ``llm.<id>.model``), the legacy
    Hermes alias, then the registry default. The default is the backend's
    primary model when DataClaw runs the agent loop on it, and its cheaper
    utility model when an external runtime owns the loop.
    """
    from dataclaw.providers.llm.registry import get_llm_backend, resolve_backend_config

    selected = backend or resolve_utility_backend()
    spec = get_llm_backend(selected)
    if spec is None:
        return ""
    cfg = resolve_backend_config(spec.id)
    if cfg.model:
        return cfg.model
    legacy_alias = str(
        resolve(
            "plugins.hermes.utility_model",
            "DATACLAW_HERMES_UTILITY_MODEL",
            "",
        )
        or ""
    ).strip()
    if legacy_alias:
        return legacy_alias
    try:
        runtime = resolve_agent_runtime()
    except ValueError:
        runtime = "dataclaw"
    role = "agent" if runtime in ("dataclaw", "mock") else "utility"
    return spec.default_model_for(role, cfg)
