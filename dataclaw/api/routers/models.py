"""Authenticated model catalog for the Config UI.

The catalog is intentionally resolved server-side: saved credentials can stay
masked in the browser, while a newly entered (not-yet-saved) key can be used to
validate access before the user picks a model.
"""

from __future__ import annotations

import asyncio
import shutil
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from dataclaw.config.resolver import resolve

router = APIRouter()

_DIRECT_BACKENDS = {"anthropic", "openai", "gemini"}
_SUPPORTED_BACKENDS = _DIRECT_BACKENDS | {"codex"}


class ModelCatalogRequest(BaseModel):
    backend: str
    api_key: str | None = None
    base_url: str | None = None
    auth_mode: str | None = None


class ModelOption(BaseModel):
    id: str
    label: str


class ModelCatalogResponse(BaseModel):
    backend: str
    authenticated: bool
    models: list[ModelOption]
    message: str | None = None


class _ProviderCatalogError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


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
    if backend not in _SUPPORTED_BACKENDS:
        raise HTTPException(status_code=400, detail=f"Model discovery is not supported for backend {backend!r}")

    try:
        if backend == "codex":
            return await _discover_codex_models(payload)

        api_key = _resolve_api_key(backend, payload.api_key)
        if not api_key:
            return _missing_credentials(backend)

        if backend == "anthropic":
            models = await _fetch_anthropic_models(api_key)
        elif backend == "openai":
            base_url = _resolve_openai_base_url(payload.base_url)
            models = await _fetch_openai_models(api_key, base_url)
        else:
            models = await _fetch_gemini_models(api_key)

        return ModelCatalogResponse(backend=backend, authenticated=True, models=models)
    except _ProviderCatalogError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


async def _discover_codex_models(payload: ModelCatalogRequest) -> ModelCatalogResponse:
    auth_mode = payload.auth_mode or resolve("llm.codex.auth_mode", "CODEX_AUTH_MODE", "default")
    if auth_mode == "api_key":
        api_key = _resolve_api_key("codex", payload.api_key)
        if not api_key:
            return _missing_credentials("codex")
        models = await _fetch_openai_models(api_key, "https://api.openai.com/v1")
        return ModelCatalogResponse(backend="codex", authenticated=True, models=models)

    if auth_mode != "default":
        raise HTTPException(status_code=400, detail=f"Unknown Codex auth mode: {auth_mode!r}")

    # Validate the OAuth state before starting app-server. model/list can return
    # cached metadata even when no account is signed in, which would make the UI
    # incorrectly report that authentication succeeded.
    from dataclaw.auth.codex_bridge import resolve_codex_credentials

    try:
        resolve_codex_credentials(auth_mode="default")
    except ValueError:
        return ModelCatalogResponse(
            backend="codex",
            authenticated=False,
            models=[],
            message="Log in to Codex to load available models.",
        )

    models = await _fetch_codex_oauth_models()
    return ModelCatalogResponse(backend="codex", authenticated=True, models=models)


def _resolve_api_key(backend: str, supplied: str | None) -> str:
    if supplied and not _looks_masked(supplied):
        return supplied.strip()

    config = {
        "anthropic": ("llm.anthropic.api_key", "ANTHROPIC_API_KEY"),
        "openai": ("llm.openai.api_key", "OPENAI_API_KEY"),
        "gemini": ("llm.gemini.api_key", "GOOGLE_API_KEY"),
        "codex": ("llm.codex.api_key", "OPENAI_API_KEY"),
    }
    dot_path, env_var = config[backend]
    return str(resolve(dot_path, env_var, "") or "").strip()


def _resolve_openai_base_url(supplied: str | None) -> str:
    if supplied is not None:
        value = supplied.strip()
    else:
        value = str(resolve("llm.openai.base_url", "OPENAI_BASE_URL", "") or "").strip()
    return (value or "https://api.openai.com/v1").rstrip("/")


def _looks_masked(value: str) -> bool:
    return value == "***" or "..." in value


def _missing_credentials(backend: str) -> ModelCatalogResponse:
    provider = {
        "anthropic": "Anthropic",
        "openai": "OpenAI",
        "gemini": "Gemini",
        "codex": "OpenAI",
    }[backend]
    return ModelCatalogResponse(
        backend=backend,
        authenticated=False,
        models=[],
        message=f"Enter a {provider} API key to load available models.",
    )


async def _fetch_anthropic_models(api_key: str) -> list[ModelOption]:
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }
    options: list[ModelOption] = []
    after_id: str | None = None

    async with httpx.AsyncClient(timeout=20.0) as client:
        for _ in range(10):
            params: dict[str, Any] = {"limit": 1000}
            if after_id:
                params["after_id"] = after_id
            data = await _get_provider_json(
                client,
                "https://api.anthropic.com/v1/models",
                provider="Anthropic",
                headers=headers,
                params=params,
            )
            for item in data.get("data", []):
                model_id = str(item.get("id") or "").strip()
                if model_id:
                    options.append(_model_option(model_id, item.get("display_name")))
            if not data.get("has_more"):
                break
            next_id = str(data.get("last_id") or "").strip()
            if not next_id or next_id == after_id:
                break
            after_id = next_id

    return _deduplicate(options)


