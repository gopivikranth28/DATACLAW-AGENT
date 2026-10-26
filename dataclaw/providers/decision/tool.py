"""The ``decide`` agent tool.

Registered with the core tools so it reaches OpenClaw (``contracts.tools``)
and the Hermes bridge like any other tool, but only offered to the agent
while ``decision.backend`` is not ``none``.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from dataclaw.providers.decision.provider import DecisionConfigurationError, DecisionError, DecisionQuestion
from dataclaw.providers.decision.registry import decision_enabled
from dataclaw.providers.decision.routing import decide_with_fallback

DECIDE_TOOL_NAME = "decide"

DECIDE_TOOL_DESCRIPTION = (
    "Answer typed questions about a state with the configured decision model "
    "(TypeSafe Jev, or the utility LLM as fallback). Use it for classification, "
    "routing and yes/no checks where calibrated probabilities matter, not for "
    "open-ended reasoning. Question kinds: 'choice' (pick one of options), "
    "'score' (options are ordered levels; the answer is the expected level "
    "index from 0) and 'boolean' (yes/no). Returns each answer with its "
    "confidence, the probabilities when the backend provides them, and which "
    "backend answered. LLM answers are uncalibrated (calibrated=false)."
)

DECIDE_TOOL_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "state": {
            "type": "string",
            "description": "The content the questions are about: text, or a JSON-encoded object.",
        },
        "questions": {
            "type": "array",
            "minItems": 1,
            "maxItems": 32,
            "description": "Questions to answer about the state.",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "Unique name for this question, used to label its answer"},
                    "kind": {"type": "string", "enum": ["choice", "score", "boolean"]},
                    "prompt": {"type": "string", "description": "The question or statement to evaluate"},
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "choice: the options (1-255). score: ordered level descriptions (1-10). boolean: omit.",
                    },
                    "option_descriptions": {
                        "type": "object",
                        "additionalProperties": {"type": "string"},
                        "description": "Optional choice descriptions keyed by option",
                    },
                },
                "required": ["id", "kind", "prompt"],
            },
        },
    },
    "required": ["state", "questions"],
}


def _error(code: str, message: str) -> dict[str, Any]:
    return {"success": False, "error": {"code": code, "message": message}}


def _parse_state(state: Any) -> str | dict[str, Any]:
    if isinstance(state, dict):
        return state
    text = str(state or "")
    stripped = text.strip()
    if stripped.startswith("{"):
        try:
            parsed = json.loads(stripped)
        except ValueError:
            return text
        if isinstance(parsed, dict):
            return parsed
    return text


async def decide_tool(state: Any = "", questions: Any = None, **_: Any) -> dict[str, Any]:
    """Tool entry point: validate, decide (with fallback on failure), report."""
    if not decision_enabled():
        return _error(
            "decision_disabled",
            "No decision backend is configured. Set decision.backend to typesafe or llm.",
        )
    if not isinstance(questions, list) or not questions:
        return _error("invalid_questions", "questions must be a non-empty list")
    try:
        parsed = [DecisionQuestion.model_validate(q) for q in questions]
    except ValidationError as exc:
        return _error("invalid_questions", str(exc))
    if len({q.id for q in parsed}) != len(parsed):
        return _error("invalid_questions", "question ids must be unique")

    try:
        # The agent sees the confidence itself, so a calibrated low-confidence
        # answer is reported rather than replaced by an uncalibrated LLM one.
        outcome = await decide_with_fallback(
            _parse_state(state),
            parsed,
            purpose="tool",
            fallback_on_low_confidence=False,
        )
    except (DecisionError, DecisionConfigurationError) as exc:
        return _error("decision_failed", str(exc))

    kinds = {q.id: q.kind for q in parsed}
    return {
        "success": True,
        "backend": outcome.backend,
        "model": outcome.model,
        "fallback_reason": outcome.fallback_reason,
        "min_confidence": outcome.min_confidence,
        "answers": [
            {
                "id": r.id,
                "kind": kinds.get(r.id),
                "answer": r.answer,
                "confidence": round(r.confidence, 4),
                "probabilities": r.probabilities,
                "calibrated": r.calibrated,
                "below_min_confidence": r.confidence < outcome.min_confidence,
            }
            for r in outcome.results
        ],
    }


def register_decide_tool(tool_registry: Any) -> None:
    from dataclaw.providers.tool.provider import ToolProvider

    tool_registry.register_tool(
        ToolProvider(
            name=DECIDE_TOOL_NAME,
            description=DECIDE_TOOL_DESCRIPTION,
            parameters=DECIDE_TOOL_PARAMETERS,
            fn=decide_tool,
            available=decision_enabled,
        )
    )
