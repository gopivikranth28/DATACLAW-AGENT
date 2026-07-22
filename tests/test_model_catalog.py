"""Tests for authenticated model discovery used by the Config page."""

from __future__ import annotations

import sys
import types
from typing import Any

import httpx
import pytest
from fastapi import HTTPException

from dataclaw.api.routers import models


class _FakeAsyncClient:
    def __init__(self, responses: list[httpx.Response]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        self.calls.append({"url": url, **kwargs})
        return self.responses.pop(0)


def _install_fake_client(monkeypatch: pytest.MonkeyPatch, responses: list[httpx.Response]) -> _FakeAsyncClient:
    client = _FakeAsyncClient(responses)
    monkeypatch.setattr(models.httpx, "AsyncClient", lambda **_kwargs: client)
    return client


@pytest.mark.asyncio
async def test_missing_key_returns_unauthenticated_catalog():
    result = await models._discover_models(models.ModelCatalogRequest(backend="anthropic"))

    assert result.authenticated is False
    assert result.models == []
    assert "Anthropic API key" in (result.message or "")


@pytest.mark.asyncio
async def test_anthropic_catalog_uses_pending_key_and_paginates(monkeypatch: pytest.MonkeyPatch):
    client = _install_fake_client(
        monkeypatch,
        [
            httpx.Response(
                200,
                json={
                    "data": [{"id": "claude-new", "display_name": "Claude New"}],
                    "has_more": True,
                    "last_id": "claude-new",
                },
            ),
            httpx.Response(
                200,
                json={
                    "data": [{"id": "claude-old", "display_name": "Claude Old"}],
                    "has_more": False,
                },
            ),
        ],
    )

    result = await models._discover_models(
        models.ModelCatalogRequest(backend="anthropic", api_key="pending-secret")
    )

    assert result.authenticated is True
    assert [item.id for item in result.models] == ["claude-new", "claude-old"]
    assert result.models[0].label == "Claude New (claude-new)"
    assert client.calls[0]["headers"]["x-api-key"] == "pending-secret"
    assert client.calls[0]["headers"]["anthropic-version"] == "2023-06-01"
    assert client.calls[1]["params"]["after_id"] == "claude-new"


@pytest.mark.asyncio
async def test_openai_catalog_honors_custom_base_url_and_sorts(monkeypatch: pytest.MonkeyPatch):
    client = _install_fake_client(
        monkeypatch,
        [httpx.Response(200, json={"data": [{"id": "z-model"}, {"id": "a-model"}]})],
    )

    result = await models._discover_models(
        models.ModelCatalogRequest(
            backend="openai",
            api_key="openai-secret",
            base_url="https://example.test/v1/",
        )
    )

    assert [item.id for item in result.models] == ["a-model", "z-model"]
    assert client.calls[0]["url"] == "https://example.test/v1/models"
    assert client.calls[0]["headers"]["Authorization"] == "Bearer openai-secret"


@pytest.mark.asyncio
async def test_gemini_catalog_only_includes_generate_content_models(monkeypatch: pytest.MonkeyPatch):
    client = _install_fake_client(
        monkeypatch,
        [
            httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "name": "models/gemini-chat",
                            "baseModelId": "gemini-chat",
                            "displayName": "Gemini Chat",
                            "supportedGenerationMethods": ["generateContent"],
                        },
                        {
                            "name": "models/text-embedding",
                            "supportedGenerationMethods": ["embedContent"],
                        },
                    ],
                    "nextPageToken": "next-page",
                },
            ),
            httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "name": "models/gemini-next",
                            "displayName": "Gemini Next",
                            "supportedGenerationMethods": ["generateContent"],
                        }
                    ]
                },
            ),
        ],
    )

    result = await models._discover_models(
        models.ModelCatalogRequest(backend="gemini", api_key="gemini-secret")
    )

    assert [item.id for item in result.models] == ["gemini-chat", "gemini-next"]
    assert client.calls[0]["headers"]["x-goog-api-key"] == "gemini-secret"
    assert client.calls[1]["params"]["pageToken"] == "next-page"


@pytest.mark.asyncio
async def test_provider_auth_errors_are_safe_and_actionable(monkeypatch: pytest.MonkeyPatch):
    _install_fake_client(monkeypatch, [httpx.Response(401, json={"error": "secret detail"})])

    with pytest.raises(HTTPException) as exc_info:
        await models._discover_models(
            models.ModelCatalogRequest(backend="openai", api_key="bad-secret")
        )

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "OpenAI rejected the configured credentials."
    assert "bad-secret" not in exc_info.value.detail


@pytest.mark.asyncio
async def test_codex_oauth_requires_login_before_listing_models():
    result = await models._discover_models(
        models.ModelCatalogRequest(backend="codex", auth_mode="default")
    )

    assert result.authenticated is False
    assert result.models == []
    assert "Log in to Codex" in (result.message or "")


@pytest.mark.asyncio
async def test_codex_catalog_ignores_new_metadata_and_paginates(
    monkeypatch: pytest.MonkeyPatch,
):
    calls: list[tuple[str, dict[str, Any]]] = []

    class _FakeAppServerConfig:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

    class _FakeAppServerClient:
        def __init__(self, config: Any) -> None:
            self.config = config

        def start(self) -> None:
            pass

        def initialize(self) -> None:
            pass

        def close(self) -> None:
            pass

        def _request_raw(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
            calls.append((method, params))
            if len(calls) == 1:
                return {
                    "data": [
                        {
                            "model": "gpt-new",
                            "displayName": "GPT New",
                            "hidden": False,
                            "supportedReasoningEfforts": [
                                {"reasoningEffort": "max", "description": "Max"},
                                {"reasoningEffort": "ultra", "description": "Ultra"},
                            ],
                        },
                        {"model": "hidden-model", "hidden": True},
                    ],
                    "nextCursor": "page-2",
                }
            return {
                "data": [{"id": "gpt-fallback-id", "hidden": False}],
                "nextCursor": None,
            }

    fake_sdk = types.ModuleType("codex_app_server")
    fake_sdk.AppServerConfig = _FakeAppServerConfig
    fake_sdk.AppServerClient = _FakeAppServerClient
    monkeypatch.setitem(sys.modules, "codex_app_server", fake_sdk)
    monkeypatch.setattr(models, "resolve", lambda *_args: "")
    monkeypatch.setattr(models.shutil, "which", lambda _name: "/usr/local/bin/codex")

    result = await models._fetch_codex_oauth_models()

    assert [item.id for item in result] == ["gpt-new", "gpt-fallback-id"]
    assert result[0].label == "GPT New (gpt-new)"
    assert calls == [
        ("model/list", {"includeHidden": False}),
        ("model/list", {"includeHidden": False, "cursor": "page-2"}),
    ]


@pytest.mark.asyncio
async def test_unsupported_backend_is_rejected():
    with pytest.raises(HTTPException) as exc_info:
        await models._discover_models(models.ModelCatalogRequest(backend="mock"))

    assert exc_info.value.status_code == 400
