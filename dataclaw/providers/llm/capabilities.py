"""Per-model request capabilities, keyed by model-id prefix.

Some request knobs are rejected outright by models that don't implement
them (``reasoning_effort`` on gpt-4o, ``thinking_level`` on Gemini 2.5,
``output_config.effort`` on Claude Sonnet 4), turning an optional hint
into a failed turn.  Providers consult these helpers before binding such
knobs and drop them with a debug log when unsupported.

This is a deliberately small, conservative heuristic.  It is meant to be
replaced by catalog-driven ``ModelInfo`` metadata (``supports_reasoning``,
``reasoning_efforts``); keep the call sites going through these functions
so that swap stays local.
"""

from __future__ import annotations

import re

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
    model = (model or "").strip().lower()
    # Gemini ids may be given as "models/gemini-..."; OpenAI-style gateways
    # sometimes use "openai/gpt-...". Only the last path segment matters.
    return model.rsplit("/", 1)[-1]


def supports_reasoning_effort(provider: str, model: str) -> bool:
    """Whether ``model`` accepts the provider's reasoning-effort control.

    ``provider`` is one of OPENAI (``reasoning_effort`` / ``reasoning.effort``),
    ANTHROPIC (``output_config.effort``) or GEMINI (``thinking_level``).
    Unknown providers or model ids return False so the knob is dropped
    rather than failing the request.
    """
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


def supports_text_verbosity(provider: str, model: str) -> bool:
    """Whether ``model`` accepts OpenAI's ``verbosity`` / ``text.verbosity``.

    Only the gpt-5+ general models take it; codex-tuned variants reject
    anything other than the default, so they are excluded.
    """
    if provider != OPENAI:
        return False
    m = _normalize(model)
    return bool(_OPENAI_VERBOSITY.match(m)) and "codex" not in m and "-chat" not in m
