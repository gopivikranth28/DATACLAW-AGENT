"""OpenRouter: model catalog, routing preferences and reasoning-state helpers.

Shared by the ``openrouter`` LLM backend (``backends.py`` and
``implementations/openrouter_chat.py``), the ``openrouter`` decision backend
and the key-provisioning API.  Wire details were checked on 2026-10-26
against OpenRouter's OpenAPI spec (https://openrouter.ai/openapi.json, API
1.0.0) and these pages:

- Models: ``GET /api/v1/models`` is public.  Each entry has ``id``
  (``vendor/model``, dots in versions: ``anthropic/claude-opus-5.5``),
  ``name``, ``context_length``, ``top_provider.max_completion_tokens``,
  ``supported_parameters``, ``architecture.input_modalities`` /
  ``output_modalities``, ``pricing.prompt`` / ``pricing.completion`` (USD
  per token, as strings; ``"-1"`` for routers whose price varies) and an
  optional ``reasoning`` object (``supported_efforts``, ``mandatory``,
  ``default_effort``).
  https://openrouter.ai/docs/guides/best-practices/reasoning-tokens.md#discovering-per-model-reasoning-options
- Reasoning: request ``reasoning: {effort | max_tokens, exclude, enabled}``;
  responses carry ``reasoning_details`` (``choices[].message`` or, when
  streaming, ``choices[].delta``) which must be sent back unchanged on the
  assistant message of a tool loop.
  https://openrouter.ai/docs/guides/best-practices/reasoning-tokens.md#preserving-reasoning
- Provider routing: request ``provider: {order, only, ignore, sort,
  max_price, quantizations, allow_fallbacks, require_parameters,
  data_collection, zdr}``; model fallbacks: request ``models: [...]``.
  https://openrouter.ai/docs/guides/routing/provider-selection.md,
  https://openrouter.ai/docs/guides/routing/model-fallbacks.md
- Usage accounting is automatic: every response's ``usage`` carries
  ``cost`` (USD).  ``usage: {include: true}`` is deprecated and has no
  effect, so it is not sent.
  https://openrouter.ai/docs/cookbook/administration/usage-accounting.md
- Attribution headers: ``HTTP-Referer`` (required for attribution) and
  ``X-OpenRouter-Title`` (``X-Title`` is still accepted).
  https://openrouter.ai/docs/app-attribution.md
- The Responses API (``POST /api/v1/responses``) is tagged ``beta`` in the
  spec, so the backend uses Chat Completions only.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

import httpx

from dataclaw.providers.llm.catalog import EFFORT_ORDER, ModelInfo

if TYPE_CHECKING:
    from dataclaw.providers.llm.registry import ResolvedBackendConfig

logger = logging.getLogger(__name__)

OPENROUTER_API_BASE = "https://openrouter.ai/api/v1"
OPENROUTER_API_KEY_ENV = "OPENROUTER_API_KEY"

# Checked against the live public catalog on 2026-10-26.  The utility default
# is the cheapest current Claude ($0.10 / $0.50 per million tokens): tools,
# structured outputs and optional reasoning, with a 1M-token context.
DEFAULT_MODEL = "anthropic/claude-opus-5.5"
UTILITY_DEFAULT_MODEL = "anthropic/claude-haiku-5.5"

APP_URL = "https://github.com/gopivikranth28/DATACLAW-AGENT"
APP_TITLE = "DataClaw"
DEFAULT_ATTRIBUTION_HEADERS: dict[str, str] = {
    "HTTP-Referer": APP_URL,
    "X-OpenRouter-Title": APP_TITLE,
}

CATALOG_TTL_SECONDS = 3600.0
# After a failed catalog fetch, wait this long before trying again so a
# network outage does not add a request to every turn.
CATALOG_RETRY_SECONDS = 60.0

# Variants that are not served by synchronous Chat Completions.
_EXCLUDED_VARIANTS = (":batch",)

# Key that stores a streamed reasoning_details fragment's ``index``.  LangChain
# merges list items that share an integer ``index`` by concatenating every
# string field (``format``, ``signature``, ...), which corrupts the details,
# so fragments are kept apart and joined by ``collapse_reasoning_details``.
FRAGMENT_INDEX_KEY = "_or_index"

_CONCATENATED_FIELDS = ("text", "summary", "data")


def attribution_headers(configured: dict[str, str] | None = None) -> dict[str, str]:
    """Default attribution headers with configured ones on top.

    A header configured with an empty value is removed, so a user can opt
    out of attribution (the headers UI saves removed headers as "").
    """
    headers = dict(DEFAULT_ATTRIBUTION_HEADERS)
    for name, value in (configured or {}).items():
        if not name:
            continue
        if value in (None, ""):
            headers.pop(name, None)
        else:
            headers[str(name)] = str(value)
    return headers


# ── Catalog ─────────────────────────────────────────────────────────────────

_catalog: dict[str, dict[str, Any]] | None = None
_catalog_loaded_at = 0.0
_catalog_failed_at = 0.0


class OpenRouterCatalogError(Exception):
    """The OpenRouter model list could not be loaded."""


def set_catalog(items: list[dict[str, Any]], *, loaded_at: float | None = None) -> None:
    """Replace the cached catalog (``/api/v1/models`` ``data`` entries)."""
    global _catalog, _catalog_loaded_at, _catalog_failed_at
    _catalog = {str(item["id"]): item for item in items if isinstance(item, dict) and item.get("id")}
    _catalog_loaded_at = time.monotonic() if loaded_at is None else loaded_at
    _catalog_failed_at = 0.0


def clear_catalog() -> None:
    global _catalog, _catalog_loaded_at, _catalog_failed_at
    _catalog = None
    _catalog_loaded_at = 0.0
    _catalog_failed_at = 0.0


def _catalog_fresh() -> bool:
    return _catalog is not None and time.monotonic() - _catalog_loaded_at < CATALOG_TTL_SECONDS


async def fetch_catalog(
    *,
    base_url: str = OPENROUTER_API_BASE,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[dict[str, Any]]:
    """GET the public model list.  No credentials are sent: it needs none."""
    try:
        async with httpx.AsyncClient(timeout=20.0, transport=transport) as client:
            response = await client.get(f"{base_url.rstrip('/')}/models", headers=DEFAULT_ATTRIBUTION_HEADERS)
    except httpx.HTTPError as exc:
        raise OpenRouterCatalogError(f"Unable to reach OpenRouter to load models ({type(exc).__name__}).") from None
    if response.is_error:
        raise OpenRouterCatalogError(f"OpenRouter could not return its model list (HTTP {response.status_code}).")
    try:
        data = response.json()
    except ValueError:
        raise OpenRouterCatalogError("OpenRouter returned an invalid model list.") from None
    items = data.get("data") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise OpenRouterCatalogError("OpenRouter returned an invalid model list.")
    return [item for item in items if isinstance(item, dict)]


async def ensure_catalog(*, force: bool = False, transport: httpx.AsyncBaseTransport | None = None) -> bool:
    """Load the catalog if it is missing or older than the TTL.

    Returns True when a catalog (possibly stale) is available.  Failures are
    logged, not raised: callers then treat every optional request parameter
    as unsupported.
    """
    global _catalog_failed_at
    if not force and _catalog_fresh():
        return True
    if not force and _catalog_failed_at and time.monotonic() - _catalog_failed_at < CATALOG_RETRY_SECONDS:
        return _catalog is not None
    try:
        set_catalog(await fetch_catalog(transport=transport))
        return True
    except OpenRouterCatalogError as exc:
        _catalog_failed_at = time.monotonic()
        logger.warning("%s Optional OpenRouter request parameters are skipped until it loads.", exc)
        return _catalog is not None


def cached_model(model_id: str) -> dict[str, Any] | None:
    """The catalog entry for ``model_id`` (variant suffixes such as
    ``:nitro`` fall back to the base model), or None."""
    if not _catalog or not model_id:
        return None
    entry = _catalog.get(model_id)
    if entry is None and ":" in model_id:
        entry = _catalog.get(model_id.split(":", 1)[0])
    return entry


def supported_parameters(entry: dict[str, Any] | None) -> frozenset[str]:
    params = entry.get("supported_parameters") if isinstance(entry, dict) else None
    return frozenset(str(p) for p in params) if isinstance(params, list) else frozenset()


def model_reasoning_efforts(entry: dict[str, Any] | None) -> list[str]:
    """Efforts the model accepts, lowest first.

    ``reasoning.supported_efforts`` null means every gateway value, absent
    means the model has no effort control; ``mandatory`` models reject
    ``none``.
    """
    reasoning = entry.get("reasoning") if isinstance(entry, dict) else None
    if not isinstance(reasoning, dict) or "supported_efforts" not in reasoning:
        return []
    raw = reasoning.get("supported_efforts")
    efforts = list(EFFORT_ORDER) if raw is None else [str(e) for e in raw if isinstance(e, str)]
    if reasoning.get("mandatory"):
        efforts = [e for e in efforts if e != "none"]
    known = [e for e in EFFORT_ORDER if e in efforts]
    return known + [e for e in efforts if e not in EFFORT_ORDER]


def model_info(entry: dict[str, Any]) -> ModelInfo | None:
    """Map one ``/api/v1/models`` entry onto ModelInfo (None to skip it)."""
    model_id = str(entry.get("id") or "").strip()
    if not model_id or model_id.endswith(_EXCLUDED_VARIANTS):
        return None
    architecture = entry.get("architecture") if isinstance(entry.get("architecture"), dict) else {}
    outputs = architecture.get("output_modalities")
    if isinstance(outputs, list) and outputs and "text" not in outputs:
        return None
    params = supported_parameters(entry)
    top = entry.get("top_provider") if isinstance(entry.get("top_provider"), dict) else {}
    pricing = entry.get("pricing") if isinstance(entry.get("pricing"), dict) else {}
    efforts = model_reasoning_efforts(entry)
    inputs = architecture.get("input_modalities") or []
    name = str(entry.get("name") or "").strip()
    return ModelInfo(
        id=model_id,
        label=f"{name} ({model_id})" if name and name != model_id else model_id,
        context_window=_positive_int(entry.get("context_length")) or _positive_int(top.get("context_length")),
        max_output=_positive_int(top.get("max_completion_tokens")),
        supports_tools="tools" in params,
        supports_reasoning="reasoning" in params,
        reasoning_efforts=efforts if "reasoning" in params else [],
        supports_vision="image" in inputs,
        supports_structured_output=native_structured_output(entry),
        transport="openai_chat",
        prompt_price_per_mtok=_price_per_mtok(pricing.get("prompt")),
        completion_price_per_mtok=_price_per_mtok(pricing.get("completion")),
    )


def native_structured_output(entry: dict[str, Any] | None) -> bool:
    """Whether ``response_format: json_schema`` can be sent.

    OpenRouter lists json_schema support as the ``structured_outputs``
    parameter (https://openrouter.ai/docs/guides/features/structured-outputs.md);
    ``response_format`` alone may only mean ``json_object``.
    """
    return "structured_outputs" in supported_parameters(entry)


async def list_models(cfg: "ResolvedBackendConfig") -> list[ModelInfo]:
    """Catalog entries for the settings UI (``LLMBackendSpec.list_models``)."""
    from dataclaw.providers.llm.model_listing import ModelCatalogError

    if not await ensure_catalog() or _catalog is None:
        raise ModelCatalogError(502, "Unable to load the OpenRouter model list.")
    infos = [info for entry in _catalog.values() if (info := model_info(entry)) is not None]
    return sorted(infos, key=lambda info: info.id.lower())


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _price_per_mtok(value: Any) -> float | None:
    try:
        per_token = float(value)
    except (TypeError, ValueError):
        return None
    if per_token < 0 or per_token != per_token:  # "-1": the price varies (routers)
        return None
    return round(per_token * 1_000_000, 6)


# ── Request fields ──────────────────────────────────────────────────────────

_LIST_PREFERENCES = ("order", "only", "ignore", "quantizations")
_BOOL_PREFERENCES = ("allow_fallbacks", "require_parameters")
_SORT_VALUES = frozenset({"price", "throughput", "latency"})
_MAX_PRICE_KEYS = ("prompt", "completion", "request", "image", "audio")


def provider_preferences(routing: Any) -> dict[str, Any]:
    """The ``provider`` request object for ``llm.backends.openrouter.routing``.

    Only settings the user changed are sent, so the defaults leave
    OpenRouter's (and the account's) routing untouched.  ``zdr`` can only
    enforce zero data retention, and ``data_collection`` is only sent as
    ``deny``: "allow" is the request default and must not override a
    stricter account-wide setting.
    """
    if not isinstance(routing, dict):
        return {}
    prefs: dict[str, Any] = {}
    if str(routing.get("data_collection") or "").strip().lower() == "deny":
        prefs["data_collection"] = "deny"
    if routing.get("zdr") is True:
        prefs["zdr"] = True
    for key in _LIST_PREFERENCES:
        values = _string_list(routing.get(key))
        if values:
            prefs[key] = values
    for key in _BOOL_PREFERENCES:
        if isinstance(routing.get(key), bool):
            prefs[key] = routing[key]
    sort = routing.get("sort")
    if isinstance(sort, str) and sort.strip().lower() in _SORT_VALUES:
        prefs["sort"] = sort.strip().lower()
    elif isinstance(sort, dict) and sort:
        prefs["sort"] = sort
    max_price = routing.get("max_price")
    if isinstance(max_price, dict):
        prices = {
            k: float(v) for k, v in max_price.items()
            if k in _MAX_PRICE_KEYS and isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0
        }
        if prices:
            prefs["max_price"] = prices
    return prefs


def fallback_models(routing: Any, model: str) -> list[str]:
    """The ``models`` request list: ``model`` first, then the fallbacks.

    The spec documents ``models`` as an ordered list tried in turn and the
    docs' examples send it without ``model``; the OpenAI client always sends
    ``model``, so the primary is repeated at the head of the list to keep the
    order unambiguous.  Empty when no fallbacks are configured.
    """
    if not isinstance(routing, dict):
        return []
    extra = [m for m in _string_list(routing.get("models")) if m != model]
    return [model, *extra] if extra else []


def routing_request_fields(routing: Any, model: str) -> dict[str, Any]:
    """Body fields for the routing settings (``provider`` and ``models``)."""
    fields: dict[str, Any] = {}
    prefs = provider_preferences(routing)
    if prefs:
        fields["provider"] = prefs
    models = fallback_models(routing, model)
    if models:
        fields["models"] = models
    return fields


def reasoning_request(entry: dict[str, Any] | None, effort: str | None) -> dict[str, Any] | None:
    """The unified ``reasoning`` object for ``effort``, or None to omit it.

    Sent only when the model lists ``reasoning`` in ``supported_parameters``.
    An effort the model lacks maps to the nearest one it offers.
    """
    from dataclaw.providers.llm.catalog import nearest_effort

    if not effort or "reasoning" not in supported_parameters(entry):
        return None
    efforts = model_reasoning_efforts(entry)
    if efforts:
        chosen = nearest_effort(effort, efforts)
        if chosen is None:
            return None
        effort = chosen
    return {"effort": effort}


def usage_cost(usage: Any) -> float | None:
    """``usage.cost`` (USD) from a Chat Completions response or chunk."""
    cost = usage.get("cost") if isinstance(usage, dict) else None
    if isinstance(cost, bool) or not isinstance(cost, (int, float)):
        return None
    return float(cost)


# ── Reasoning details ───────────────────────────────────────────────────────


def as_fragment(detail: dict[str, Any]) -> dict[str, Any]:
    """A streamed reasoning_details item, safe from LangChain's chunk merging."""
    fragment = {k: v for k, v in detail.items() if k != "index"}
    if "index" in detail:
        fragment[FRAGMENT_INDEX_KEY] = detail["index"]
    return fragment


