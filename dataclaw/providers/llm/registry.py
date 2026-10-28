"""LLM backend registry — one place that knows every model backend.

Each backend is described by an ``LLMBackendSpec``: its config fields (for
the settings UI and for resolution), default models, presets, how to build
an ``LLMProvider`` and how to list its models.  Everything that used to keep
its own list of backend names (runtime selection, the utility-backend
resolver, config migration, the model catalog, the Config page) derives it
from here.

Built-in backends live in ``backends.py`` and are registered on first use.
Plugins add backends through ``PluginContext.register_llm_backend``.

Config resolution for a backend field, highest precedence first:
explicit override (e.g. a key typed in the UI) > the field's env var >
``llm.backends.<id>.<field>`` > legacy ``llm.<id>.<field>`` > preset
default > field default.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Literal

from dataclaw.config.resolver import resolve
from dataclaw.providers.config_field import ConfigField

if TYPE_CHECKING:
    from dataclaw.providers.llm.catalog import ModelInfo
    from dataclaw.providers.llm.provider import LLMProvider

logger = logging.getLogger(__name__)

Transport = Literal["anthropic", "openai_responses", "openai_chat", "gemini", "codex", "mock"]
ModelRole = Literal["agent", "utility"]

# Placeholder bearer token for keyless endpoints. The OpenAI SDKs fall back to
# OPENAI_API_KEY when no key is given, which would send the user's OpenAI key
# to a third-party server.
KEYLESS_API_KEY = "not-needed"


class LLMConfigurationError(ValueError):
    """A backend cannot be built from the current configuration."""


@dataclass(frozen=True)
class PresetSpec:
    """A ready-made endpoint for a generic backend (Ollama, OpenRouter, ...)."""

    id: str
    label: str
    base_url: str
    default_model: str = ""
    requires_api_key: bool = True
    api_key_env: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "base_url": self.base_url,
            "default_model": self.default_model,
            "requires_api_key": self.requires_api_key,
            "api_key_env": self.api_key_env,
            "headers": dict(self.headers),
            "notes": self.notes,
        }


@dataclass
class ResolvedBackendConfig:
    """A backend's effective settings after env/config/preset resolution."""

    backend: str
    values: dict[str, Any] = field(default_factory=dict)
    preset: PresetSpec | None = None

    def get(self, name: str, default: Any = None) -> Any:
        value = self.values.get(name)
        return default if value is None or value == "" else value

    @property
    def api_key(self) -> str:
        return str(self.get("api_key", "")).strip()

    @property
    def base_url(self) -> str:
        return str(self.get("base_url", "")).strip().rstrip("/")

    @property
    def model(self) -> str:
        return str(self.get("model", "")).strip()

    @property
    def headers(self) -> dict[str, str]:
        headers = self.values.get("headers")
        if not isinstance(headers, dict):
            return {}
        return {str(k): str(v) for k, v in headers.items() if k and v is not None}

    @property
    def reasoning_effort(self) -> str | None:
        return str(self.get("reasoning_effort", "")).strip() or None


ListModels = Callable[[ResolvedBackendConfig], Awaitable[list["ModelInfo"]]]
BuildLLM = Callable[[ResolvedBackendConfig, str], "LLMProvider"]


@dataclass(frozen=True)
class LLMBackendSpec:
    """Describes one LLM backend.

    ``build(cfg, model)`` returns an LLMProvider and may raise
    ``LLMConfigurationError``; it is only called once required credentials
    are present.  ``list_models(cfg)`` returns catalog entries and raises
    ``model_listing.ModelCatalogError`` / ``ModelCatalogUnauthenticated``.
    """

    id: str
    label: str
    transport: Transport
    build: BuildLLM
    config_fields: list[ConfigField] = field(default_factory=list)
    default_model: str = ""
    utility_default_model: str = ""
    requires_api_key: bool = True
    list_models: ListModels | None = None
    presets: dict[str, PresetSpec] = field(default_factory=dict)
    # Short provider name for messages ("Enter your <vendor> API key").
    vendor: str = ""
    description: str = ""
    # Hidden backends (mock) can be built but are not offered in the UI or
    # accepted as the configured utility backend.
    hidden: bool = False

    def get_field(self, name: str) -> ConfigField | None:
        return next((f for f in self.config_fields if f.name == name), None)

    def needs_api_key(self, cfg: ResolvedBackendConfig) -> bool:
        if cfg.preset is not None:
            return cfg.preset.requires_api_key
        return self.requires_api_key

    def api_key_hint(self, cfg: ResolvedBackendConfig | None = None) -> str:
        """Where a missing key can be configured, for error messages."""
        places: list[str] = []
        key_field = self.get_field("api_key")
        if key_field is not None and key_field.env:
            places.append(key_field.env)
        if cfg is not None and cfg.preset is not None and cfg.preset.api_key_env:
            places.append(cfg.preset.api_key_env)
        places.append(f"llm.backends.{self.id}.api_key")
        return " or ".join(places)

    def default_model_for(self, role: ModelRole = "agent", cfg: ResolvedBackendConfig | None = None) -> str:
        if cfg is not None and cfg.preset is not None and cfg.preset.default_model:
            return cfg.preset.default_model
        if role == "utility" and self.utility_default_model:
            return self.utility_default_model
        return self.default_model

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "vendor": self.vendor or self.label,
            "description": self.description,
            "transport": self.transport,
            "requires_api_key": self.requires_api_key,
            "default_model": self.default_model,
            "utility_default_model": self.utility_default_model or self.default_model,
            "supports_model_listing": self.list_models is not None,
            "fields": [f.to_dict() for f in self.config_fields],
            "presets": [p.to_dict() for p in self.presets.values()],
        }


