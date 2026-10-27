"""OpenClaw model-provider endpoints (OpenRouter).

- ``GET  /api/openclaw/model`` — primary model, whether an OpenRouter
  credential is configured (boolean only), and the primary's routing params.
- ``POST /api/openclaw/model`` — store the key, set the primary model, write
  per-model routing / response-cache params.
- ``GET  /api/openclaw/openrouter/models`` — TTL-cached proxy of OpenRouter's
  public model list, so the browser never calls a third party.

See :mod:`dataclaw_openclaw.openrouter_config` for the verified OpenClaw
mechanics. The API key is never logged, echoed, or returned.
"""

from __future__ import annotations

import asyncio
import logging
import os

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError

from dataclaw_openclaw import openrouter_config as orc
from dataclaw_openclaw.install_router import _get_openclaw_config, _openclaw_argv

logger = logging.getLogger(__name__)

router = APIRouter()

# Serialize writes: two concurrent submits would interleave CLI config writes.
_write_lock = asyncio.Lock()


@router.get("/model")
async def get_model(request: Request):
    argv = _openclaw_argv(_get_openclaw_config(request))
    return await orc.read_model_state(argv)


def _parse_body(raw: object) -> orc.ModelConfigRequest:
    """Validate without FastAPI's default 422, whose ``input`` echoes the body
    (and with it the API key)."""
    try:
        return orc.ModelConfigRequest.model_validate(raw)
    except ValidationError as exc:
        errors = [
            {"loc": list(err.get("loc", ())), "msg": orc.redact(str(err.get("msg", "")))}
            for err in exc.errors(include_url=False, include_input=False, include_context=False)
        ]
        raise HTTPException(status_code=422, detail=errors) from None


@router.post("/model")
async def set_model(request: Request):
    try:
        raw = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="Request body must be JSON") from None
    body = _parse_body(raw)
    argv = _openclaw_argv(_get_openclaw_config(request))
    _, upstream = orc.normalize_model_ref(body.model)

    warnings: list[str] = []
    try:
        catalog, _stale = await orc.fetch_openrouter_catalog()
    except httpx.HTTPError:
        catalog = None
        warnings.append("OpenRouter's model list is unreachable; the model id was not checked against it.")
    if catalog is not None and upstream not in {row["id"] for row in catalog}:
        raise HTTPException(status_code=400, detail=f"Unknown OpenRouter model: {upstream}")

    api_key = body.api_key
    if api_key is None:
        env_key = os.environ.get(orc.API_KEY_ENV_VAR, "").strip()
        if env_key:
            try:
                api_key = orc.validate_api_key(env_key)
            except ValueError as exc:
                warnings.append(f"Ignoring {orc.API_KEY_ENV_VAR} from the environment: {exc}")

    async with _write_lock:
        try:
            result = await orc.apply_model_config(
                argv,
                model=body.model,
                api_key=api_key,
                routing=body.routing,
                response_cache=body.response_cache,
            )
        except orc.OpenClawCommandError as exc:
            # exc.output is redacted; still re-redact with the known key.
            detail = orc.redact(str(exc), [api_key])
            logger.warning("OpenClaw model configuration failed: %s", detail)
            raise HTTPException(status_code=502, detail=detail) from None

    state = await orc.read_model_state(argv)
    if not state["configured"]:
        warnings.append("No OpenRouter credential is configured in OpenClaw yet; add an API key or sign in.")
    return {**state, "key_updated": result["key_updated"], "warnings": warnings}


@router.get("/openrouter/models")
async def openrouter_models(refresh: bool = False):
    try:
        models, stale = await orc.fetch_openrouter_catalog(force=refresh)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    return {"models": models, "stale": stale, "count": len(models)}
