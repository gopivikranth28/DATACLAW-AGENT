"""Authenticated model catalog for the Config UI.

The catalog is intentionally resolved server-side: saved credentials can stay
masked in the browser, while a newly entered (not-yet-saved) key can be used to
validate access before the user picks a model.

Backends and their model listing come from the LLM backend registry; each
entry carries ``ModelInfo`` capability metadata (context window, reasoning
efforts, ...) so the UI can show only the controls a model supports.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from dataclaw.providers.llm.model_listing import (
    ModelCatalogError,
    ModelCatalogUnauthenticated,
)
from dataclaw.providers.llm.registry import get_llm_backend, resolve_backend_config

router = APIRouter()


class ModelCatalogRequest(BaseModel):
    backend: str
    api_key: str | None = None
    base_url: str | None = None
    auth_mode: str | None = None
    preset: str | None = None
    api: str | None = None
    headers: dict[str, str] | None = None


class ModelOption(BaseModel):
    id: str
    label: str
    context_window: int | None = None
    max_output: int | None = None
    supports_tools: bool = True
    supports_reasoning: bool = False
    reasoning_efforts: list[str] = []
    supports_vision: bool = False
    supports_structured_output: bool = False
    transport: str = ""
    prompt_price_per_mtok: float | None = None
    completion_price_per_mtok: float | None = None


class ModelCatalogResponse(BaseModel):
    backend: str
    authenticated: bool
    models: list[ModelOption]
    message: str | None = None


@router.get("")
async def get_models(backend: str) -> ModelCatalogResponse:
    """List models using credentials already saved in config or the environment."""
    return await _discover_models(ModelCatalogRequest(backend=backend))


@router.post("")
async def load_models(payload: ModelCatalogRequest) -> ModelCatalogResponse:
    """List models, optionally validating credentials currently entered in the UI."""
    return await _discover_models(payload)


async def _discover_models(payload: ModelCatalogRequest) -> ModelCatalogResponse:
    backend = payload.backend.strip().lower()
    spec = get_llm_backend(backend)
    if spec is None or spec.hidden or spec.list_models is None:
        raise HTTPException(status_code=400, detail=f"Model discovery is not supported for backend {backend!r}")

    cfg = resolve_backend_config(spec.id, _overrides(payload))
    if spec.needs_api_key(cfg) and not cfg.api_key:
        return ModelCatalogResponse(
            backend=backend,
            authenticated=False,
            models=[],
            message=f"Enter your {spec.vendor or spec.label} API key to load available models.",
        )

    try:
        models = await spec.list_models(cfg)
    except ModelCatalogUnauthenticated as exc:
        return ModelCatalogResponse(backend=backend, authenticated=False, models=[], message=exc.message)
    except ModelCatalogError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    return ModelCatalogResponse(
        backend=backend,
        authenticated=True,
        models=[ModelOption(**m.to_dict()) for m in models],
    )


def _overrides(payload: ModelCatalogRequest) -> dict[str, Any]:
    """Values typed in the UI that take precedence over saved settings.

    Masked secrets (what GET /api/config returns) mean "use the saved key".
    """
    overrides: dict[str, Any] = {}
    if payload.api_key and not _looks_masked(payload.api_key):
        overrides["api_key"] = payload.api_key.strip()
    if payload.base_url is not None:
        overrides["base_url"] = payload.base_url.strip()
    for name in ("auth_mode", "preset", "api"):
        value = getattr(payload, name)
        if value is not None:
            overrides[name] = value
    if payload.headers is not None and not any(_looks_masked(v) for v in payload.headers.values()):
        overrides["headers"] = payload.headers
    return overrides


def _looks_masked(value: str) -> bool:
    return value == "***" or "..." in value
