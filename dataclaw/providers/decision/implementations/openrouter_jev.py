"""OpenRouter decision backend — Jev (and other decision models) via OpenRouter.

OpenRouter serves TypeSafe's Jev on two surfaces that share one wire format
(``DecisionsRequest`` / ``DecisionsResponse`` in
https://openrouter.ai/openapi.json, checked 2026-10-26):

- the Decisions API, ``POST https://openrouter.ai/api/alpha/decisions``
  (alpha; the default here), and
- the System One API, ``POST https://openrouter.ai/api/v1/systemone``
  ("Compatible with the TypeSafe SDKs"; bare ids such as ``jev-latest`` are
  mapped onto ``typesafe/``).

Both take ``{"model", "state", "questions": {<name>: {"type": "noul" |
"choice" | "score", "instructions", "criteria"}}}`` plus OpenRouter's
optional ``provider`` routing object, and answer ``{"id", "model",
"provider", "answers", "usage": {"input_tokens", "output_tokens", "cost"}}``
with the same answer objects as TypeSafe's ``/v1/systemone``, so the
question encoding and answer parsing of ``typesafe_jev`` are reused.
Errors use OpenRouter's ``{"error": {"code", "message"}}`` shape, which
``typesafe_jev.error_message`` already reads.

Model ids: ``typesafe/jev-1.14``, ``typesafe/jev-1.13`` and the alias
``~typesafe/jev-latest``
(https://openrouter.ai/docs/guides/community/jev.md).  Jev is billed to the
OpenRouter account; input tokens only.

OpenRouter documents a 262,144-token context for Jev but runs requests over
~32,000 bytes of text in a slower, less accurate long-context mode, so the
state is still cut to TypeSafe's default limits (``typesafe_jev.fit_state``).
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

import httpx

from dataclaw.providers.decision.implementations.typesafe_jev import (
    TypeSafeAPIError,
    TypeSafeJevProvider,
    build_request_body,
)
from dataclaw.providers.decision.provider import DecisionError, DecisionQuestion
from dataclaw.providers.llm.openrouter import attribution_headers, provider_preferences, usage_cost

DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"
SYSTEMONE_URL = "https://openrouter.ai/api/v1/systemone"
ENDPOINTS = {"decisions": DECISIONS_URL, "systemone": SYSTEMONE_URL}
DEFAULT_ENDPOINT = "decisions"
DEFAULT_MODEL = "~typesafe/jev-latest"


class OpenRouterDecisionAPIError(TypeSafeAPIError):
    """An unsuccessful OpenRouter Decisions response."""

    def __init__(self, status: int, message: str, request_id: str | None = None) -> None:
        self.status = status
        self.request_id = request_id
        suffix = f" (request id {request_id})" if request_id else ""
        DecisionError.__init__(self, f"OpenRouter Decisions API error {status}: {message}{suffix}")


def _status_hint(status: int) -> str:
    if status == 401:
        return "the OpenRouter key is missing or invalid (set OPENROUTER_API_KEY or llm.backends.openrouter.api_key)"
    if status == 402:
        return "the OpenRouter account or key has no credits left"
    if status == 403:
        return "the key may not use this model (a management key cannot run models)"
    if status == 429:
        return "rate limited"
    return ""


class OpenRouterJevProvider(TypeSafeJevProvider):
    """DecisionProvider for decision models served by OpenRouter (alpha)."""

    name = "openrouter"
    service = "OpenRouter Decisions"
    retry_count_header = None

    def __init__(
        self,
        api_key: str,
        *,
        model: str = DEFAULT_MODEL,
        endpoint: str = DEFAULT_ENDPOINT,
        routing: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
        max_retries: int = 2,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if not api_key:
            raise DecisionError("An OpenRouter API key is required")
        if endpoint not in ENDPOINTS:
            raise DecisionError(f"Unknown OpenRouter decision endpoint {endpoint!r}; use one of {sorted(ENDPOINTS)}")
        super().__init__(api_key, model=model or DEFAULT_MODEL, timeout=timeout, max_retries=max_retries, transport=transport, sleep=sleep)
        # TypeSafe's URL / model-id handling does not apply here.
        self.model = (model or DEFAULT_MODEL).strip()
        self.url = ENDPOINTS[endpoint]
        self.base_url = self.url
        self._provider = provider_preferences(routing)
        self._headers = attribution_headers(headers)
        # usage.cost of the last answered request, in USD.
        self.last_cost_usd: float | None = None

    def _request_body(self, state: str | dict[str, Any], questions: list[DecisionQuestion]) -> dict[str, Any]:
        body = build_request_body(self.model, state, questions)
        if self._provider:
            body["provider"] = self._provider
        return body

    def _extra_headers(self) -> dict[str, str]:
        return dict(self._headers)

    async def _post(self, body: dict[str, Any]) -> Any:
        data = await super()._post(body)
        self.last_cost_usd = usage_cost(data.get("usage")) if isinstance(data, dict) else None
        return data

    @staticmethod
    def _status_hint(status: int) -> str:
        return _status_hint(status)

    def _error(self, status: int, message: str, request_id: str | None) -> TypeSafeAPIError:
        return OpenRouterDecisionAPIError(status, message, request_id=request_id)
