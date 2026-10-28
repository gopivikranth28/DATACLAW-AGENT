"""TypeSafe Jev decision backend — httpx client for ``POST /v1/systemone``.

Wire format, verified against TypeSafe's OpenAPI spec
(https://docs.typesafe.ai/api.md, spec 0.2.0) and the official Python SDK
(``typesafe-sdk`` 0.7.5, ``_schemas/models.py``, ``_core/constants.py``,
``_core/errors.py``):

- ``Authorization: Bearer <key>``, JSON body
  ``{"model", "state", "questions": {<name>: <question>}}``.
- Question types: ``noul`` (yes/no; optional ``instructions``),
  ``choice`` (``criteria``: ``{choice: description|null}``, 1-255 entries),
  ``score`` (``criteria``: ordered level descriptions, 1-10; the index is
  the score).
- Response ``{"model", "answers": {<name>: <answer>}, "usage"}``; answers
  are ``{"type":"noul","noul":p_yes}``,
  ``{"type":"choice","choice","confidence","probabilities":{choice:p}}``
  and ``{"type":"score","score":expected,"confidence","legend",
  "probabilities":{"0":p,...}}``.
- Errors: 422 is FastAPI-style ``{"detail":[{"loc","msg",...}]}``; other
  bodies are undocumented, so messages are read like the SDK does
  (``error`` / ``message`` / ``detail``).  429 and 529 (and 408/5xx) are
  retried with exponential backoff, honouring ``retry-after-ms`` /
  ``retry-after``.
- Limits (https://docs.typesafe.ai/models.md): 64k tokens per request
  (state + all questions) and 32k per question (state + one question).

Vercel AI Gateway serves the same request/response shape at
``https://ai-gateway.vercel.sh/typesafe/v1/systemone``
(https://vercel.com/docs/ai-gateway/sdks-and-apis/typesafe) with model ids
``typesafe-ai/jev`` / ``typesafe-ai/jev-1.14.0`` and the gateway key as the
bearer token.  Its ``/v1/decisions`` endpoint uses a different
(OpenAI-style) body and is not used here.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from email.utils import parsedate_to_datetime
from typing import Any, Awaitable, Callable
from urllib.parse import urlsplit, urlunsplit

import httpx

from dataclaw.providers.decision.limits import CHARS_PER_TOKEN, estimate_tokens, state_text, truncate_middle
from dataclaw.providers.decision.provider import DecisionError, DecisionQuestion, DecisionResult

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.typesafe.ai"
DEFAULT_MODEL = "jev-latest"
SYSTEM_ONE_PATH = "/v1/systemone"
VERCEL_GATEWAY_HOST = "ai-gateway.vercel.sh"
VERCEL_TYPESAFE_PREFIX = "/typesafe"

MAX_REQUEST_TOKENS = 64_000
MAX_QUESTION_TOKENS = 32_000
# The character-based estimate undercounts dense text (JSON, code, non-English);
# stay well below the documented limits.
LIMIT_SAFETY = 0.85
# Smallest state budget worth sending after the questions are accounted for.
MIN_STATE_TOKENS = 256
# Envelope (model name, braces, keys) per request and per question.
REQUEST_OVERHEAD_TOKENS = 32
QUESTION_OVERHEAD_TOKENS = 8

RETRY_STATUSES = frozenset({408, 429, 500, 502, 503, 504, 529})
BACKOFF_BASE = 0.5
BACKOFF_CAP = 5.0
MAX_RETRY_AFTER = 30.0


class TypeSafeAPIError(DecisionError):
    """An unsuccessful TypeSafe HTTP response."""

    def __init__(self, status: int, message: str, request_id: str | None = None) -> None:
        self.status = status
        self.request_id = request_id
        suffix = f" (request id {request_id})" if request_id else ""
        super().__init__(f"TypeSafe API error {status}: {message}{suffix}")


def systemone_url(base_url: str) -> str:
    """The ``/v1/systemone`` URL for a configured base URL.

    Accepts the API root with or without ``/v1``, and for Vercel AI Gateway
    either the TypeSafe-shape base (``.../typesafe``) or the generic gateway
    base (``https://ai-gateway.vercel.sh`` or ``.../v1``).
    """
    raw = (base_url or DEFAULT_BASE_URL).strip().rstrip("/")
    parts = urlsplit(raw if "://" in raw else f"https://{raw}")
    path = parts.path.rstrip("/")
    if path.endswith(SYSTEM_ONE_PATH):
        path = path[: -len(SYSTEM_ONE_PATH)]
    elif path.endswith("/v1"):
        path = path[:-3]
    if is_vercel_gateway(raw) and not path.endswith(VERCEL_TYPESAFE_PREFIX):
        path = f"{path}{VERCEL_TYPESAFE_PREFIX}"
    return urlunsplit((parts.scheme, parts.netloc, f"{path}{SYSTEM_ONE_PATH}", "", ""))


def is_vercel_gateway(base_url: str) -> bool:
    raw = (base_url or "").strip()
    host = urlsplit(raw if "://" in raw else f"https://{raw}").hostname or ""
    return host == VERCEL_GATEWAY_HOST or host.endswith(f".{VERCEL_GATEWAY_HOST}")


def wire_model(model: str, base_url: str) -> str:
    """The model id to send.

    Vercel names models ``typesafe-ai/<id>`` and documents ``typesafe-ai/jev``
    for the current version.  Assumption (not documented): TypeSafe's
    ``jev-latest`` / ``jev-preview`` aliases map to ``typesafe-ai/jev`` there.
    """
    model = (model or DEFAULT_MODEL).strip()
    if not is_vercel_gateway(base_url) or "/" in model:
        return model
    if model in {"jev-latest", "jev-preview"}:
        return "typesafe-ai/jev"
    return f"typesafe-ai/{model}"


def question_payload(question: DecisionQuestion) -> dict[str, Any]:
    """Encode one question in TypeSafe's format."""
    if question.kind == "boolean":
        return {"type": "noul", "instructions": question.prompt}
    if question.kind == "choice":
        descriptions = question.option_descriptions or {}
        return {
            "type": "choice",
            "instructions": question.prompt,
            "criteria": {option: descriptions.get(option) for option in question.options or []},
        }
    return {"type": "score", "instructions": question.prompt, "criteria": list(question.options or [])}


def build_request_body(
    model: str,
    state: str | dict[str, Any],
    questions: list[DecisionQuestion],
) -> dict[str, Any]:
    """The request body, with the state cut to fit the context limits."""
    if not questions:
        raise DecisionError("At least one question is required")
    ids = [q.id for q in questions]
    if len(set(ids)) != len(ids):
        raise DecisionError("Question ids must be unique")
    payloads = {q.id: question_payload(q) for q in questions}
    return {"model": model, "state": fit_state(state, payloads), "questions": payloads}


def fit_state(state: str | dict[str, Any], payloads: dict[str, dict[str, Any]]) -> str | dict[str, Any]:
    """Truncate ``state`` so the request stays within Jev's limits.

    Per request: state + every question <= 64k tokens; per question: state +
    that question <= 32k.  An object state that does not fit is sent as
    truncated JSON text.
    """
    question_tokens = [
        estimate_tokens(json.dumps({name: body}, ensure_ascii=False)) + QUESTION_OVERHEAD_TOKENS
        for name, body in payloads.items()
    ]
    budget = int(
        min(
            MAX_QUESTION_TOKENS * LIMIT_SAFETY - max(question_tokens),
            MAX_REQUEST_TOKENS * LIMIT_SAFETY - sum(question_tokens) - REQUEST_OVERHEAD_TOKENS,
        )
    )
    if budget < MIN_STATE_TOKENS:
        raise DecisionError(
            "The questions are too large for Jev's context limits "
            f"({MAX_REQUEST_TOKENS} tokens per request, {MAX_QUESTION_TOKENS} per question)"
        )
    text = state_text(state)
    if estimate_tokens(text) <= budget:
        return state
    logger.warning(
        "Decision state of ~%d tokens exceeds Jev's limit; truncating to ~%d tokens",
        estimate_tokens(text),
        budget,
    )
    return truncate_middle(text, budget * CHARS_PER_TOKEN)


def parse_answers(data: Any, questions: list[DecisionQuestion]) -> list[DecisionResult]:
    """Map a ``/v1/systemone`` response onto DecisionResults, in question order."""
    answers = data.get("answers") if isinstance(data, dict) else None
    if not isinstance(answers, dict):
        raise DecisionError("TypeSafe response has no answers object")
    results: list[DecisionResult] = []
    for question in questions:
        answer = answers.get(question.id)
        if not isinstance(answer, dict):
            raise DecisionError(f"TypeSafe response is missing the answer to {question.id!r}")
        try:
            results.append(_parse_answer(question, answer))
        except (KeyError, TypeError, ValueError) as exc:
            raise DecisionError(f"Unexpected TypeSafe answer for {question.id!r}: {exc}") from exc
    return results


def _parse_answer(question: DecisionQuestion, answer: dict[str, Any]) -> DecisionResult:
    expected = {"boolean": "noul", "choice": "choice", "score": "score"}[question.kind]
    if answer.get("type") != expected:
        raise ValueError(f"expected a {expected} answer, got {answer.get('type')!r}")
    if question.kind == "boolean":
        p_yes = _probability(answer["noul"])
        return DecisionResult(
            id=question.id,
            answer=p_yes >= 0.5,
            probabilities={"true": p_yes, "false": round(1.0 - p_yes, 12)},
            confidence=max(p_yes, 1.0 - p_yes),
        )
    probabilities = {str(k): _probability(v) for k, v in (answer.get("probabilities") or {}).items()}
    if question.kind == "choice":
        choice = str(answer["choice"])
        if choice not in (question.options or []):
            raise ValueError(f"choice {choice!r} is not one of the options")
        return DecisionResult(
            id=question.id,
            answer=choice,
            probabilities=probabilities or None,
            confidence=_probability(answer["confidence"]),
        )
    return DecisionResult(
        id=question.id,
        answer=float(answer["score"]),
        probabilities=probabilities or None,
        confidence=_probability(answer["confidence"]),
    )


def _probability(value: Any) -> float:
    number = float(value)
    if number != number:  # NaN
        raise ValueError("probability is NaN")
    return min(max(number, 0.0), 1.0)


def error_message(body: Any) -> str | None:
    """Read an error message the way the official SDK does."""
    if isinstance(body, str):
        return body.strip() or None
    if not isinstance(body, dict):
        return None
    error, message, detail = body.get("error"), body.get("message"), body.get("detail")
    if isinstance(error, str):
        return error
    if isinstance(error, dict) and isinstance(error.get("message"), str):
        return error["message"]
    if isinstance(message, str):
        return message
    if isinstance(detail, str):
        return detail
    if isinstance(detail, dict) and isinstance(detail.get("message"), str):
        return detail["message"]
    if isinstance(detail, list):
        parts = []
        for entry in detail:
            if isinstance(entry, dict) and isinstance(entry.get("msg"), str):
                loc = entry.get("loc")
                path = ".".join(str(p) for p in loc if p != "body") if isinstance(loc, list) else ""
                parts.append(f"{path}: {entry['msg']}" if path else entry["msg"])
        return "; ".join(parts) or None
    return None


def _status_hint(status: int) -> str:
    if status == 401:
        return "the API key is missing or invalid (set TYPESAFE_API_KEY or decision.typesafe.api_key)"
    if status == 413:
        return "the request body is larger than 32 MiB"
    if status == 429:
        return "rate limited"
    if status == 529:
        return "TypeSafe is overloaded"
    return ""


def retry_after_seconds(headers: httpx.Headers) -> float | None:
    """``retry-after-ms`` (milliseconds), then ``retry-after`` (seconds or HTTP date)."""
    raw_ms = headers.get("retry-after-ms")
    if raw_ms is not None:
        try:
            value = float(raw_ms)
            if value >= 0:
                return value / 1000.0
        except ValueError:
            pass
    raw = headers.get("retry-after")
    if raw is None:
        return None
    try:
        value = float(raw)
        return value if value >= 0 else None
    except ValueError:
        try:
            return max(0.0, parsedate_to_datetime(raw).timestamp() - time.time())
        except (TypeError, ValueError, OverflowError):
            return None


class TypeSafeJevProvider:
    """DecisionProvider backed by TypeSafe's Jev models."""

    name = "typesafe"

    def __init__(
        self,
        api_key: str,
        *,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
        max_retries: int = 2,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if not api_key:
            raise DecisionError("A TypeSafe API key is required")
        self.api_key = api_key
        self.base_url = base_url or DEFAULT_BASE_URL
        self.model = wire_model(model, self.base_url)
        self.url = systemone_url(self.base_url)
        self.timeout = float(timeout)
        self.max_retries = max(int(max_retries), 0)
        self._transport = transport
        self._sleep = sleep
        # The versioned model that answered the last request ("jev-1.14.0").
        self.last_model: str | None = None

    async def decide(
        self,
        state: str | dict[str, Any],
        questions: list[DecisionQuestion],
    ) -> list[DecisionResult]:
        body = build_request_body(self.model, state, questions)
        data = await self._post(body)
        self.last_model = str(data.get("model") or self.model) if isinstance(data, dict) else self.model
        return parse_answers(data, questions)

    async def _post(self, body: dict[str, Any]) -> Any:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(transport=self._transport, timeout=self.timeout) as client:
            for attempt in range(self.max_retries + 1):
                if attempt:
                    headers["X-TypeSafe-Retry-Count"] = str(attempt)
                try:
                    response = await client.post(self.url, json=body, headers=headers)
                except httpx.HTTPError as exc:
                    if attempt < self.max_retries:
                        await self._sleep(self._backoff(attempt))
                        continue
                    raise DecisionError(f"TypeSafe request failed: {type(exc).__name__}: {exc}") from exc

                if response.status_code in RETRY_STATUSES and attempt < self.max_retries:
                    delay = retry_after_seconds(response.headers)
                    await self._sleep(
                        min(delay, MAX_RETRY_AFTER) if delay is not None else self._backoff(attempt)
                    )
                    continue
                if response.status_code >= 400:
                    raise self._api_error(response)
                try:
                    return response.json()
                except ValueError as exc:
                    raise DecisionError("TypeSafe returned a response that is not JSON") from exc
        raise DecisionError("TypeSafe request failed")  # pragma: no cover - loop always returns or raises

    @staticmethod
    def _backoff(attempt: int) -> float:
        delay = min(BACKOFF_BASE * (2**attempt), BACKOFF_CAP)
        return delay * random.uniform(0.75, 1.25)

    @staticmethod
    def _api_error(response: httpx.Response) -> TypeSafeAPIError:
        try:
            body: Any = response.json()
        except ValueError:
            body = response.text
        message = error_message(body) or _status_hint(response.status_code) or response.reason_phrase
        hint = _status_hint(response.status_code)
        if hint and hint != message:
            message = f"{message} ({hint})"
        return TypeSafeAPIError(
            response.status_code,
            str(message)[:500],
            request_id=response.headers.get("x-typesafe-request-id"),
        )
