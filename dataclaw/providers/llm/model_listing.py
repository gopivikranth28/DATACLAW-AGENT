"""Provider model-list fetchers used by the backend registry's catalog.

Each fetcher returns ``ModelInfo`` entries: ids and display names come from
the provider, capability metadata from ``catalog.enrich_model``.  Errors are
raised as ``ModelCatalogError`` with a message safe to show in the UI (it
never echoes credentials or provider error bodies).
"""

from __future__ import annotations

import asyncio
import shutil
from typing import Any

import httpx

from dataclaw.config.resolver import resolve
from dataclaw.providers.llm.catalog import ModelInfo, enrich_model


class ModelCatalogError(Exception):
    """The provider's model list could not be loaded."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class ModelCatalogUnauthenticated(Exception):
    """Credentials are missing; ``message`` tells the user what to do."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


async def fetch_anthropic_models(api_key: str) -> list[ModelInfo]:
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }
    options: list[ModelInfo] = []
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
                    options.append(
                        enrich_model(
                            model_id,
                            _label(model_id, item.get("display_name")),
                            transport="anthropic",
                            reported=_anthropic_reported(item),
                        )
                    )
            if not data.get("has_more"):
                break
            next_id = str(data.get("last_id") or "").strip()
            if not next_id or next_id == after_id:
                break
            after_id = next_id

    return deduplicate(options)


def _anthropic_reported(item: dict[str, Any]) -> dict[str, Any]:
    # Newer Models API responses include limits; use them when present.
    reported: dict[str, Any] = {}
    if isinstance(item.get("max_input_tokens"), int):
        reported["context_window"] = item["max_input_tokens"]
    if isinstance(item.get("max_tokens"), int):
        reported["max_output"] = item["max_tokens"]
    return reported


async def fetch_openai_models(
    api_key: str,
    base_url: str,
    *,
    provider: str = "OpenAI",
    headers: dict[str, str] | None = None,
    transport: str = "openai_responses",
) -> list[ModelInfo]:
    """GET {base_url}/models — OpenAI and every OpenAI-compatible server."""
    request_headers = dict(headers or {})
    if api_key:
        request_headers["Authorization"] = f"Bearer {api_key}"
    async with httpx.AsyncClient(timeout=20.0) as client:
        data = await _get_provider_json(
            client,
            f"{base_url.rstrip('/')}/models",
            provider=provider,
            headers=request_headers,
        )

    options = [
        enrich_model(
            model_id,
            _label(model_id, item.get("name") if isinstance(item, dict) else None),
            transport=transport,
            reported=_openai_compatible_reported(item),
        )
        for item in data.get("data", [])
        if isinstance(item, dict) and (model_id := str(item.get("id") or "").strip())
    ]
    return sorted(deduplicate(options), key=lambda item: item.id.lower())


def _openai_compatible_reported(item: dict[str, Any]) -> dict[str, Any]:
    # OpenAI omits limits; gateways such as OpenRouter and Groq report a
    # context window under one of these names.
    for key in ("context_length", "context_window", "max_context_length"):
        if isinstance(item.get(key), int):
            return {"context_window": item[key]}
    return {}


async def fetch_gemini_models(api_key: str) -> list[ModelInfo]:
    headers = {"x-goog-api-key": api_key}
    options: list[ModelInfo] = []
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
                    reported: dict[str, Any] = {}
                    if isinstance(item.get("inputTokenLimit"), int):
                        reported["context_window"] = item["inputTokenLimit"]
                    if isinstance(item.get("outputTokenLimit"), int):
                        reported["max_output"] = item["outputTokenLimit"]
                    options.append(
                        enrich_model(
                            model_id,
                            _label(model_id, item.get("displayName")),
                            transport="gemini",
                            reported=reported,
                        )
                    )
            next_token = str(data.get("nextPageToken") or "").strip()
            if not next_token or next_token == page_token:
                break
            page_token = next_token

    return deduplicate(options)


async def fetch_codex_oauth_models() -> list[ModelInfo]:
    try:
        from codex_app_server import AppServerConfig
        from dataclaw.auth.codex_bridge import prepare_codex_env

        codex_bin = str(
            resolve("llm.backends.codex.codex_bin", "CODEX_BIN", "")
            or resolve("llm.codex.codex_bin", "CODEX_BIN", "")
            or ""
        ).strip()
        if not codex_bin:
            codex_bin = shutil.which("codex") or ""
        config = AppServerConfig(
            codex_bin=codex_bin or None,
            env=prepare_codex_env(),
        )
        data = await asyncio.to_thread(_fetch_codex_model_pages, config)
    except Exception as exc:
        raise ModelCatalogError(502, "Unable to load models from Codex.") from exc

    options: list[ModelInfo] = []
    for item in data:
        if item.get("hidden"):
            continue
        model_id = str(item.get("model") or item.get("id") or "").strip()
        if model_id:
            options.append(
                enrich_model(
                    model_id,
                    _label(model_id, item.get("displayName")),
                    transport="codex",
                    reported=_codex_reported(item),
                )
            )
    return deduplicate(options)


def _codex_reported(item: dict[str, Any]) -> dict[str, Any]:
    efforts = [
        str(entry.get("reasoningEffort"))
        for entry in item.get("supportedReasoningEfforts") or []
        if isinstance(entry, dict) and entry.get("reasoningEffort")
    ]
    return {"supports_reasoning": True, "reasoning_efforts": efforts} if efforts else {}


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
        raise ModelCatalogError(502, f"Unable to reach {provider} to load models.") from exc

    if response.status_code in {401, 403}:
        raise ModelCatalogError(401, f"{provider} rejected the configured credentials.")
    if response.is_error:
        raise ModelCatalogError(502, f"{provider} could not return its model list.")

    try:
        data = response.json()
    except ValueError as exc:
        raise ModelCatalogError(502, f"{provider} returned an invalid model list.") from exc
    if not isinstance(data, dict):
        raise ModelCatalogError(502, f"{provider} returned an invalid model list.")
    return data


def _label(model_id: str, display_name: Any) -> str:
    display = str(display_name or "").strip()
    return f"{display} ({model_id})" if display and display != model_id else model_id


def deduplicate(options: list[ModelInfo]) -> list[ModelInfo]:
    seen: set[str] = set()
    result: list[ModelInfo] = []
    for option in options:
        if option.id in seen:
            continue
        seen.add(option.id)
        result.append(option)
    return result
