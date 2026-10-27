"""In-place migrations for persisted DataClaw configuration."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from dataclaw.config.secure_io import write_private_text

logger = logging.getLogger(__name__)

EXTERNAL_RUNTIMES = frozenset({"openclaw", "hermes"})

# Backends whose settings lived directly under ``llm.<id>`` before the
# ``llm.backends.<id>`` layout.
LEGACY_BACKEND_SECTIONS = ("anthropic", "openai", "gemini", "codex")

# Model defaults of the legacy schema (codex's is unchanged, so omitted),
# mapped to their same-tier successors. Earlier releases wrote these defaults
# into every config file, so a migrated config keeps the same tier (and cost
# class) rather than jumping to the registry's current default.
_OLD_DEFAULT_SUCCESSORS = {
    "anthropic": ("claude-sonnet-4-20250514", "claude-sonnet-5-5"),
    "openai": ("gpt-4o", "gpt-6.1-sol"),
    "gemini": ("gemini-2.5-flash", "gemini-3.8-flash"),
}

# Copy of the config taken before the first migration that changes it, kept
# next to the config so a downgrade can restore the legacy layout.
BACKUP_SUFFIX = ".pre-llm-backends.bak"


def _utility_backends() -> frozenset[str]:
    from dataclaw.providers.llm.registry import utility_backend_ids

    return utility_backend_ids()


def migrate_config(raw: dict[str, Any]) -> bool:
    """Apply every config migration in order. Returns True if ``raw`` changed."""
    changed = migrate_runtime_utility_config(raw)
    changed = migrate_llm_backends_config(raw) or changed
    changed = migrate_openrouter_preset(raw) or changed
    return changed


def backup_path(config_file: Path) -> Path:
    return config_file.with_name(config_file.name + BACKUP_SUFFIX)


def migrate_config_file(config_file: Path) -> bool:
    """Migrate the config file in place. Returns True if it was rewritten.

    Before the first rewrite, the original bytes are saved as
    ``<config>.pre-llm-backends.bak`` (mode 0600, never overwritten), since
    the migrated file drops the legacy ``llm.<backend>`` sections that older
    releases read.
    """
    original = config_file.read_bytes()
    raw = json.loads(original)
    if not migrate_config(raw):
        return False
    backup = backup_path(config_file)
    created = _write_backup_once(backup, original)
    write_private_text(config_file, json.dumps(raw, indent=2))
    logger.info(
        "Migrated runtime and LLM backend config in %s (pre-migration copy: %s%s)",
        config_file,
        backup,
        "" if created else ", kept from an earlier migration",
    )
    return True


def _write_backup_once(backup: Path, data: bytes) -> bool:
    """Atomically create ``backup`` with mode 0600 unless it already exists."""
    if backup.exists():
        return False
    tmp = backup.with_name(f"{backup.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        # link() fails if the backup appeared meanwhile: never overwrite it.
        os.link(tmp, backup)
        return True
    except FileExistsError:
        return False
    finally:
        tmp.unlink(missing_ok=True)


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
            if key == "model":
                value = _successor_model(backend, value, legacy)
            if _is_unset(current.get(key)):
                current[key] = value
        del llm[backend]
        changed = True
    return changed


# Settings of an ``openai_compatible`` section with the OpenRouter preset that
# carry over to the ``openrouter`` backend. ``base_url`` and ``preset`` are
# implied by the new backend.
_OPENROUTER_PRESET_KEYS = ("api_key", "model", "reasoning_effort")
_OPENROUTER_PRESET_HEADERS = {"X-Title": "DataClaw"}


def migrate_openrouter_preset(raw: dict[str, Any]) -> bool:
    """Move ``llm.backends.openai_compatible`` with ``preset: openrouter`` to
    ``llm.backends.openrouter``.

    The key, model, reasoning effort and custom headers are kept (a value
    already set under ``openrouter`` wins), ``llm.backend`` follows when it
    pointed at ``openai_compatible``, and the old section is removed so the
    key does not linger in a stale copy. The preset still resolves for one
    release (deprecated) for configs that never pass through this migration.
    """
    llm = raw.get("llm")
    backends = llm.get("backends") if isinstance(llm, dict) else None
    if not isinstance(backends, dict):
        return False
    legacy = backends.get("openai_compatible")
    if not isinstance(legacy, dict) or str(legacy.get("preset") or "").strip() != "openrouter":
        return False

    current = backends.get("openrouter")
    if not isinstance(current, dict):
        current = {}
        backends["openrouter"] = current
    for key in _OPENROUTER_PRESET_KEYS:
        if not _is_unset(legacy.get(key)) and _is_unset(current.get(key)):
            current[key] = legacy[key]
    headers = legacy.get("headers")
    if isinstance(headers, dict):
        # The preset's own X-Title default is replaced by the backend's
        # X-OpenRouter-Title default; anything the user set is kept.
        custom = {
            k: v for k, v in headers.items()
            if v not in (None, "") and _OPENROUTER_PRESET_HEADERS.get(k) != v
        }
        merged = {**custom, **(current.get("headers") if isinstance(current.get("headers"), dict) else {})}
        if merged:
            current["headers"] = merged
    del backends["openai_compatible"]
    if llm.get("backend") == "openai_compatible":
        llm["backend"] = "openrouter"
    logger.info("migrated llm.backends.openai_compatible (OpenRouter preset) → llm.backends.openrouter")
    return True


def _successor_model(backend: str, model: Any, legacy: dict[str, Any]) -> Any:
    """The model to keep for a legacy section.

    An old schema default maps to its same-tier successor; any other value
    is kept. An OpenAI proxy (custom base_url) keeps its model, since the
    successor may not exist there.
    """
    old, new = _OLD_DEFAULT_SUCCESSORS.get(backend, (None, None))
    if model != old or (backend == "openai" and str(legacy.get("base_url") or "").strip()):
        return model
    logger.info("migrated llm.%s.model %s → %s", backend, old, new)
    return new


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
