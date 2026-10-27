"""Decision backend registry and settings.

Mirrors the LLM backend registry: each backend is a ``DecisionBackendSpec``
with its config fields (for the settings UI and resolution) and a
``build`` function.  Built-ins are ``typesafe`` (Jev), ``openrouter`` (Jev via OpenRouter) and ``llm`` (the
utility model through ``structured_output``); plugins add backends through
``PluginContext.register_decision_backend``.

Settings::

    decision.backend           none | typesafe | openrouter | llm | <plugin id>   (DATACLAW_DECISION_BACKEND)
    decision.min_confidence    0.7
    decision.<backend>.<field> backend fields, e.g. decision.typesafe.api_key (TYPESAFE_API_KEY)
    decision.routing.{plan_gates, skill_routing, compaction}   opt-in internal uses, default off

Field resolution, highest precedence first: explicit override > the field's
env var > ``decision.<id>.<field>`` > field default.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Literal

from dataclaw.config.resolver import resolve, resolve_bool
from dataclaw.providers.config_field import ConfigField
from dataclaw.providers.decision.provider import DecisionConfigurationError, DecisionError, DecisionProvider

if TYPE_CHECKING:
    from dataclaw.providers.llm.provider import LLMProvider

logger = logging.getLogger(__name__)

BACKEND_NONE = "none"
DEFAULT_MIN_CONFIDENCE = 0.7
RoutingUse = Literal["plan_gates", "skill_routing", "compaction"]
ROUTING_USES: tuple[RoutingUse, ...] = ("plan_gates", "skill_routing", "compaction")


@dataclass
class ResolvedDecisionConfig:
    """A decision backend's effective settings."""

    backend: str
    values: dict[str, Any] = field(default_factory=dict)

    def get(self, name: str, default: Any = None) -> Any:
        value = self.values.get(name)
        return default if value is None or value == "" else value

    @property
    def api_key(self) -> str:
        return str(self.get("api_key", "")).strip()


BuildDecision = Callable[[ResolvedDecisionConfig, "LLMProvider | None"], DecisionProvider]


@dataclass(frozen=True)
class DecisionBackendSpec:
    """Describes one decision backend.

    ``build(cfg, llm)`` returns a DecisionProvider; ``llm`` is the utility
    model (needed by the ``llm`` backend, ignored by others).  It may raise
    ``DecisionConfigurationError``.
    """

    id: str
    label: str
    build: BuildDecision
    config_fields: list[ConfigField] = field(default_factory=list)
    requires_api_key: bool = False
    vendor: str = ""
    description: str = ""

    def get_field(self, name: str) -> ConfigField | None:
        return next((f for f in self.config_fields if f.name == name), None)

    def api_key_hint(self) -> str:
        places: list[str] = []
        key_field = self.get_field("api_key")
        if key_field is not None and key_field.env:
            places.append(key_field.env)
        places.append(f"decision.{self.id}.api_key")
        return " or ".join(places)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "vendor": self.vendor or self.label,
            "description": self.description,
            "requires_api_key": self.requires_api_key,
            "fields": [f.to_dict() for f in self.config_fields],
        }


# ── Built-ins ───────────────────────────────────────────────────────────────


def _build_typesafe(cfg: ResolvedDecisionConfig, llm: "LLMProvider | None") -> DecisionProvider:
    from dataclaw.providers.decision.implementations.typesafe_jev import (
        DEFAULT_BASE_URL,
        DEFAULT_MODEL,
        TypeSafeJevProvider,
    )

    try:
        timeout = float(cfg.get("timeout", 30))
        max_retries = int(cfg.get("max_retries", 2))
    except (TypeError, ValueError) as exc:
        raise DecisionConfigurationError(f"Invalid TypeSafe timeout/max_retries: {exc}") from exc
    return TypeSafeJevProvider(
        cfg.api_key,
        model=str(cfg.get("model", DEFAULT_MODEL)).strip(),
        base_url=str(cfg.get("base_url", DEFAULT_BASE_URL)).strip(),
        timeout=timeout,
        max_retries=max_retries,
    )


