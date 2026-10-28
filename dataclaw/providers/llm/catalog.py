"""Model capability metadata (``ModelInfo``) for the model catalog.

Provider ``/models`` endpoints list ids (and sometimes display names) but
rarely the limits and features DataClaw needs: context window, max output,
and which reasoning-effort values a model accepts.  Those come from the
checked-in ``model_capabilities.json``, keyed by model-id prefix, and are
merged with whatever the provider reported.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CAPABILITIES_PATH = Path(__file__).with_name("model_capabilities.json")

# Reasoning-effort levels from least to most thinking. Used to pick the
# nearest supported value when a caller asks for one a model lacks.
EFFORT_ORDER: tuple[str, ...] = ("none", "minimal", "low", "medium", "high", "xhigh", "max")


@dataclass
class ModelInfo:
    """One entry in a backend's model catalog.

    ``None`` limits mean unknown.  ``reasoning_efforts`` lists the values the
    model's native reasoning control accepts; empty means either no reasoning
    control or an unverified list.  Prices are USD per million tokens, when
    the provider reports them (OpenRouter's catalog does).
    """

    id: str
    label: str = ""
    context_window: int | None = None
    max_output: int | None = None
    supports_tools: bool = True
    supports_reasoning: bool = False
    reasoning_efforts: list[str] = field(default_factory=list)
    supports_vision: bool = False
    supports_structured_output: bool = False
    transport: str = ""
    prompt_price_per_mtok: float | None = None
    completion_price_per_mtok: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_model_id(model: str) -> str:
    """Lower-case, last path segment: ``models/gemini-x`` and ``openai/gpt-x``
    resolve to the vendor's own id."""
    return (model or "").strip().lower().rsplit("/", 1)[-1]


@lru_cache(maxsize=1)
def _capability_table() -> dict[str, dict[str, Any]]:
    try:
        data = json.loads(_CAPABILITIES_PATH.read_text())
    except (OSError, ValueError):
        logger.exception("Could not read %s", _CAPABILITIES_PATH)
        return {}
    models = data.get("models") if isinstance(data, dict) else None
    if not isinstance(models, dict):
        return {}
    return {str(k).lower(): v for k, v in models.items() if isinstance(v, dict)}


def _known_capabilities(model: str) -> dict[str, Any] | None:
    """Capability entry with the longest prefix matching ``model``."""
    model_id = normalize_model_id(model)
    if not model_id:
        return None
    best: str | None = None
    for prefix in _capability_table():
        if model_id.startswith(prefix) and (best is None or len(prefix) > len(best)):
            best = prefix
    return _capability_table()[best] if best is not None else None


def lookup_model_info(model: str, *, transport: str = "") -> ModelInfo | None:
    """ModelInfo for ``model`` from the checked-in table, or None if unknown."""
    entry = _known_capabilities(model)
    if entry is None:
        return None
    return _from_entry(model, model, transport, entry)


def enrich_model(
    model_id: str,
    label: str | None = None,
    *,
    transport: str = "",
    reported: dict[str, Any] | None = None,
) -> ModelInfo:
    """Build the catalog entry for a listed model.

    Provider-reported values (``reported``, e.g. Codex's supported efforts)
    win over the checked-in table, which wins over the dataclass defaults.
    """
    entry = dict(_known_capabilities(model_id) or {})
    for key, value in (reported or {}).items():
        if value is not None:
            entry[key] = value
    return _from_entry(model_id, label or model_id, transport, entry)


def _from_entry(model_id: str, label: str, transport: str, entry: dict[str, Any]) -> ModelInfo:
    efforts = [str(e) for e in entry.get("reasoning_efforts") or [] if e]
    return ModelInfo(
        id=model_id,
        label=label,
        context_window=_int_or_none(entry.get("context_window")),
        max_output=_int_or_none(entry.get("max_output")),
        supports_tools=bool(entry.get("supports_tools", True)),
        supports_reasoning=bool(entry.get("supports_reasoning", bool(efforts))),
        reasoning_efforts=efforts,
        supports_vision=bool(entry.get("supports_vision", False)),
        supports_structured_output=bool(entry.get("supports_structured_output", False)),
        transport=transport,
    )


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def nearest_effort(requested: str, supported: list[str]) -> str | None:
    """Closest value in ``supported`` to ``requested`` on EFFORT_ORDER.

    Ties go to the higher level: asking for "minimal" where only "none" and
    "low" exist means "think a little", not "don't think".  Returns None when
    neither value can be placed on the scale.
    """
    if requested in supported:
        return requested
    if requested not in EFFORT_ORDER:
        return None
    target = EFFORT_ORDER.index(requested)
    ranked = [
        (abs(EFFORT_ORDER.index(e) - target), -EFFORT_ORDER.index(e), e)
        for e in supported
        if e in EFFORT_ORDER
    ]
    return min(ranked)[2] if ranked else None
