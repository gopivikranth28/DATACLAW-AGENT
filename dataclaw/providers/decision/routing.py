"""Run a decision with LLM fallback and an audit trail.

``decide_with_fallback`` asks the configured backend and falls back to the
utility LLM when that backend fails or (optionally) answers below
``decision.min_confidence``.  Every decision is logged and, inside an agent
run, emitted as a ``decision:result`` custom event on the run's stream.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from dataclaw.providers.decision.provider import (
    DecisionConfigurationError,
    DecisionError,
    DecisionProvider,
    DecisionQuestion,
    DecisionResult,
)
from dataclaw.providers.decision.registry import (
    build_decision_provider,
    resolve_decision_backend,
    resolve_min_confidence,
)

if TYPE_CHECKING:
    from dataclaw.providers.llm.provider import LLMProvider

logger = logging.getLogger(__name__)

DECISION_EVENT = "decision:result"

# Provider registry bound at startup; used to find the utility LLM outside an
# agent run (e.g. plan gates resolved from an API request).
_providers: Any = None


def bind_providers(providers: Any) -> None:
    """Remember the app's ProviderRegistry (its ``llm`` is the utility model)."""
    global _providers
    _providers = providers


def utility_llm() -> "LLMProvider | None":
    """The utility LLM of the current run's bundle, else of the bound registry."""
    try:
        from dataclaw.api.context import current_runtime_bundle

        llm = getattr(current_runtime_bundle.get(), "llm", None)
        if llm is not None:
            return llm
    except LookupError:
        pass
    return getattr(_providers, "llm", None)


@dataclass
class DecisionOutcome:
    """Results plus which backend produced them and why."""

    purpose: str
    results: list[DecisionResult]
    backend: str
    model: str | None = None
    min_confidence: float = 0.7
    fallback_reason: str | None = None
    # Backend tried first when a fallback answered.
    primary_backend: str | None = None
    attempts: list[dict[str, Any]] = field(default_factory=list)

    def result(self, question_id: str) -> DecisionResult | None:
        return next((r for r in self.results if r.id == question_id), None)

    def confident(self, question_id: str) -> bool:
        result = self.result(question_id)
        return result is not None and result.confidence >= self.min_confidence

    def to_dict(self) -> dict[str, Any]:
        return {
            "purpose": self.purpose,
            "backend": self.backend,
            "model": self.model,
            "minConfidence": self.min_confidence,
            "fallbackReason": self.fallback_reason,
            "primaryBackend": self.primary_backend,
            "results": [r.model_dump() for r in self.results],
        }


async def decide_with_fallback(
    state: str | dict[str, Any],
    questions: list[DecisionQuestion],
    *,
    purpose: str,
    llm: "LLMProvider | None" = None,
    provider: DecisionProvider | None = None,
    fallback_on_low_confidence: bool = True,
) -> DecisionOutcome:
    """Answer ``questions`` with the configured backend, falling back to the LLM.

    The fallback runs when the primary backend is unavailable (missing key,
    API or transport error) or, if ``fallback_on_low_confidence``, when any
    answer is below ``decision.min_confidence``.  If the fallback fails too,
    the primary's low-confidence answers are returned; with no answers at
    all ``DecisionError`` is raised.
    """
    min_conf = resolve_min_confidence()
    llm = llm if llm is not None else utility_llm()
    backend = getattr(provider, "name", None) or resolve_decision_backend()
    attempts: list[dict[str, Any]] = []

    primary_results: list[DecisionResult] | None = None
    reason: str | None = None
    if backend != "llm" or provider is not None:
        try:
            primary = provider or build_decision_provider(backend, llm=llm)
            primary_results = await primary.decide(state, questions)
            attempts.append({"backend": backend, "ok": True})
            low = [r for r in primary_results if r.confidence < min_conf]
            if not low or not fallback_on_low_confidence or backend == "llm":
                return _finish(
                    DecisionOutcome(
                        purpose=purpose,
                        results=primary_results,
                        backend=backend,
                        model=getattr(primary, "last_model", None),
                        min_confidence=min_conf,
                        attempts=attempts,
                    ),
                    questions,
                )
            reason = "low confidence: " + ", ".join(f"{r.id}={r.confidence:.2f}" for r in low) + f" < {min_conf:.2f}"
        except (DecisionError, DecisionConfigurationError) as exc:
            reason = f"{backend} unavailable: {exc}"
            attempts.append({"backend": backend, "ok": False, "error": str(exc)})
            logger.warning("Decision backend %s failed for %s: %s", backend, purpose, exc)

    try:
        fallback = build_decision_provider("llm", llm=llm)
        results = await fallback.decide(state, questions)
        attempts.append({"backend": "llm", "ok": True})
    except (DecisionError, DecisionConfigurationError) as exc:
        attempts.append({"backend": "llm", "ok": False, "error": str(exc)})
        if primary_results is None:
            raise DecisionError(f"No decision backend could answer ({reason or exc})") from exc
        logger.warning("LLM decision fallback failed for %s: %s", purpose, exc)
        return _finish(
            DecisionOutcome(
                purpose=purpose,
                results=primary_results,
                backend=backend,
                min_confidence=min_conf,
                fallback_reason=f"{reason}; LLM fallback failed: {exc}",
                attempts=attempts,
            ),
            questions,
        )
    return _finish(
        DecisionOutcome(
            purpose=purpose,
            results=results,
            backend="llm",
            model=getattr(fallback, "last_model", None),
            min_confidence=min_conf,
            fallback_reason=reason,
            primary_backend=backend if backend != "llm" else None,
            attempts=attempts,
        ),
        questions,
    )


def _finish(outcome: DecisionOutcome, questions: list[DecisionQuestion]) -> DecisionOutcome:
    record_decision(outcome, questions)
    return outcome


def record_decision(outcome: DecisionOutcome, questions: list[DecisionQuestion]) -> None:
    """Log a decision and emit it on the current run's event stream, if any."""
    payload = outcome.to_dict()
    payload["questions"] = [{"id": q.id, "kind": q.kind, "prompt": q.prompt} for q in questions]
    logger.info(
        "decision purpose=%s backend=%s fallback=%s results=%s",
        outcome.purpose,
        outcome.backend,
        outcome.fallback_reason,
        [(r.id, r.answer, round(r.confidence, 3)) for r in outcome.results],
    )
    try:
        from dataclaw.api.context import current_emitter, current_thread_id
        from dataclaw.api.run_tracker import get_run_tracker

        emitter = current_emitter.get()
        thread_id = current_thread_id.get()
        get_run_tracker().append_event(thread_id, emitter.custom(DECISION_EVENT, payload))
    except LookupError:
        return
    except Exception:
        logger.debug("Could not emit %s event", DECISION_EVENT, exc_info=True)