# ── Registry ────────────────────────────────────────────────────────────────

_BACKENDS: dict[str, LLMBackendSpec] = {}
_BUILTIN_IDS: set[str] = set()
_builtins_loaded = False


def _ensure_builtins() -> None:
    global _builtins_loaded
    if _builtins_loaded:
        return
    _builtins_loaded = True
    from dataclaw.providers.llm import backends

    for spec in backends.builtin_backends():
        _BACKENDS[spec.id] = spec
        _BUILTIN_IDS.add(spec.id)


def register_llm_backend(spec: LLMBackendSpec) -> None:
    """Register a plugin backend.

    Built-in ids cannot be shadowed. Re-registering a plugin id replaces the
    previous spec (plugins register again whenever an app is created).
    """
    _ensure_builtins()
    backend_id = spec.id.strip().lower()
    if not backend_id or backend_id != spec.id:
        raise ValueError(f"LLM backend id must be a non-empty lower-case name: {spec.id!r}")
    if backend_id in _BUILTIN_IDS:
        raise ValueError(f"LLM backend {backend_id!r} is built in and cannot be replaced")
    if backend_id in _BACKENDS:
        logger.debug("Replacing LLM backend %s", backend_id)
    _BACKENDS[backend_id] = spec


def unregister_llm_backend(backend_id: str) -> None:
    """Remove a plugin backend (tests, plugin unload). Built-ins stay."""
    if backend_id not in _BUILTIN_IDS:
        _BACKENDS.pop(backend_id, None)


def get_llm_backend(backend_id: str) -> LLMBackendSpec | None:
    _ensure_builtins()
    return _BACKENDS.get((backend_id or "").strip().lower())


def require_llm_backend(backend_id: str) -> LLMBackendSpec:
    spec = get_llm_backend(backend_id)
    if spec is None:
        raise ValueError(f"Unknown LLM backend: {backend_id!r}")
    return spec


def list_llm_backends(*, include_hidden: bool = False) -> list[LLMBackendSpec]:
    _ensure_builtins()
    return [s for s in _BACKENDS.values() if include_hidden or not s.hidden]


def llm_backend_ids() -> frozenset[str]:
    """Every buildable backend id, including hidden ones (mock)."""
    return frozenset(s.id for s in list_llm_backends(include_hidden=True))


def utility_backend_ids() -> frozenset[str]:
    """Backends that may be configured as DataClaw's utility model."""
    return frozenset(s.id for s in list_llm_backends())


# ── Resolution ──────────────────────────────────────────────────────────────


def resolve_backend_config(
    backend_id: str,
    overrides: dict[str, Any] | None = None,
) -> ResolvedBackendConfig:
    """Resolve every declared field of a backend (see module docstring)."""
    spec = require_llm_backend(backend_id)
    overrides = {k: v for k, v in (overrides or {}).items() if v is not None}
    values: dict[str, Any] = {}
    for f in spec.config_fields:
        if f.name in overrides:
            values[f.name] = overrides[f.name]
            continue
        value = _configured(spec.id, f.name, f.env)
        values[f.name] = f.default if value is None else value

    preset = spec.presets.get(str(values.get("preset") or "").strip())
    if preset is not None:
        if not str(values.get("base_url") or "").strip():
            values["base_url"] = preset.base_url
        configured_headers = values.get("headers")
        values["headers"] = {
            **preset.headers,
            **(configured_headers if isinstance(configured_headers, dict) else {}),
        }
        if not str(values.get("api_key") or "").strip() and preset.api_key_env:
            values["api_key"] = os.environ.get(preset.api_key_env, "")
    return ResolvedBackendConfig(backend=spec.id, values=values, preset=preset)


def _configured(backend_id: str, name: str, env: str | None) -> Any:
    sentinel = object()
    value = resolve(f"llm.backends.{backend_id}.{name}", env or "", sentinel)
    if value is sentinel:
        # Not yet migrated configs keep settings in llm.<backend>.
        value = resolve(f"llm.{backend_id}.{name}", "", sentinel)
    return None if value is sentinel else value


def build_llm(
    backend_id: str,
    model: str | None = None,
    *,
    role: ModelRole = "agent",
) -> "LLMProvider":
    """Build an LLMProvider for ``backend_id`` from the current configuration.

    Raises ``LLMConfigurationError`` (naming the env var / config path) when
    a required API key is missing, instead of silently degrading.
    """
    spec = require_llm_backend(backend_id)
    cfg = resolve_backend_config(spec.id)
    if spec.needs_api_key(cfg) and not cfg.api_key:
        raise LLMConfigurationError(
            f"{spec.vendor or spec.label} API key is not configured for the "
            f"{spec.id!r} LLM backend. Set {spec.api_key_hint(cfg)}."
        )
    model_id = (model or "").strip() or cfg.model or spec.default_model_for(role, cfg)
    return spec.build(cfg, model_id)


def default_model_for(backend_id: str, role: ModelRole = "agent") -> str:
    """The registry default for a backend (empty for unknown backends)."""
    spec = get_llm_backend(backend_id)
    return spec.default_model_for(role) if spec is not None else ""