async def _fetch_openai_models(api_key: str, base_url: str) -> list[ModelOption]:
    async with httpx.AsyncClient(timeout=20.0) as client:
        data = await _get_provider_json(
            client,
            f"{base_url.rstrip('/')}/models",
            provider="OpenAI",
            headers={"Authorization": f"Bearer {api_key}"},
        )

    options = [
        ModelOption(id=model_id, label=model_id)
        for item in data.get("data", [])
        if (model_id := str(item.get("id") or "").strip())
    ]
    return sorted(_deduplicate(options), key=lambda item: item.id.lower())


async def _fetch_gemini_models(api_key: str) -> list[ModelOption]:
    headers = {"x-goog-api-key": api_key}
    options: list[ModelOption] = []
    page_token: str | None = None

    async with httpx.AsyncClient(timeout=20.0) as client:
        for _ in range(10):
            params: dict[str, Any] = {"pageSize": 1000}
            if page_token:
                params["pageToken"] = page_token
            data = await _get_provider_json(
                client,
                "https://generativelanguage.googleapis.com/v1beta/models",
                provider="Gemini",
                headers=headers,
                params=params,
            )
            for item in data.get("models", []):
                methods = item.get("supportedGenerationMethods") or []
                if "generateContent" not in methods:
                    continue
                model_id = str(item.get("baseModelId") or item.get("name") or "").strip()
                if model_id.startswith("models/"):
                    model_id = model_id.removeprefix("models/")
                if model_id:
                    options.append(_model_option(model_id, item.get("displayName")))
            next_token = str(data.get("nextPageToken") or "").strip()
            if not next_token or next_token == page_token:
                break
            page_token = next_token

    return _deduplicate(options)


async def _fetch_codex_oauth_models() -> list[ModelOption]:
    try:
        from codex_app_server import AppServerConfig
        from dataclaw.auth.codex_bridge import prepare_codex_env

        codex_bin = str(resolve("llm.codex.codex_bin", "CODEX_BIN", "") or "").strip()
        if not codex_bin:
            codex_bin = shutil.which("codex") or ""
        config = AppServerConfig(
            codex_bin=codex_bin or None,
            env=prepare_codex_env(),
        )
        data = await asyncio.to_thread(_fetch_codex_model_pages, config)
    except Exception as exc:
        raise _ProviderCatalogError(502, "Unable to load models from Codex.") from exc

    options: list[ModelOption] = []
    for item in data:
        if item.get("hidden"):
            continue
        model_id = str(item.get("model") or item.get("id") or "").strip()
        if model_id:
            options.append(_model_option(model_id, item.get("displayName")))
    return _deduplicate(options)


def _fetch_codex_model_pages(config: Any) -> list[dict[str, Any]]:
    """Read the app-server model catalog without validating its full schema.

    The generated Python SDK types are tied to the Codex CLI version that
    produced them. New, unrelated model metadata (for example a reasoning
    effort added by a newer CLI) must not make the model picker unusable. The
    picker only needs a small stable subset, so validate that subset here and
    leave the rest of the response forward-compatible.
    """
    from codex_app_server import AppServerClient

    client = AppServerClient(config=config)
    items: list[dict[str, Any]] = []
    cursor: str | None = None

    try:
        client.start()
        client.initialize()
        for _ in range(20):
            params: dict[str, Any] = {"includeHidden": False}
            if cursor:
                params["cursor"] = cursor
            response = client._request_raw("model/list", params)
            if not isinstance(response, dict) or not isinstance(response.get("data"), list):
                raise ValueError("Codex returned an invalid model list")

            for item in response["data"]:
                if isinstance(item, dict):
                    items.append(item)

            next_cursor = str(response.get("nextCursor") or "").strip()
            if not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor
    finally:
        client.close()

    return items


async def _get_provider_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    provider: str,
    headers: dict[str, str],
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        response = await client.get(url, headers=headers, params=params)
    except httpx.RequestError as exc:
        raise _ProviderCatalogError(502, f"Unable to reach {provider} to load models.") from exc

    if response.status_code in {401, 403}:
        raise _ProviderCatalogError(401, f"{provider} rejected the configured credentials.")
    if response.is_error:
        raise _ProviderCatalogError(502, f"{provider} could not return its model list.")

    try:
        data = response.json()
    except ValueError as exc:
        raise _ProviderCatalogError(502, f"{provider} returned an invalid model list.") from exc
    if not isinstance(data, dict):
        raise _ProviderCatalogError(502, f"{provider} returned an invalid model list.")
    return data


def _model_option(model_id: str, display_name: Any) -> ModelOption:
    display = str(display_name or "").strip()
    label = f"{display} ({model_id})" if display and display != model_id else model_id
    return ModelOption(id=model_id, label=label)


def _deduplicate(options: list[ModelOption]) -> list[ModelOption]:
    seen: set[str] = set()
    result: list[ModelOption] = []
    for option in options:
        if option.id in seen:
            continue
        seen.add(option.id)
        result.append(option)
    return result
