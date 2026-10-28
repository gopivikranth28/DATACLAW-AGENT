"""OpenRouter key endpoints: provision, status and rotation.

``POST /api/providers/openrouter/provision`` turns an OpenRouter management
key into an inference key for DataClaw.  The management key is read from the
request body (or ``OPENROUTER_MANAGEMENT_KEY``), held in a local variable for
the duration of the request and used only as the bearer token of the
key-management calls.  It is never written to config, logged or returned:
the body is parsed by hand so a validation error cannot echo it, and only the
created inference key (plus its hash, for later rotation) is stored, through
the same write path as ``PATCH /api/config``.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, SecretStr, ValidationError

from dataclaw.api.routers.config import apply_config_updates
from dataclaw.config.resolver import resolve
from dataclaw.providers.llm import openrouter_keys as keys
from dataclaw.providers.llm.registry import resolve_backend_config

logger = logging.getLogger(__name__)

router = APIRouter()

CONFIG_PREFIX = "llm.backends.openrouter"


class _KeyRequest(BaseModel):
    """Body of provision and rotate.  ``management_key`` is a SecretStr so
    its repr (and any validation message) never shows the value."""

    model_config = {"extra": "ignore"}

    management_key: SecretStr | None = None
    name: str | None = Field(default=None, max_length=100)
    limit_usd: float | None = None
    limit_reset: str | None = None
    expires_at: str | None = None
    # Provision only: also select OpenRouter for the LLM / decision backend.
    use_for_llm: bool = False
    use_for_decisions: bool = False


async def _parse(request: Request) -> _KeyRequest:
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="The request body must be JSON.") from None
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="The request body must be a JSON object.")
    try:
        return _KeyRequest.model_validate(body)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in error['loc'])}: {error['msg']}"
            for error in exc.errors(include_input=False, include_url=False)
        )
        raise HTTPException(status_code=422, detail=f"Invalid request: {problems}") from None


def _management_key(payload: _KeyRequest) -> str:
    value = payload.management_key.get_secret_value().strip() if payload.management_key else ""
    return value or keys.management_key_from_env()


def _http_error(exc: keys.OpenRouterKeyError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


def _key_settings(payload: _KeyRequest) -> dict[str, Any]:
    return {
        "limit_usd": keys.normalize_limit(payload.limit_usd),
        "limit_reset": keys.normalize_limit_reset(payload.limit_reset),
        "expires_at": keys.normalize_expires_at(payload.expires_at),
    }


def _stored_key_updates(created: keys.CreatedKey) -> dict[str, Any]:
    return {
        "api_key": created.key,
        "key_hash": created.hash,
        "key_name": created.name,
        "key_label": created.label,
    }


@router.post("/provision")
async def provision(request: Request) -> dict[str, Any]:
    """Create an inference key with a management key and store it."""
    payload = await _parse(request)
    management_key = _management_key(payload)
    try:
        settings = _key_settings(payload)
        name = (payload.name or "").strip() or keys.default_key_name()
        created = await keys.create_key(management_key, name=name, **settings)
    except keys.OpenRouterKeyError as exc:
        raise _http_error(exc) from None
    finally:
        del management_key

    updates: dict[str, Any] = {"llm": {"backends": {"openrouter": _stored_key_updates(created)}}}
    if payload.use_for_llm:
        updates["llm"]["backend"] = "openrouter"
    if payload.use_for_decisions:
        updates["decision"] = {"backend": "openrouter"}
    await apply_config_updates(request, updates)
    logger.info("Provisioned OpenRouter key %r (hash %s)", created.name, created.hash)
    return {
        "status": "provisioned",
        **created.public(),
        "use_for_llm": payload.use_for_llm,
        "use_for_decisions": payload.use_for_decisions,
    }


@router.get("/key-status")
async def key_status() -> dict[str, Any]:
    """Usage, limit and remaining credit of the stored inference key."""
    api_key = resolve_backend_config("openrouter").api_key
    stored = {
        "key_hash": _stored("key_hash"),
        "key_name": _stored("key_name"),
    }
    if not api_key:
        return {"configured": False, "valid": False, **stored}
    try:
        status = await keys.key_status(api_key)
    except keys.OpenRouterKeyError as exc:
        if exc.status_code == 401:
            return {"configured": True, "valid": False, "message": exc.message, **stored}
        raise _http_error(exc) from None
    return {"configured": True, "valid": True, **stored, **status}


@router.post("/rotate")
async def rotate(request: Request) -> dict[str, Any]:
    """Create a new inference key, store it, then delete the old one by hash.

    An unset limit or reset schedule is copied from the old key.  If the
    old key cannot be deleted, the new key stays in use and the response says
    so (``old_key_deleted: false``).
    """
    payload = await _parse(request)
    old_hash = _stored("key_hash")
    if not old_hash:
        raise HTTPException(
            status_code=400,
            detail="Rotation needs a key provisioned by DataClaw (no key hash is stored). Provision a key first.",
        )
    management_key = _management_key(payload)
    try:
        settings = _key_settings(payload)
        name = (payload.name or "").strip() or _stored("key_name") or keys.default_key_name()
        try:
            old = await keys.get_key(management_key, old_hash)
        except keys.OpenRouterKeyError as exc:
            if exc.status_code in (401, 403):
                raise
            old = {}
        if settings["limit_usd"] is None and payload.limit_usd is None:
            settings["limit_usd"] = keys.normalize_limit(old.get("limit"))
        if settings["limit_reset"] is None and payload.limit_reset is None:
            settings["limit_reset"] = old.get("limit_reset") if old.get("limit_reset") in keys.LIMIT_RESETS else None
        created = await keys.create_key(management_key, name=name, **settings)
        await apply_config_updates(request, {"llm": {"backends": {"openrouter": _stored_key_updates(created)}}})
        deleted, warning = True, None
        try:
            await keys.delete_key(management_key, old_hash)
        except keys.OpenRouterKeyError as exc:
            deleted = False
            warning = f"The new key is in use, but the old key could not be deleted: {exc.message}"
            logger.warning("OpenRouter key rotation: %s", warning)
    except keys.OpenRouterKeyError as exc:
        raise _http_error(exc) from None
    finally:
        del management_key
    logger.info("Rotated OpenRouter key %s → %s", old_hash, created.hash)
    return {
        "status": "rotated",
        **created.public(),
        "old_key_hash": old_hash,
        "old_key_deleted": deleted,
        "warning": warning,
    }


def _stored(name: str) -> str:
    return str(resolve(f"{CONFIG_PREFIX}.{name}", "", "") or "").strip()
