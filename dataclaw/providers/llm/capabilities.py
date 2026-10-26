"""Per-model request capabilities.

Some request knobs are rejected outright by models that don't implement
them (``reasoning_effort`` on gpt-4o, ``thinking_level`` on Gemini 2.5,
``output_config.effort`` on Claude Sonnet 4), turning an optional hint
into a failed turn.  Providers consult these helpers before binding such
knobs and drop them with a debug log when unsupported.

Known models are answered from the catalog's ``ModelInfo``
(``model_capabilities.json``: ``supports_reasoning``, ``reasoning_efforts``).
Unknown ids fall back to small, conservative prefix rules, unless the
caller talks to a third-party endpoint and asks for ``catalog_only``.
"""

from __future__ import annotations

import logging
import re

from dataclaw.providers.llm.catalog import lookup_model_info, nearest_effort, normalize_model_id

logger = logging.getLogger(__name__)

# Provider families understood here. Callers map their backend/model class
# onto one of these.
OPENAI = "openai"
ANTHROPIC = "anthropic"
GEMINI = "gemini"

# OpenAI reasoning models: the o-series, gpt-5 and later, gpt-oss, codex.
_OPENAI_REASONING = re.compile(r"^(o\d|gpt-(?:[5-9]|\d{2,})|gpt-oss|codex)")
# gpt-5 and later; o-series models reject ``verbosity``.
_OPENAI_VERBOSITY = re.compile(r"^gpt-(?:[5-9]|\d{2,})")
_CLAUDE = re.compile(r"^claude-(?P<family>[a-z]+)-(?P<major>\d+)(?:-(?P<minor>\d{1,2}))?(?:\D|$)")
_GEMINI = re.compile(r"^gemini-(?P<major>\d+)")


def _normalize(model: str) -> str:
    # Gemini ids may be given as "models/gemini-..."; OpenAI-style gateways
    # sometimes use "openai/gpt-...". Only the last path segment matters.
    return normalize_model_id(model)


def supports_reasoning_effort(provider: str, model: str, *, catalog_only: bool = False) -> bool:
    """Whether ``model`` accepts the provider's reasoning-effort control.

    ``provider`` is one of OPENAI (``reasoning_effort`` / ``reasoning.effort``),
    ANTHROPIC (``output_config.effort``) or GEMINI (``thinking_level``).
    Unknown providers or model ids return False so the knob is dropped
    rather than failing the request.  ``catalog_only`` skips the prefix
    rules, for endpoints (OpenAI-compatible servers) where a familiar-looking
    id says nothing about which request fields the server accepts.
    """
    if provider not in (OPENAI, ANTHROPIC, GEMINI):
        return False
    info = lookup_model_info(model)
    if info is not None:
        return info.supports_reasoning
    if catalog_only:
        return False
    m = _normalize(model)
    if provider == OPENAI:
        return bool(_OPENAI_REASONING.match(m)) and "-chat" not in m
    if provider == ANTHROPIC:
        match = _CLAUDE.match(m)
        if not match:
            return False
        version = (int(match["major"]), int(match["minor"] or 0))
        # Effort shipped on Opus 4.5, then on every 4.6+ model.
        if match["family"] == "opus" and version >= (4, 5):
            return True
        return version >= (4, 6)
    if provider == GEMINI:
        # thinking_level is Gemini 3+; 2.5 only takes a token budget.
        match = _GEMINI.match(m)
        return bool(match) and int(match["major"]) >= 3
    return False


def resolve_reasoning_effort(
    provider: str,
    model: str,
    effort: str | None,
    *,
    catalog_only: bool = False,
) -> str | None:
    """The effort value to send for ``model``, or None to omit the knob.

    Drops the knob when the model has no reasoning control.  When the catalog
    lists the model's accepted values, an unsupported request maps to the
    nearest supported level (e.g. "minimal" -> "low" on Claude), or is
    dropped if it cannot be placed.  Without a list the value passes through.
    """
    if not effort:
        return None
    if not supports_reasoning_effort(provider, model, catalog_only=catalog_only):
        logger.debug("Skipping reasoning_effort=%r: not supported by %r", effort, model)
        return None
    info = lookup_model_info(model)
    if info is None or not info.reasoning_efforts:
        return effort
    chosen = nearest_effort(effort, info.reasoning_efforts)
    if chosen is None:
        logger.debug(
            "Skipping reasoning_effort=%r: %r accepts %s",
            effort, model, info.reasoning_efforts,
        )
    elif chosen != effort:
        logger.debug("reasoning_effort=%r not offered by %r; using %r", effort, model, chosen)
    return chosen


def supports_text_verbosity(provider: str, model: str) -> bool:
    """Whether ``model`` accepts OpenAI's ``verbosity`` / ``text.verbosity``.

    Only the gpt-5+ general models take it; codex-tuned variants reject
    anything other than the default, so they are excluded.
    """
    if provider != OPENAI:
        return False
    m = _normalize(model)
    return bool(_OPENAI_VERBOSITY.match(m)) and "codex" not in m and "-chat" not in m