def collapse_reasoning_details(fragments: Any) -> list[dict[str, Any]]:
    """Join streamed reasoning_details fragments into complete items.

    Fragments with the same ``index`` (or, without one, consecutive
    fragments of the same type and id) form one item: their ``text`` /
    ``summary`` / ``data`` are concatenated in order and other fields take
    the first non-empty value, except ``signature``, which arrives last.
    Complete (non-streamed) items pass through unchanged.
    """
    items: list[dict[str, Any]] = []
    by_index: dict[tuple[Any, Any], dict[str, Any]] = {}
    for raw in fragments if isinstance(fragments, list) else []:
        if not isinstance(raw, dict):
            continue
        fragment = dict(raw)
        index = fragment.pop(FRAGMENT_INDEX_KEY, fragment.get("index"))
        key = (index, fragment.get("type"))
        if index is not None and key in by_index:
            _merge_fragment(by_index[key], fragment)
            continue
        previous = items[-1] if items else None
        if (
            index is None
            and previous is not None
            and "index" not in previous
            and previous.get("type") == fragment.get("type")
            and (previous.get("id") in (None, "") or fragment.get("id") in (None, "") or previous.get("id") == fragment.get("id"))
        ):
            _merge_fragment(previous, fragment)
            continue
        item = dict(fragment)
        if index is not None:
            item["index"] = index
            by_index[key] = item
        items.append(item)
    return items


def _merge_fragment(item: dict[str, Any], fragment: dict[str, Any]) -> None:
    for key, value in fragment.items():
        if value is None or key == "index":
            continue
        current = item.get(key)
        if key in _CONCATENATED_FIELDS and isinstance(value, str) and isinstance(current, str):
            item[key] = current + value
        elif key == "signature" or current in (None, ""):
            item[key] = value


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [part for part in value.split(",")]
    if not isinstance(value, list):
        return []
    return [s for item in value if isinstance(item, str) and (s := item.strip())]
