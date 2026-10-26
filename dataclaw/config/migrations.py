"""In-place migrations for persisted DataClaw configuration."""

from __future__ import annotations

from typing import Any

EXTERNAL_RUNTIMES = frozenset({"openclaw", "hermes"})

# Backends whose settings lived directly under ``llm.<id>`` before the
# ``llm.backends.<id>`` layout.
LEGACY_BACKEND_SECTIONS = ("anthropic", "openai", "gemini", "codex")

# Model defaults of the legacy schema (codex's is unchanged, so omitted).
_OLD_SCHEMA_DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-20250514",
    "openai": "gpt-4o",
    "gemini": "gemini-2.5-flash",
}


def _utility_backends() -> frozenset[str]:
    from dataclaw.providers.llm.registry import utility_backend_ids

    return utility_backend_ids()


def migrate_config(raw: dict[str, Any]) -> bool:
    """Apply every config migration in order. Returns True if ``raw`` changed."""
    changed = migrate_runtime_utility_config(raw)
    changed = migrate_llm_backends_config(raw) or changed
    return changed


def migrate_runtime_utility_config(raw: dict[str, Any]) -> bool:
    """Separate the legacy combined LLM/runtime selector.

    Older configs stored direct model providers and external agent runtimes in
    ``llm.backend``. New configs keep the runtime in ``agent.runtime`` while
    ``llm.backend`` always names DataClaw's utility provider.
    """

    changed = False
    llm = raw.setdefault("llm", {})
    if not isinstance(llm, dict):
        return False

    utility_backends = _utility_backends()
    legacy_backend = str(llm.get("backend") or "openclaw")
    agent = raw.setdefault("agent", {})
    if not isinstance(agent, dict):
        agent = {}
        raw["agent"] = agent
        changed = True

    if not agent.get("runtime"):
        if legacy_backend in EXTERNAL_RUNTIMES or legacy_backend == "mock":
            agent["runtime"] = legacy_backend
        else:
            agent["runtime"] = "dataclaw"
        changed = True

    hermes = raw.get("plugins", {}).get("hermes", {})
    if not isinstance(hermes, dict):
        hermes = {}

    if legacy_backend not in utility_backends:
        migrated_backend = str(hermes.get("utility_backend") or "")
        if migrated_backend not in utility_backends:
            migrated_backend = _configured_provider(llm) or "codex"
        llm["backend"] = migrated_backend
        changed = True

        migrated_model = str(hermes.get("utility_model") or "")
        if migrated_model:
            backends = llm.setdefault("backends", {})
            if isinstance(backends, dict):
                provider_config = backends.setdefault(migrated_backend, {})
                if isinstance(provider_config, dict):
                    provider_config["model"] = migrated_model
                    changed = True

    # These legacy aliases may remain readable in older releases, but the
    # current config has one canonical source for utility selection.
    if hermes:
        if "utility_backend" in hermes:
            del hermes["utility_backend"]
            changed = True
        if "utility_model" in hermes:
            del hermes["utility_model"]
            changed = True

    return changed


def migrate_llm_backends_config(raw: dict[str, Any]) -> bool:
    """Move ``llm.<backend>`` sections into ``llm.backends.<backend>``.

    Every key of a legacy section is carried over (api keys, models, the
    OpenAI ``base_url``, codex ``auth_mode``/``codex_bin``, unknown keys).
    A value already present under ``llm.backends`` wins, so re-running the
    migration, or a config edited by a newer release, never loses the newer
    setting. The legacy section is removed afterwards so a secret rotated in
    the UI does not linger in a stale copy. The resolver still reads legacy
    sections for configs that have not been migrated yet.
    """
    llm = raw.get("llm")
    if not isinstance(llm, dict):
        return False

    changed = False
    for backend in LEGACY_BACKEND_SECTIONS:
        legacy = llm.get(backend)
        if backend not in llm:
            continue
        if not isinstance(legacy, dict):
            del llm[backend]
            changed = True
            continue
        backends = llm.get("backends")
        if not isinstance(backends, dict):
            backends = {}
            llm["backends"] = backends
        current = backends.get(backend)
        if not isinstance(current, dict):
            current = {}
            backends[backend] = current
        for key, value in legacy.items():
            if key == "model" and _is_stale_default(backend, value, legacy):
                continue
            if _is_unset(current.get(key)):
                current[key] = value
        del llm[backend]
        changed = True
    return changed


def _is_stale_default(backend: str, model: Any, legacy: dict[str, Any]) -> bool:
    """Whether a legacy model value is the old schema default.

    Earlier releases wrote these defaults into every config file, so they
    record no user choice; dropping them lets the registry's current default
    apply. An OpenAI proxy (custom base_url) keeps its model, since the new
    default may not exist there.
    """
    if model != _OLD_SCHEMA_DEFAULT_MODELS.get(backend):
        return False
    return not (backend == "openai" and str(legacy.get("base_url") or "").strip())


def _is_unset(value: Any) -> bool:
    return value is None or value == "" or value == {}


def _configured_provider(llm: dict[str, Any]) -> str | None:
    """Prefer a provider with an explicitly saved API key."""

    backends = llm.get("backends") if isinstance(llm.get("backends"), dict) else {}
    for backend in ("codex", "openai", "anthropic", "gemini"):
        for provider in (backends.get(backend), llm.get(backend)):
            if isinstance(provider, dict) and str(provider.get("api_key") or ""):
                return backend
    return None
