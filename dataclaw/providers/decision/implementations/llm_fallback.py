"""LLM decision backend — answers the decision schema with any LLMProvider.

The model returns each answer plus a self-reported confidence through
``structured_output``.  A chat model's stated confidence is not a
calibrated probability, so results carry ``probabilities=None`` and
``calibrated=False``; callers comparing against ``min_confidence`` should
treat it as a weaker signal than Jev's.
"""

from __future__ import annotations

import logging
from typing import Any

from dataclaw.providers.decision.limits import state_text, truncate_middle
from dataclaw.providers.decision.provider import DecisionError, DecisionQuestion, DecisionResult
from dataclaw.providers.llm.provider import LLMProvider, StructuredOutputError
from dataclaw.providers.llm.structured import structured_output
from dataclaw.schema import Message

logger = logging.getLogger(__name__)

# Upper bound on the state text sent to the LLM (~50k tokens).
MAX_STATE_CHARS = 200_000

SYSTEM_PROMPT = (
    "You are a decision function. Read the state and answer every question "
    "using only the information in the state. For each question give the "
    "answer and your confidence from 0 to 1 that the answer is correct. Use "
    "a low confidence when the state does not settle the question."
)


def answer_schema(question: DecisionQuestion) -> dict[str, Any]:
    if question.kind == "boolean":
        answer: dict[str, Any] = {"type": "boolean"}
    elif question.kind == "choice":
        answer = {"type": "string", "enum": list(question.options or [])}
    else:
        answer = {
            "type": "integer",
            "minimum": 0,
            "maximum": len(question.options or []) - 1,
            "description": "Index of the level that applies, starting at 0",
        }
    return {
        "type": "object",
        "properties": {
            "answer": answer,
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
        "required": ["answer", "confidence"],
        "additionalProperties": False,
    }


def response_schema(questions: list[DecisionQuestion]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {q.id: answer_schema(q) for q in questions},
        "required": [q.id for q in questions],
        "additionalProperties": False,
    }


def render_prompt(state: str | dict[str, Any], questions: list[DecisionQuestion]) -> str:
    text = state_text(state)
    if len(text) > MAX_STATE_CHARS:
        logger.warning("Decision state of %d characters truncated for the LLM fallback", len(text))
        text = truncate_middle(text, MAX_STATE_CHARS)
    lines = ["<state>", text, "</state>", "", "Questions:"]
    for q in questions:
        lines.append(f"- {q.id} ({q.kind}): {q.prompt}")
        if q.kind == "choice":
            descriptions = q.option_descriptions or {}
            for option in q.options or []:
                note = descriptions.get(option)
                lines.append(f"    - {option}" + (f": {note}" if note else ""))
        elif q.kind == "score":
            for index, level in enumerate(q.options or []):
                lines.append(f"    {index}: {level}")
    return "\n".join(lines)


class LLMDecisionProvider:
    """DecisionProvider answering through an LLM's structured output."""

    name = "llm"

    def __init__(self, llm: LLMProvider) -> None:
        self.llm = llm
        self.last_model: str | None = getattr(llm, "model", None) or getattr(llm, "model_name", None)

    async def decide(
        self,
        state: str | dict[str, Any],
        questions: list[DecisionQuestion],
    ) -> list[DecisionResult]:
        if not questions:
            raise DecisionError("At least one question is required")
        if len({q.id for q in questions}) != len(questions):
            raise DecisionError("Question ids must be unique")
        try:
            data = await structured_output(
                self.llm,
                [Message.user(render_prompt(state, questions))],
                response_schema(questions),
                system=SYSTEM_PROMPT,
                name="decision",
            )
        except StructuredOutputError as exc:
            raise DecisionError(f"The LLM did not return a usable decision: {exc}") from exc
        except Exception as exc:
            raise DecisionError(f"LLM decision call failed: {type(exc).__name__}: {exc}") from exc
        return [_parse(q, data.get(q.id)) for q in questions]


def _parse(question: DecisionQuestion, raw: Any) -> DecisionResult:
    if not isinstance(raw, dict) or "answer" not in raw:
        raise DecisionError(f"The LLM did not answer {question.id!r}")
    answer = raw["answer"]
    try:
        confidence = min(max(float(raw.get("confidence", 0.0)), 0.0), 1.0)
    except (TypeError, ValueError):
        confidence = 0.0
    if question.kind == "boolean":
        if isinstance(answer, str) and answer.strip().lower() in {"true", "false", "yes", "no"}:
            answer = answer.strip().lower() in {"true", "yes"}
        if not isinstance(answer, bool):
            raise DecisionError(f"The LLM's answer to {question.id!r} is not a boolean")
    elif question.kind == "choice":
        if answer not in (question.options or []):
            raise DecisionError(f"The LLM's answer to {question.id!r} is not one of the options")
    else:
        try:
            level = float(answer)
        except (TypeError, ValueError) as exc:
            raise DecisionError(f"The LLM's answer to {question.id!r} is not a level index") from exc
        if not 0 <= level <= len(question.options or []) - 1:
            raise DecisionError(f"The LLM's answer to {question.id!r} is out of range")
        answer = level
    return DecisionResult(
        id=question.id,
        answer=answer,
        probabilities=None,
        confidence=confidence,
        calibrated=False,
    )
