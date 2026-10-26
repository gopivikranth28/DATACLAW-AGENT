"""Decision-model plan gate pre-check and skill routing (opt-in)."""

from __future__ import annotations

import json
from typing import Any

import pytest

import dataclaw.config.paths as paths
from dataclaw.config.resolver import invalidate_cache
from dataclaw.providers.decision import routing
from dataclaw.providers.decision.implementations.llm_fallback import LLMDecisionProvider
from dataclaw.providers.decision.provider import DecisionResult
from dataclaw.providers.llm.provider import PendingToolCall, TurnCompleteEvent

import dataclaw_plans.decisions as decisions
import dataclaw_plans.gates as gates


@pytest.fixture(autouse=True)
def tmp_home(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DATACLAW_HOME", tmp_path)
    for name in ("TYPESAFE_API_KEY", "DATACLAW_DECISION_BACKEND", "DATACLAW_DECISION_MIN_CONFIDENCE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(gates, "GATE_RESOLVERS", {})
    decisions._gate_cache.clear()
    invalidate_cache()
    yield tmp_path
    invalidate_cache()


def write_config(decision: dict[str, Any]) -> None:
    path = paths.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"decision": decision}))
    invalidate_cache()


class Primary:
    """Stands in for the Jev backend."""

    name = "typesafe"
    last_model = "jev-1.14.0"

    def __init__(self, answer: Any, confidence: float, probabilities: dict[str, float] | None = None) -> None:
        self.answer = answer
        self.confidence = confidence
        self.probabilities = probabilities
        self.calls: list[tuple[Any, list]] = []

    async def decide(self, state, questions):
        self.calls.append((state, questions))
        return [
            DecisionResult(id=q.id, answer=self.answer, confidence=self.confidence, probabilities=self.probabilities)
            for q in questions
        ]


class FakeLLM:
    def __init__(self, answer: dict[str, Any] | None) -> None:
        self.answer = answer
        self.calls = 0

    async def stream_turn(self, messages, *, system, tools, **kwargs):
        self.calls += 1
        if self.answer is not None:
            yield PendingToolCall(call_id="c1", tool_name=tools[0]["name"], tool_input=self.answer)
        yield TurnCompleteEvent(has_pending_tool_calls=self.answer is not None)

    def build_tool_result_message(self, tool_calls, results, errors):
        return []


@pytest.fixture
def backends(monkeypatch):
    """Route build_decision_provider to a fake Jev and a fake utility LLM."""
    state: dict[str, Any] = {"primary": Primary(True, 0.9), "llm": FakeLLM(None), "builds": []}

    def build(backend=None, *, llm=None):
        state["builds"].append(backend)
        if backend == "llm":
            return LLMDecisionProvider(state["llm"])
        return state["primary"]

    monkeypatch.setattr(routing, "build_decision_provider", build)
    return state


PROPOSAL = {"id": "plan-1", "name": "Churn study", "description": "Explain churn"}
STEP = {
    "plan_step_id": "step-0000abcd",
    "name": "Profile customers",
    "description": "Profile the customer table",
    "status": "completed",
    "summary": "Profiled 12 columns; no nulls in key fields",
    "outputs": ["profile.html"],
}


# ── Plan-gate pre-check ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_gate_toggle_off_makes_no_calls(backends):
    write_config({"backend": "typesafe", "routing": {"plan_gates": False}})
    assert await decisions.decision_gate_resolver(PROPOSAL, STEP) is None
    assert backends["builds"] == []


@pytest.mark.asyncio
async def test_gate_inert_without_a_backend(backends):
    write_config({"backend": "none", "routing": {"plan_gates": True}})
    assert await decisions.decision_gate_resolver(PROPOSAL, STEP) is None
    assert backends["builds"] == []


@pytest.mark.asyncio
async def test_gate_skips_steps_without_recorded_work(backends):
    write_config({"backend": "typesafe", "routing": {"plan_gates": True}})
    assert await decisions.decision_gate_resolver(PROPOSAL, {**STEP, "status": "not_started"}) is None
    assert backends["builds"] == []


@pytest.mark.asyncio
async def test_gate_passes_on_a_confident_yes_and_is_cached(backends):
    write_config({"backend": "typesafe", "routing": {"plan_gates": True}})
    gate = await decisions.decision_gate_resolver(PROPOSAL, STEP)
    assert gate["status"] == "pass"
    assert gate["actor"] == "decision:typesafe"
    assert "required" not in gate
    assert gate["details"]["confidence"] == 0.9
    state, questions = backends["primary"].calls[0]
    assert state["step"]["summary"] == STEP["summary"] and questions[0].kind == "boolean"

    await decisions.decision_gate_resolver(PROPOSAL, STEP)
    assert len(backends["primary"].calls) == 1