def _build_openrouter(cfg: ResolvedDecisionConfig, llm: "LLMProvider | None") -> DecisionProvider:
    """Jev through OpenRouter, with the LLM backend's key and routing settings.

    One OpenRouter key (``llm.backends.openrouter.api_key`` /
    ``OPENROUTER_API_KEY``) powers both the LLM and the decision backend.
    """
    from dataclaw.providers.decision.implementations.openrouter_jev import (
        DEFAULT_ENDPOINT,
        DEFAULT_MODEL,
        OpenRouterJevProvider,
    )
    from dataclaw.providers.llm.registry import resolve_backend_config

    llm_cfg = resolve_backend_config("openrouter")
    if not llm_cfg.api_key:
        raise DecisionConfigurationError(
            "OpenRouter API key is not configured for the 'openrouter' decision backend. "
            "Set OPENROUTER_API_KEY or llm.backends.openrouter.api_key."
        )
    try:
        timeout = float(cfg.get("timeout", 30))
        max_retries = int(cfg.get("max_retries", 2))
    except (TypeError, ValueError) as exc:
        raise DecisionConfigurationError(f"Invalid OpenRouter timeout/max_retries: {exc}") from exc
    routing = llm_cfg.get("routing")
    try:
        return OpenRouterJevProvider(
            llm_cfg.api_key,
            model=str(cfg.get("model", DEFAULT_MODEL)).strip(),
            endpoint=str(cfg.get("endpoint", DEFAULT_ENDPOINT)).strip(),
            routing=routing if isinstance(routing, dict) else None,
            headers=llm_cfg.headers,
            timeout=timeout,
            max_retries=max_retries,
        )
    except DecisionError as exc:
        raise DecisionConfigurationError(str(exc)) from exc


def _build_llm(cfg: ResolvedDecisionConfig, llm: "LLMProvider | None") -> DecisionProvider:
    from dataclaw.providers.decision.implementations.llm_fallback import LLMDecisionProvider

    if llm is None:
        raise DecisionConfigurationError(
            "The llm decision backend needs DataClaw's utility model; configure llm.backend."
        )
    return LLMDecisionProvider(llm)


def _builtin_backends() -> list[DecisionBackendSpec]:
    return [
        DecisionBackendSpec(
            id="typesafe",
            label="TypeSafe Jev",
            vendor="TypeSafe",
            description=(
                "Decision model with calibrated probabilities (choice, score, yes/no). "
                "Also reachable through Vercel AI Gateway."
            ),
            requires_api_key=True,
            build=_build_typesafe,
            config_fields=[
                ConfigField("api_key", "secret", "API key", "TypeSafe or Vercel AI Gateway key.", required=True, env="TYPESAFE_API_KEY"),
                ConfigField(
                    "model",
                    "string",
                    "Model",
                    "jev-latest, jev-preview or a pinned version such as jev-1.14.0.",
                    default="jev-latest",
                ),
                ConfigField(
                    "base_url",
                    "string",
                    "Base URL",
                    "https://api.typesafe.ai, or https://ai-gateway.vercel.sh/typesafe for Vercel AI Gateway.",
                    default="https://api.typesafe.ai",
                ),
                ConfigField("timeout", "int", "Timeout (seconds)", default=30),
                ConfigField("max_retries", "int", "Retries on 429/5xx", default=2),
            ],
        ),
        DecisionBackendSpec(
            id="openrouter",
            label="OpenRouter Jev (alpha)",
            vendor="OpenRouter",
            description=(
                "Jev and other decision models through OpenRouter's Decisions API (alpha). "
                "Uses the OpenRouter key and routing settings of the OpenRouter LLM provider."
            ),
            build=_build_openrouter,
            config_fields=[
                ConfigField(
                    "model",
                    "string",
                    "Model",
                    "~typesafe/jev-latest, or a pinned typesafe/jev-1.14 or typesafe/jev-1.13.",
                    default="~typesafe/jev-latest",
                ),
                ConfigField(
                    "endpoint",
                    "select",
                    "API",
                    "The Decisions API is alpha; System One is the TypeSafe-SDK-compatible surface.",
                    default="decisions",
                    options=[
                        {"value": "decisions", "label": "Decisions API (alpha)"},
                        {"value": "systemone", "label": "System One API"},
                    ],
                ),
                ConfigField("timeout", "int", "Timeout (seconds)", default=30),
                ConfigField("max_retries", "int", "Retries on 429/5xx", default=2),
            ],
        ),
        DecisionBackendSpec(
            id="llm",
            label="Utility LLM",
            description=(
                "Answers with the configured DataClaw utility model. Confidence is the "
                "model's own estimate and is not calibrated."
            ),
            build=_build_llm,
        ),
    ]


# ── Registry ────────────────────────────────────────────────────────────────

_BACKENDS: dict[str, DecisionBackendSpec] = {}
_BUILTIN_IDS: set[str] = set()
_builtins_loaded = False


def _ensure_builtins() -> None:
    global _builtins_loaded
    if _builtins_loaded:
        return
    _builtins_loaded = True
    for spec in _builtin_backends():
        _BACKENDS[spec.id] = spec
        _BUILTIN_IDS.add(spec.id)


