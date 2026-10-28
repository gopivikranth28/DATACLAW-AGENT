"""Decision-model integrations for plans (opt-in, advisory).

- ``decision_gate_resolver``: the ``decision_precheck`` plan gate
  (``decision.routing.plan_gates``).  It asks whether a step's recorded work
  satisfies what the step set out to do and reports ``pass`` or ``warn``.
  It never sets ``required``, so it only blocks if a stored gate policy
  already requires it.
- ``decision_skill_routing_hook``: a ``postSkillHook`` for the plan-drafting
  turn (``decision.routing.skill_routing``).  Skill routing is otherwise
  prompt-only; this adds an advisory "likely playbook" line to the skill
  section of the system prompt when the decision model is confident.

Both fall back to the utility LLM (see ``decide_with_fallback``) and emit
``decision:result`` events inside a run.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections import OrderedDict
from typing import Any

from dataclaw.providers.decision.provider import DecisionConfigurationError, DecisionError, DecisionQuestion
from dataclaw.providers.decision.registry import resolve_decision_backend, resolve_min_confidence, routing_enabled
from dataclaw.providers.decision.routing import DecisionOutcome, decide_with_fallback
from dataclaw.state import AgentState

logger = logging.getLogger(__name__)

DECISION_GATE = "decision_precheck"
# Steps the pre-check evaluates; untouched steps have nothing to judge yet.
_EVALUATED_STATUSES = {"in_progress", "completed"}
_GATE_QUESTION_ID = "ready"
_GATE_QUESTION = DecisionQuestion(
    id=_GATE_QUESTION_ID,
    kind="boolean",
    prompt=(
        "Does the step's recorded work (status, summary, outputs and notes) satisfy what the "
        "step description set out to do, so the step is ready for human validation?"
    ),
)
# Gate state is resolved on every plan read (the UI polls it); cache by step
# content so an unchanged step is decided once.
_GATE_CACHE_SIZE = 256
_gate_cache: OrderedDict[str, dict[str, Any]] = OrderedDict()

SKILL_NONE = "none"
_SKILL_QUESTION_ID = "skill"
# Secondary skills are suggested when their probability reaches this share.
_SECONDARY_SKILL_PROBABILITY = 0.25
_MAX_SKILL_OPTIONS = 254  # Jev allows 255 choices; one is "none"


def _outcome_details(outcome: DecisionOutcome, question_id: str) -> dict[str, Any]:
    result = outcome.result(question_id)
    return {
        "backend": outcome.backend,
        "model": outcome.model,
        "answer": result.answer if result else None,
        "confidence": result.confidence if result else None,
        "calibrated": result.calibrated if result else None,
        "probabilities": result.probabilities if result else None,
        "min_confidence": outcome.min_confidence,
        "fallback_reason": outcome.fallback_reason,
    }


def _step_state(proposal: dict[str, Any], step: dict[str, Any]) -> dict[str, Any]:
    return {
        "plan": {
            "name": proposal.get("name", ""),
            "description": proposal.get("description", ""),
        },
        "step": {
            key: step.get(key)
            for key in ("name", "description", "status", "summary", "outputs", "note", "ready_for_validation")
            if step.get(key) not in (None, "", [])
        },
    }


async def decision_gate_resolver(proposal: dict[str, Any], step: dict[str, Any]) -> dict[str, Any] | None:
    """Advisory ``decision_precheck`` gate; ``None`` (no gate) when off or not applicable."""
    if not routing_enabled("plan_gates"):
        return None
    if step.get("status") not in _EVALUATED_STATUSES and not step.get("ready_for_validation"):
        return None

    state = _step_state(proposal, step)
    key = hashlib.sha256(
        json.dumps(
            [proposal.get("id"), state, resolve_decision_backend(), resolve_min_confidence()],
            sort_keys=True,
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    cached = _gate_cache.get(key)
    if cached is not None:
        _gate_cache.move_to_end(key)
        return dict(cached)

    try:
        outcome = await decide_with_fallback(state, [_GATE_QUESTION], purpose="plan_gate")
    except (DecisionError, DecisionConfigurationError) as exc:
        # Not cached: a transient outage should not stick.
        return {
            "status": "warn",
            "reason": f"Decision pre-check unavailable: {exc}",
            "actor": "decision",
        }

    result = outcome.result(_GATE_QUESTION_ID)
    confident = outcome.confident(_GATE_QUESTION_ID)
    if result is not None and result.answer is True and confident:
        status = "pass"
        reason = f"Decision model judges the step ready ({result.confidence:.0%} confidence)"
    elif result is not None and result.answer is False and confident:
        status = "warn"
        reason = f"Decision model judges the step not yet ready ({result.confidence:.0%} confidence)"
    else:
        status = "warn"
        confidence = f"{result.confidence:.0%}" if result is not None else "no answer"
        reason = f"Decision model is not confident about this step ({confidence} < {outcome.min_confidence:.0%})"
    # ``required`` is deliberately absent so a stored gate policy keeps its value.
    gate = {
        "status": status,
        "reason": reason,
        "actor": f"decision:{outcome.backend}",
        "details": _outcome_details(outcome, _GATE_QUESTION_ID),
    }
    _gate_cache[key] = gate
    while len(_gate_cache) > _GATE_CACHE_SIZE:
        _gate_cache.popitem(last=False)
    return dict(gate)


def _skill_option(skill: dict[str, Any]) -> str:
    return str(skill.get("serial_id") or skill.get("id") or "")


async def decision_skill_routing_hook(state: AgentState) -> AgentState:
    """postSkillHook: suggest the playbook(s) matching the request while drafting a plan."""
    if not routing_enabled("skill_routing"):
        return state
    from dataclaw_plans.hooks import _in_planning_phase

    query = str(state.get("user_query") or "").strip()
    skills = [s for s in state.get("skills") or [] if _skill_option(s)]
    if not query or not skills or not _in_planning_phase(state.get("session_id", "")):
        return state

    skills = skills[:_MAX_SKILL_OPTIONS]
    by_option = {_skill_option(s): s for s in skills}
    question = DecisionQuestion(
        id=_SKILL_QUESTION_ID,
        kind="choice",
        prompt=(
            "Which skill's method best fits the user's request? Answer 'none' when no "
            "skill applies."
        ),
        options=[*by_option, SKILL_NONE],
        option_descriptions={
            **{
                option: f"{skill.get('name', '')}: {skill.get('description', '')}".strip(": ")
                for option, skill in by_option.items()
            },
            SKILL_NONE: "No listed skill applies to this request.",
        },
    )
    try:
        outcome = await decide_with_fallback({"user_request": query}, [question], purpose="skill_routing")
    except (DecisionError, DecisionConfigurationError) as exc:
        logger.warning("Decision skill routing failed; keeping prompt-only routing: %s", exc)
        return state
    except Exception:
        # Advisory routing must never fail the run.
        logger.exception("Decision skill routing raised; keeping prompt-only routing")
        return state

    result = outcome.result(_SKILL_QUESTION_ID)
    metadata = {**(state.get("metadata") or {}), "decision_skill_routing": _outcome_details(outcome, _SKILL_QUESTION_ID)}
    if result is None or result.answer == SKILL_NONE or not outcome.confident(_SKILL_QUESTION_ID):
        return {**state, "metadata": metadata}

    picks = [str(result.answer)]
    for option, probability in sorted((result.probabilities or {}).items(), key=lambda kv: -kv[1]):
        if option not in picks and option in by_option and probability >= _SECONDARY_SKILL_PROBABILITY:
            picks.append(option)
    names = ", ".join(f"{by_option[o].get('name', o)} (id: {o})" for o in picks)
    hint = (
        f"Decision-model routing (advisory, {result.confidence:.0%} confidence): this request most "
        f"likely calls for {names}. Fetch with `fetch_skill` before drafting the plan unless it "
        "clearly does not apply; other matching playbooks still apply."
    )
    fragments = [*(state.get("skill_prompt_fragments") or []), hint]
    return {**state, "skill_prompt_fragments": fragments, "metadata": metadata}