@pytest.mark.asyncio
async def test_gate_low_confidence_falls_back_to_the_llm(backends):
    write_config({"backend": "typesafe", "min_confidence": 0.7, "routing": {"plan_gates": True}})
    backends["primary"] = Primary(True, 0.55)
    backends["llm"] = FakeLLM({"ready": {"answer": False, "confidence": 0.85}})

    gate = await decisions.decision_gate_resolver(PROPOSAL, STEP)

    assert backends["llm"].calls == 1
    assert gate["status"] == "warn"
    assert gate["actor"] == "decision:llm"
    assert "not yet ready" in gate["reason"]
    assert "low confidence" in gate["details"]["fallback_reason"]
    assert gate["details"]["calibrated"] is False


@pytest.mark.asyncio
async def test_gate_warns_when_no_backend_is_confident(backends):
    write_config({"backend": "typesafe", "routing": {"plan_gates": True}})
    backends["primary"] = Primary(True, 0.5)
    backends["llm"] = FakeLLM({"ready": {"answer": True, "confidence": 0.4}})
    gate = await decisions.decision_gate_resolver(PROPOSAL, STEP)
    assert gate["status"] == "warn" and "not confident" in gate["reason"]


@pytest.mark.asyncio
async def test_warn_gate_is_advisory_unless_policy_requires_it(backends):
    write_config({"backend": "typesafe", "routing": {"plan_gates": True}})
    backends["primary"] = Primary(False, 0.95)
    gates.register_gate_resolver(decisions.DECISION_GATE, decisions.decision_gate_resolver)
    # A step that does not trip the analysis-review policy keywords.
    step = {**STEP, "name": "Write notes", "description": "Summarise notes", "summary": "Notes written", "outputs": []}

    resolved = await gates.resolve_step_gates(PROPOSAL, step)
    assert resolved[decisions.DECISION_GATE]["status"] == "warn"
    assert resolved[decisions.DECISION_GATE]["required"] is False
    assert await gates.blocking_gates(PROPOSAL, step) == []

    required = {**step, "gates": {decisions.DECISION_GATE: {"status": "unknown", "required": True}}}
    blockers = await gates.blocking_gates(PROPOSAL, required)
    assert [g["name"] for g in blockers] == [decisions.DECISION_GATE]


# ── Skill routing at plan drafting ──────────────────────────────────────────

SKILLS = [
    {"id": "churn", "serial_id": "skill_1", "name": "Churn analysis", "description": "Retention and churn drivers"},
    {"id": "forecast", "serial_id": "skill_2", "name": "Forecasting", "description": "Time-series forecasts"},
]


def drafting_state() -> dict[str, Any]:
    return {
        "session_id": "s-1",
        "user_query": "Why are customers leaving?",
        "skills": [dict(s) for s in SKILLS],
        "skill_prompt_fragments": ["Available skills: ..."],
        "metadata": {},
    }


@pytest.mark.asyncio
async def test_skill_routing_toggle_off_makes_no_calls(backends):
    write_config({"backend": "typesafe"})
    state = drafting_state()
    assert await decisions.decision_skill_routing_hook(state) is state
    assert backends["builds"] == []


@pytest.mark.asyncio
async def test_skill_routing_adds_an_advisory_hint(backends):
    write_config({"backend": "typesafe", "routing": {"skill_routing": True}})
    backends["primary"] = Primary("skill_1", 0.8, {"skill_1": 0.65, "skill_2": 0.3, "none": 0.05})

    state = await decisions.decision_skill_routing_hook(drafting_state())

    _, questions = backends["primary"].calls[0]
    assert questions[0].kind == "choice" and questions[0].options == ["skill_1", "skill_2", "none"]
    assert questions[0].option_descriptions["skill_1"] == "Churn analysis: Retention and churn drivers"
    hint = state["skill_prompt_fragments"][-1]
    assert "Churn analysis (id: skill_1)" in hint and "Forecasting (id: skill_2)" in hint
    assert state["metadata"]["decision_skill_routing"]["backend"] == "typesafe"


@pytest.mark.asyncio
async def test_skill_routing_low_confidence_falls_back_then_adds_nothing(backends):
    write_config({"backend": "typesafe", "routing": {"skill_routing": True}})
    backends["primary"] = Primary("skill_2", 0.4)
    backends["llm"] = FakeLLM({"skill": {"answer": "skill_2", "confidence": 0.5}})

    state = await decisions.decision_skill_routing_hook(drafting_state())

    assert backends["llm"].calls == 1
    assert state["skill_prompt_fragments"] == ["Available skills: ..."]
    assert state["metadata"]["decision_skill_routing"]["backend"] == "llm"


@pytest.mark.asyncio
async def test_skill_routing_only_while_drafting(backends, monkeypatch):
    write_config({"backend": "typesafe", "routing": {"skill_routing": True}})
    import dataclaw_plans.hooks as hooks

    monkeypatch.setattr(hooks, "_in_planning_phase", lambda session_id: False)
    state = drafting_state()
    assert await decisions.decision_skill_routing_hook(state) is state
    assert backends["builds"] == []