def register_decision_backend(spec: DecisionBackendSpec) -> None:
    """Register a plugin backend. Built-in ids and ``none`` cannot be replaced."""
    _ensure_builtins()
    backend_id = spec.id.strip().lower()
    if not backend_id or backend_id != spec.id:
        raise ValueError(f"Decision backend id must be a non-empty lower-case name: {spec.id!r}")
    if backend_id == BACKEND_NONE or backend_id in _BUILTIN_IDS:
        raise ValueError(f"Decision backend {backend_id!r} is built in and cannot be replaced")
    if backend_id in _BACKENDS:
        logger.debug("Replacing decision backend %s", backend_id)
    _BACKENDS[backend_id] = spec


def unregister_decision_backend(backend_id: str) -> None:
    if backend_id not in _BUILTIN_IDS:
        _BACKENDS.pop(backend_id, None)


def get_decision_backend(backend_id: str) -> DecisionBackendSpec | None:
    _ensure_builtins()
    return _BACKENDS.get((backend_id or "").strip().lower())


def list_decision_backends() -> list[DecisionBackendSpec]:
    _ensure_builtins()
    return list(_BACKENDS.values())


# ── Settings ────────────────────────────────────────────────────────────────


def resolve_decision_backend() -> str:
    """The selected backend id, or ``none``.

    Raises ``DecisionConfigurationError`` for an unknown id rather than
    silently turning decisions off.
    """
    backend = str(resolve("decision.backend", "DATACLAW_DECISION_BACKEND", BACKEND_NONE) or "").strip().lower()
    if not backend or backend == BACKEND_NONE:
        return BACKEND_NONE
    if get_decision_backend(backend) is None:
        known = ", ".join([BACKEND_NONE, *sorted(s.id for s in list_decision_backends())])
        raise DecisionConfigurationError(
            f"Unknown decision backend {backend!r} (decision.backend / DATACLAW_DECISION_BACKEND); use one of: {known}"
        )
    return backend


def decision_enabled() -> bool:
    """True when a decision backend is selected (unknown ids count as off)."""
    try:
        return resolve_decision_backend() != BACKEND_NONE
    except DecisionConfigurationError:
        return False


def resolve_min_confidence() -> float:
    raw = resolve("decision.min_confidence", "DATACLAW_DECISION_MIN_CONFIDENCE", DEFAULT_MIN_CONFIDENCE)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        logger.warning("Invalid decision.min_confidence %r; using %s", raw, DEFAULT_MIN_CONFIDENCE)
        return DEFAULT_MIN_CONFIDENCE
    return min(max(value, 0.0), 1.0)


def routing_enabled(use: RoutingUse) -> bool:
    """True when internal routing ``use`` is switched on and a backend is selected."""
    if use not in ROUTING_USES:
        raise ValueError(f"Unknown decision routing use: {use!r}")
    return resolve_bool(f"decision.routing.{use}", "", False) and decision_enabled()


def resolve_decision_config(backend_id: str, overrides: dict[str, Any] | None = None) -> ResolvedDecisionConfig:
    spec = get_decision_backend(backend_id)
    if spec is None:
        raise DecisionConfigurationError(f"Unknown decision backend: {backend_id!r}")
    overrides = {k: v for k, v in (overrides or {}).items() if v is not None}
    values: dict[str, Any] = {}
    for f in spec.config_fields:
        if f.name in overrides:
            values[f.name] = overrides[f.name]
            continue
        values[f.name] = resolve(f"decision.{spec.id}.{f.name}", f.env or "", f.default)
    return ResolvedDecisionConfig(backend=spec.id, values=values)


def build_decision_provider(
    backend_id: str | None = None,
    *,
    llm: "LLMProvider | None" = None,
) -> DecisionProvider:
    """Build the selected (or named) decision backend from configuration.

    Raises ``DecisionConfigurationError`` when decisions are off, the backend
    is unknown or a required API key is missing (naming the env var and
    config path).
    """
    backend = (backend_id or resolve_decision_backend()).strip().lower()
    if backend == BACKEND_NONE:
        raise DecisionConfigurationError(
            "No decision backend is configured. Set decision.backend (or DATACLAW_DECISION_BACKEND) to typesafe or llm."
        )
    spec = get_decision_backend(backend)
    if spec is None:
        raise DecisionConfigurationError(f"Unknown decision backend: {backend!r}")
    cfg = resolve_decision_config(spec.id)
    if spec.requires_api_key and not cfg.api_key:
        raise DecisionConfigurationError(
            f"{spec.vendor or spec.label} API key is not configured for the {spec.id!r} decision backend. "
            f"Set {spec.api_key_hint()}."
        )
    return spec.build(cfg, llm)
