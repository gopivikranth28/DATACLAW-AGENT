"""Configure OpenClaw's bundled ``openrouter`` provider from Dataclaw.

OpenClaw 2026.10.7 ships an enabled-by-default ``openrouter`` provider
extension. This module drives it through the OpenClaw CLI:

- **API key** — ``openclaw models auth paste-api-key --provider openrouter``
  with the key piped on **stdin**. The key lands in OpenClaw's auth-profile
  store (``~/.openclaw/state/openclaw.sqlite``); ``openclaw.json`` only gets
  a non-secret ``auth.profiles.<id> = {provider, mode: api_key}`` entry. It
  updates the active OpenRouter profile (or creates ``openrouter:manual``), so
  a re-submit rotates the key in place. The key is never put on argv.
- **Primary model** — ``openclaw models set <ref>``. OpenClaw canonicalizes
  some refs (``openrouter/openrouter/fusion`` is stored as
  ``openrouter/fusion``), so the stored value is read back before anything is
  keyed on it.
- **Routing / response cache** — per-model params at
  ``agents.defaults.models["<ref>"].params.{provider,responseCache,
  responseCacheTtlSeconds}``, written with one ``config set --batch-json``
  (hot-reloaded; no gateway restart). OpenClaw does not validate the
  ``provider`` routing object, so Dataclaw does.
- **Credential status** — ``openclaw models status --json``; only a boolean is
  derived from it (its ``labels``/``env`` fields carry key fragments).

Neither ``models set`` nor ``config set`` checks a ref against OpenRouter's
live catalog (an unknown model is saved with a warning), so callers validate
against :func:`fetch_openrouter_catalog` when it is reachable.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from collections.abc import Iterable
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

logger = logging.getLogger(__name__)

PROVIDER_ID = "openrouter"
API_KEY_ENV_VAR = "OPENROUTER_API_KEY"
MODEL_ENV_VAR = "DATACLAW_OPENCLAW_MODEL"
DEFAULT_MODEL_REF = "openrouter/auto"
REF_PREFIX = f"{PROVIDER_ID}/"

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
CATALOG_TTL_SECONDS = 600.0
_CATALOG_MAX_BYTES = 16 * 1024 * 1024

_REDACTED = "****"
# OpenRouter keys look like ``sk-or-v1-<hex>``; redact anything key-shaped even
# when the exact value is unknown (e.g. a key OpenClaw echoes from its store).
_KEY_PATTERN = re.compile(r"sk-or-[A-Za-z0-9_-]{4,}")

# Upstream OpenRouter model ids: ``vendor/model`` with an optional ``:variant``
# (``:free``, ``:batch``…). ``~vendor/…`` are OpenRouter's "latest" aliases.
_UPSTREAM_ID_RE = re.compile(r"^~?[a-z0-9][a-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._:-]*$")
_PROVIDER_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,63}$")
_MAX_MODEL_LEN = 200
_MAX_KEY_LEN = 512
_MAX_SLUGS = 32


# ── Secret handling ─────────────────────────────────────────────────────────


def redact(text: str, secrets: Iterable[str | None] = ()) -> str:
    """Mask every known secret and anything shaped like an OpenRouter key."""
    out = text or ""
    for secret in secrets:
        if secret and len(secret) >= 4:
            out = out.replace(secret, _REDACTED)
    return _KEY_PATTERN.sub(_REDACTED, out)


def validate_api_key(raw: str) -> str:
    """Trim and sanity-check an API key. Raises ``ValueError`` (without echoing it)."""
    key = (raw or "").strip()
    if not key:
        raise ValueError("api_key is empty")
    if len(key) > _MAX_KEY_LEN:
        raise ValueError("api_key is too long")
    if any(ch.isspace() or not ch.isprintable() for ch in key):
        raise ValueError("api_key must be a single line without spaces")
    return key


# ── Model refs ──────────────────────────────────────────────────────────────


def normalize_model_ref(raw: str) -> tuple[str, str]:
    """Return ``(openclaw_ref, openrouter_id)`` for a model string.

    Accepts an OpenClaw ref (``openrouter/anthropic/claude-opus-5.5``,
    ``openrouter/auto``, ``openrouter/openrouter/fusion``) or a bare OpenRouter
    id (``anthropic/claude-opus-5.5``, ``openrouter/fusion``, ``auto``). The
    returned ref is the form OpenClaw stores: OpenRouter's own
    ``openrouter/<x>`` routers are not double-prefixed.
    """
    model = (raw or "").strip()
    if not model:
        raise ValueError("model is required")
    if len(model) > _MAX_MODEL_LEN:
        raise ValueError("model is too long")
    if model == "auto":
        upstream = "openrouter/auto"
    elif model.startswith(REF_PREFIX):
        rest = model[len(REF_PREFIX):]
        # `openrouter/<x>` without another slash is OpenRouter's own router
        # namespace (auto, fusion); otherwise the rest is the upstream id.
        upstream = rest if "/" in rest else f"{PROVIDER_ID}/{rest}"
    else:
        upstream = model
    if not _UPSTREAM_ID_RE.match(upstream):
        raise ValueError(
            "model must be an OpenRouter model like "
            "'openrouter/<vendor>/<model>' (e.g. openrouter/anthropic/claude-opus-5.5) "
            "or 'openrouter/auto'"
        )
    ref = upstream if upstream.startswith(REF_PREFIX) else f"{REF_PREFIX}{upstream}"
    return ref, upstream


def openrouter_id_from_ref(ref: str | None) -> str | None:
    """Inverse of :func:`normalize_model_ref` for an OpenClaw-stored ref."""
    if not ref or not ref.startswith(REF_PREFIX):
        return None
    try:
        return normalize_model_ref(ref)[1]
    except ValueError:
        return None


def model_params_path(ref: str, *leaf: str) -> str:
    """Config path for a per-model param; bracket-quotes the ref (it has dots)."""
    return ".".join([f"agents.defaults.models[{json.dumps(ref)}].params", *leaf])


# ── Request schema ──────────────────────────────────────────────────────────


class RoutingSettings(BaseModel):
    """Subset of OpenRouter's ``provider`` routing object Dataclaw manages."""

    model_config = ConfigDict(extra="forbid")

    data_collection: Literal["allow", "deny"] | None = None
    zdr: bool | None = None
    sort: Literal["price", "throughput", "latency"] | None = None
    order: list[str] | None = None
    only: list[str] | None = None
    ignore: list[str] | None = None
    allow_fallbacks: bool | None = None

    @field_validator("order", "only", "ignore")
    @classmethod
    def _slugs(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        if len(value) > _MAX_SLUGS:
            raise ValueError(f"at most {_MAX_SLUGS} providers")
        cleaned: list[str] = []
        for item in value:
            slug = str(item).strip()
            if not _PROVIDER_SLUG_RE.match(slug):
                raise ValueError(f"invalid provider slug: {slug[:64]!r}")
            if slug not in cleaned:
                cleaned.append(slug)
        return cleaned

    def to_openrouter(self) -> dict[str, Any]:
        """The ``params.provider`` object; unset fields are omitted."""
        return self.model_dump(exclude_none=True)


class ResponseCacheSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    # OpenClaw truncates/clamps to 1–86400; reject out-of-range values instead.
    ttl_seconds: int | None = Field(default=None, ge=1, le=86400)


class ModelConfigRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["openrouter"]
    api_key: str | None = Field(default=None, repr=False)
    model: str
    routing: RoutingSettings | None = None
    response_cache: ResponseCacheSettings | None = None

    @field_validator("model")
    @classmethod
    def _model(cls, value: str) -> str:
        return normalize_model_ref(value)[0]

    @field_validator("api_key")
    @classmethod
    def _key(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        return validate_api_key(value)


def build_model_param_entries(
    ref: str,
    routing: RoutingSettings | None,
    response_cache: ResponseCacheSettings | None,
) -> list[dict[str, Any]]:
    """``config set --batch-json`` entries for one model's params.

    ``routing=None`` / ``response_cache=None`` leave the existing values
    alone. A ``routing`` object replaces ``params.provider`` wholesale (``set``
    replaces the object at a path), so cleared toggles really clear.
    """
    entries: list[dict[str, Any]] = []
    if routing is not None:
        entries.append({"path": model_params_path(ref, "provider"), "value": routing.to_openrouter()})
    if response_cache is not None:
        entries.append({"path": model_params_path(ref, "responseCache"), "value": response_cache.enabled})
        if response_cache.ttl_seconds is not None:
            entries.append({
                "path": model_params_path(ref, "responseCacheTtlSeconds"),
                "value": response_cache.ttl_seconds,
            })
    return entries


# ── CLI plumbing ────────────────────────────────────────────────────────────


class OpenClawCommandError(RuntimeError):
    """An openclaw subcommand failed; ``output`` is already redacted."""

    def __init__(self, step: str, returncode: int | None, output: str) -> None:
        self.step = step
        self.returncode = returncode
        self.output = output
        tail = output.strip().splitlines()[-1:] if output.strip() else []
        super().__init__(f"{step} failed (exit {returncode})" + (f": {tail[0]}" if tail else ""))


async def run_openclaw(
    argv: list[str],
    args: list[str],
    *,
    stdin: str | None = None,
    secrets: Iterable[str | None] = (),
    env: dict[str, str] | None = None,
    timeout: float = 120,
) -> tuple[int | None, str]:
    """Run ``<argv> <args>``; return ``(returncode, redacted stdout+stderr)``.

    Secrets travel on stdin only. Output is redacted before it is returned, so
    callers may log or surface it.
    """
    secrets = list(secrets)
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, *args,
            stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
        )
    except OSError as exc:
        return None, redact(f"could not run {argv[0]}: {exc}", secrets)
    try:
        out, _ = await asyncio.wait_for(
            proc.communicate(stdin.encode() if stdin is not None else None), timeout=timeout,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return None, f"{' '.join(args[:3])} timed out after {timeout:.0f}s"
    return proc.returncode, redact(out.decode(errors="replace"), secrets)


def _env_without_key() -> dict[str, str]:
    """Process env minus the OpenRouter key, so status reports only what
    OpenClaw itself has stored (not what this process happens to export)."""
    env = os.environ.copy()
    env.pop(API_KEY_ENV_VAR, None)
    return env


def _parse_json_output(output: str) -> Any:
    start = output.find("{")
    if start < 0:
        return None
    try:
        return json.loads(output[start:])
    except json.JSONDecodeError:
        return None


async def get_config_value(argv: list[str], path: str) -> Any:
    rc, out = await run_openclaw(argv, ["config", "get", path, "--json"], timeout=30)
    if rc != 0:
        return None
    text = out.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def credential_configured_from_status(status: Any) -> bool:
    """True when ``models status --json`` lists a usable OpenRouter credential source."""
    if not isinstance(status, dict):
        return False
    auth = status.get("auth")
    providers = auth.get("providers") if isinstance(auth, dict) else None
    for entry in providers or []:
        if not isinstance(entry, dict) or entry.get("provider") != PROVIDER_ID:
            continue
        effective = entry.get("effective")
        kind = effective.get("kind") if isinstance(effective, dict) else None
        if kind and kind not in ("missing", "none"):
            return True
    return False


async def is_credential_configured(argv: list[str]) -> bool:
    rc, out = await run_openclaw(argv, ["models", "status", "--json"], env=_env_without_key(), timeout=60)
    if rc != 0:
        return False
    return credential_configured_from_status(_parse_json_output(out))


async def store_api_key(argv: list[str], api_key: str) -> None:
    """Save the key in OpenClaw's auth-profile store via stdin."""
    rc, out = await run_openclaw(
        argv,
        ["models", "auth", "paste-api-key", "--provider", PROVIDER_ID],
        stdin=api_key + "\n",
        secrets=[api_key],
    )
    if rc != 0:
        raise OpenClawCommandError("openclaw models auth paste-api-key", rc, out)


async def set_primary_model(argv: list[str], ref: str) -> str:
    """``openclaw models set <ref>``; returns the ref OpenClaw actually stored."""
    rc, out = await run_openclaw(argv, ["models", "set", ref])
    if rc != 0:
        raise OpenClawCommandError("openclaw models set", rc, out)
    stored = await get_config_value(argv, "agents.defaults.model.primary")
    return stored if isinstance(stored, str) and stored else ref


async def apply_batch(argv: list[str], entries: list[dict[str, Any]]) -> None:
    if not entries:
        return
    rc, out = await run_openclaw(argv, ["config", "set", "--batch-json", json.dumps(entries)])
    if rc != 0:
        raise OpenClawCommandError("openclaw config set --batch-json", rc, out)


def _primary_from(value: Any) -> str | None:
    if isinstance(value, str):
        return value or None
    if isinstance(value, dict) and isinstance(value.get("primary"), str):
        return value["primary"] or None
    return None


async def read_model_state(argv: list[str]) -> dict[str, Any]:
    """Current primary model, credential presence, and the primary's params.

    Never includes key material.
    """
    primary = _primary_from(await get_config_value(argv, "agents.defaults.model"))
    params: dict[str, Any] = {}
    if primary:
        raw = await get_config_value(argv, model_params_path(primary))
        params = raw if isinstance(raw, dict) else {}
    routing = params.get("provider") if isinstance(params.get("provider"), dict) else {}
    cache_enabled = params.get("responseCache")
    ttl = params.get("responseCacheTtlSeconds")
    return {
        "provider": primary.split("/", 1)[0] if primary and "/" in primary else None,
        "model": primary,
        "openrouter_model": openrouter_id_from_ref(primary),
        "configured": await is_credential_configured(argv),
        "env_key_available": bool(os.environ.get(API_KEY_ENV_VAR, "").strip()),
        "routing": routing,
        "response_cache": {
            "enabled": cache_enabled is True,
            "ttl_seconds": ttl if isinstance(ttl, int) else None,
        },
    }


async def apply_model_config(
    argv: list[str],
    *,
    model: str,
    api_key: str | None = None,
    routing: RoutingSettings | None = None,
    response_cache: ResponseCacheSettings | None = None,
) -> dict[str, Any]:
    """Store the key (if any), set the primary model, write per-model params.

    Returns ``{"model": <stored ref>, "key_updated": bool, "entries": n}``.
    """
    ref, _ = normalize_model_ref(model)
    if api_key:
        await store_api_key(argv, validate_api_key(api_key))
    stored = await set_primary_model(argv, ref)
    entries = build_model_param_entries(stored, routing, response_cache)
    await apply_batch(argv, entries)
    logger.info(
        "Configured OpenClaw model %s (key updated: %s, param entries: %d)",
        stored, bool(api_key), len(entries),
    )
    return {"model": stored, "key_updated": bool(api_key), "entries": len(entries)}


async def bootstrap_from_env(argv: list[str], env: dict[str, str] | None = None) -> list[str]:
    """First-start configuration for the bundled image.

    - ``OPENROUTER_API_KEY`` set and OpenClaw has no OpenRouter credential →
      store it (an existing credential is never overwritten).
    - ``DATACLAW_OPENCLAW_MODEL`` set → apply it as the primary model on every
      start (the env var is the operator's override).
    - Otherwise, when a key is available but no primary model is configured,
      default to ``openrouter/auto`` (what OpenClaw's own onboarding picks).

    Returns human-readable progress lines (never containing the key).
    """
    env = os.environ if env is None else env
    lines: list[str] = []
    raw_key = (env.get(API_KEY_ENV_VAR) or "").strip()
    raw_model = (env.get(MODEL_ENV_VAR) or "").strip()

    key: str | None = None
    if raw_key:
        try:
            key = validate_api_key(raw_key)
        except ValueError as exc:
            lines.append(f"warning: ignoring {API_KEY_ENV_VAR}: {exc}")
    if key:
        if await is_credential_configured(argv):
            lines.append("OpenRouter credential already configured in OpenClaw; leaving it unchanged")
        else:
            await store_api_key(argv, key)
            lines.append(f"Stored {API_KEY_ENV_VAR} in OpenClaw's openrouter auth profile")

    ref: str | None = None
    if raw_model:
        try:
            ref = normalize_model_ref(raw_model)[0]
        except ValueError as exc:
            lines.append(f"warning: ignoring {MODEL_ENV_VAR}: {exc}")
    elif key and not _primary_from(await get_config_value(argv, "agents.defaults.model")):
        ref = DEFAULT_MODEL_REF
    if ref:
        stored = await set_primary_model(argv, ref)
        lines.append(f"OpenClaw primary model: {stored}")
    return lines


# ── OpenRouter public catalog (proxied for the UI) ───────────────────────────

_catalog_cache: dict[str, Any] = {"at": 0.0, "models": None}
_catalog_lock = asyncio.Lock()


def summarize_catalog(payload: Any) -> list[dict[str, Any]]:
    """Compact, UI-shaped rows; ``:batch`` variants are dropped."""
    data = payload.get("data") if isinstance(payload, dict) else None
    rows: list[dict[str, Any]] = []
    for item in data or []:
        if not isinstance(item, dict):
            continue
        model_id = item.get("id")
        if not isinstance(model_id, str) or not _UPSTREAM_ID_RE.match(model_id):
            continue
        if model_id.endswith(":batch"):
            continue
        pricing = item.get("pricing") if isinstance(item.get("pricing"), dict) else {}
        params = item.get("supported_parameters")
        rows.append({
            "id": model_id,
            "ref": normalize_model_ref(model_id)[0],
            "name": item.get("name") if isinstance(item.get("name"), str) else model_id,
            "vendor": model_id.split("/", 1)[0].lstrip("~"),
            "context_length": item.get("context_length") if isinstance(item.get("context_length"), int) else None,
            "prompt_price": pricing.get("prompt"),
            "completion_price": pricing.get("completion"),
            "tools": isinstance(params, list) and "tools" in params,
        })
    rows.sort(key=lambda r: (r["vendor"], r["id"]))
    return rows


async def fetch_openrouter_catalog(
    *, force: bool = False, client: httpx.AsyncClient | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    """Return ``(models, stale)`` from a TTL cache of OpenRouter's public list.

    A failed refresh serves the previous list with ``stale=True``; with no
    previous list it raises ``httpx.HTTPError``.
    """
    async with _catalog_lock:
        now = time.monotonic()
        cached = _catalog_cache["models"]
        if not force and cached is not None and now - _catalog_cache["at"] < CATALOG_TTL_SECONDS:
            return cached, False
        try:
            own = client is None
            http = client or httpx.AsyncClient(timeout=20.0)
            try:
                resp = await http.get(OPENROUTER_MODELS_URL, headers={"Accept": "application/json"})
            finally:
                if own:
                    await http.aclose()
            resp.raise_for_status()
            if len(resp.content) > _CATALOG_MAX_BYTES:
                raise httpx.HTTPError("OpenRouter catalog response too large")
            models = summarize_catalog(resp.json())
        except (httpx.HTTPError, ValueError) as exc:
            if cached is not None:
                logger.warning("OpenRouter catalog refresh failed (%s); serving cached list", exc)
                return cached, True
            raise httpx.HTTPError(f"OpenRouter catalog unavailable: {exc}") from exc
        _catalog_cache.update(at=now, models=models)
        return models, False


def reset_catalog_cache() -> None:
    _catalog_cache.update(at=0.0, models=None)
