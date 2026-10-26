"""Decision provider family: Jev adapter, LLM fallback, registry, routing."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx
import pytest

from dataclaw.config.paths import config_path
from dataclaw.config.resolver import invalidate_cache
from dataclaw.providers.decision import registry as decision_registry
from dataclaw.providers.decision.implementations.llm_fallback import LLMDecisionProvider, response_schema
from dataclaw.providers.decision.implementations.typesafe_jev import (
    TypeSafeAPIError,
    TypeSafeJevProvider,
    build_request_body,
    systemone_url,
    wire_model,
)
from dataclaw.providers.decision.provider import (
    DecisionConfigurationError,
    DecisionError,
    DecisionQuestion,
    DecisionResult,
)
from dataclaw.providers.decision.registry import (
    DecisionBackendSpec,
    build_decision_provider,
    register_decision_backend,
    resolve_decision_backend,
    resolve_min_confidence,
    routing_enabled,
    unregister_decision_backend,
)
from dataclaw.providers.decision.routing import decide_with_fallback
from dataclaw.providers.llm.provider import PendingToolCall, TurnCompleteEvent

# Read before the autouse fixture clears it for the offline tests.
LIVE_TYPESAFE_KEY = os.environ.get("TYPESAFE_API_KEY", "")

QUESTIONS = [
    DecisionQuestion(id="billing", kind="boolean", prompt="Is this message about billing?"),
    DecisionQuestion(
        id="tone",
        kind="choice",
        prompt="What is the tone of this message?",
        options=["angry", "calm"],
        option_descriptions={"angry": "An upset or hostile message"},
    ),
    DecisionQuestion(
        id="urgency",
        kind="score",
        prompt="How urgent is this message?",
        options=["Can wait", "Needs attention this week", "Needs attention today"],
    ),
]

# Shaped like the documented SystemOneResponse (docs.typesafe.ai/api.md).
JEV_RESPONSE = {
    "model": "jev-1.14.0",
    "answers": {
        "billing": {"type": "noul", "noul": 0.98},
        "tone": {"type": "choice", "choice": "calm", "confidence": 0.8, "probabilities": {"angry": 0.2, "calm": 0.8}},
        "urgency": {
            "type": "score",
            "score": 1.7,
            "confidence": 0.75,
            "legend": {"0": "Can wait", "1": "Needs attention this week", "2": "Needs attention today"},
            "probabilities": {"0": 0.1, "1": 0.1, "2": 0.8},
        },
    },
    "usage": {"input_tokens": 120, "output_tokens": 12},
}


def write_config(data: dict[str, Any]) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    invalidate_cache()


@pytest.fixture(autouse=True)
def _fresh_config(monkeypatch):
    for name in ("TYPESAFE_API_KEY", "DATACLAW_DECISION_BACKEND", "DATACLAW_DECISION_MIN_CONFIDENCE"):
        monkeypatch.delenv(name, raising=False)
    invalidate_cache()
    yield
    invalidate_cache()


class Recorder:
    """httpx MockTransport handler that replays a list of responses."""

    def __init__(self, *responses: httpx.Response | Exception) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def jev(handler: Recorder, **kwargs: Any) -> tuple[TypeSafeJevProvider, list[float]]:
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    provider = TypeSafeJevProvider(
        "ts-key", transport=httpx.MockTransport(handler), sleep=sleep, **kwargs
    )
    return provider, sleeps


# ── Questions ───────────────────────────────────────────────────────────────


def test_question_validation():
    with pytest.raises(ValueError, match="needs options"):
        DecisionQuestion(id="q", kind="choice", prompt="?")
    with pytest.raises(ValueError, match="takes no options"):
        DecisionQuestion(id="q", kind="boolean", prompt="?", options=["a"])
    with pytest.raises(ValueError, match="duplicate"):
        DecisionQuestion(id="q", kind="choice", prompt="?", options=["a", "a"])
    with pytest.raises(ValueError, match="more than 10 levels"):
        DecisionQuestion(id="q", kind="score", prompt="?", options=[str(i) for i in range(11)])
    with pytest.raises(ValueError, match="unknown options"):
        DecisionQuestion(id="q", kind="choice", prompt="?", options=["a"], option_descriptions={"b": "x"})


# ── Jev request building ────────────────────────────────────────────────────


def test_request_body_matches_systemone_format():
    body = build_request_body("jev-latest", "I was charged twice.", QUESTIONS)
    assert body == {
        "model": "jev-latest",
        "state": "I was charged twice.",
        "questions": {
            "billing": {"type": "noul", "instructions": "Is this message about billing?"},
            "tone": {
                "type": "choice",
                "instructions": "What is the tone of this message?",
                "criteria": {"angry": "An upset or hostile message", "calm": None},
            },
            "urgency": {
                "type": "score",
                "instructions": "How urgent is this message?",
                "criteria": ["Can wait", "Needs attention this week", "Needs attention today"],
            },
        },
    }


def test_object_state_is_sent_as_object():
    body = build_request_body("jev-latest", {"message": "hi"}, QUESTIONS[:1])
    assert body["state"] == {"message": "hi"}


@pytest.mark.parametrize(
    ("base_url", "expected"),
    [
        ("", "https://api.typesafe.ai/v1/systemone"),
        ("https://api.typesafe.ai", "https://api.typesafe.ai/v1/systemone"),
        ("https://api.typesafe.ai/v1/", "https://api.typesafe.ai/v1/systemone"),
        ("https://ai-gateway.vercel.sh/typesafe", "https://ai-gateway.vercel.sh/typesafe/v1/systemone"),
        ("https://ai-gateway.vercel.sh/v1", "https://ai-gateway.vercel.sh/typesafe/v1/systemone"),
        ("http://localhost:9000", "http://localhost:9000/v1/systemone"),
    ],
)
def test_systemone_url(base_url, expected):
    assert systemone_url(base_url) == expected


def test_vercel_gateway_model_names():
    gateway = "https://ai-gateway.vercel.sh/typesafe"
    assert wire_model("jev-latest", gateway) == "typesafe-ai/jev"
    assert wire_model("jev-1.14.0", gateway) == "typesafe-ai/jev-1.14.0"
    assert wire_model("typesafe-ai/jev", gateway) == "typesafe-ai/jev"
    assert wire_model("jev-1.14.0", "https://api.typesafe.ai") == "jev-1.14.0"


def test_state_over_the_limit_is_truncated(caplog):
    state = "x" * (70_000 * 4)
    body = build_request_body("jev-latest", state, QUESTIONS)
    sent = body["state"]
    assert isinstance(sent, str)
    assert len(sent) < 32_000 * 4
    assert "characters truncated" in sent
    assert sent.startswith("xxx") and sent.endswith("xxx")
    assert "truncating" in caplog.text


def test_object_state_over_the_limit_becomes_truncated_text():
    body = build_request_body("jev-latest", {"log": "y" * (40_000 * 4)}, QUESTIONS[:1])
    assert isinstance(body["state"], str)
    assert "characters truncated" in body["state"]


def test_questions_too_large_for_the_limits():
    big = DecisionQuestion(id="q", kind="boolean", prompt="z" * (32_000 * 4))
    with pytest.raises(DecisionError, match="too large"):
        build_request_body("jev-latest", "s", [big])


# ── Jev transport, parsing, retries, errors ─────────────────────────────────


@pytest.mark.asyncio
async def test_decide_sends_bearer_and_parses_answers():
    handler = Recorder(httpx.Response(200, json=JEV_RESPONSE))
    provider, _ = jev(handler)

    results = await provider.decide("I was charged twice.", QUESTIONS)

    request = handler.requests[0]
    assert str(request.url) == "https://api.typesafe.ai/v1/systemone"
    assert request.headers["authorization"] == "Bearer ts-key"
    assert json.loads(request.content)["model"] == "jev-latest"
    billing, tone, urgency = results
    assert (billing.answer, billing.confidence) == (True, 0.98)
    assert billing.probabilities == {"true": 0.98, "false": pytest.approx(0.02)}
    assert tone.answer == "calm" and tone.confidence == 0.8 and tone.probabilities == {"angry": 0.2, "calm": 0.8}
    assert urgency.answer == 1.7 and urgency.probabilities == {"0": 0.1, "1": 0.1, "2": 0.8}
    assert all(r.calibrated for r in results)
    assert provider.last_model == "jev-1.14.0"


@pytest.mark.asyncio
async def test_low_yes_probability_is_a_confident_no():
    handler = Recorder(httpx.Response(200, json={"model": "jev-1.14.0", "answers": {"billing": {"type": "noul", "noul": 0.1}}, "usage": {}}))
    provider, _ = jev(handler)
    [result] = await provider.decide("s", QUESTIONS[:1])
    assert result.answer is False
    assert result.confidence == pytest.approx(0.9)


@pytest.mark.asyncio
async def test_retries_429_and_529_honouring_retry_after():
    handler = Recorder(
        httpx.Response(429, headers={"retry-after": "2"}, json={"detail": "slow down"}),
        httpx.Response(529, headers={"retry-after-ms": "250"}),
        httpx.Response(200, json=JEV_RESPONSE),
    )
    provider, sleeps = jev(handler)
    results = await provider.decide("s", QUESTIONS)
    assert len(results) == 3
    assert sleeps == [2.0, 0.25]
    assert handler.requests[1].headers["x-typesafe-retry-count"] == "1"


@pytest.mark.asyncio
async def test_retries_transport_errors_with_backoff():
    handler = Recorder(httpx.ConnectError("refused"), httpx.Response(200, json=JEV_RESPONSE))
    provider, sleeps = jev(handler)
    await provider.decide("s", QUESTIONS)
    assert len(sleeps) == 1 and 0.3 <= sleeps[0] <= 0.7


@pytest.mark.asyncio
async def test_gives_up_after_max_retries():
    handler = Recorder(*(httpx.Response(503) for _ in range(3)))
    provider, sleeps = jev(handler, max_retries=2)
    with pytest.raises(TypeSafeAPIError) as info:
        await provider.decide("s", QUESTIONS)
    assert info.value.status == 503
    assert len(handler.requests) == 3 and len(sleeps) == 2


@pytest.mark.asyncio
async def test_401_names_the_key_settings():
    handler = Recorder(httpx.Response(401, json={"detail": "Invalid API key"}, headers={"x-typesafe-request-id": "req-1"}))
    provider, sleeps = jev(handler)
    with pytest.raises(TypeSafeAPIError) as info:
        await provider.decide("s", QUESTIONS)
    message = str(info.value)
    assert "401" in message and "Invalid API key" in message
    assert "TYPESAFE_API_KEY" in message and "req-1" in message
    assert sleeps == []  # not retried


@pytest.mark.asyncio
async def test_422_validation_detail_is_readable():
    detail = {"detail": [{"loc": ["body", "questions", "urgency", "score", "criteria"], "msg": "Field required", "type": "missing"}]}
    provider, _ = jev(Recorder(httpx.Response(422, json=detail)))
    with pytest.raises(TypeSafeAPIError, match="questions.urgency.score.criteria: Field required"):
        await provider.decide("s", QUESTIONS)


@pytest.mark.asyncio
async def test_missing_or_mistyped_answer_is_an_error():
    provider, _ = jev(Recorder(httpx.Response(200, json={"model": "m", "answers": {"billing": {"type": "noul", "noul": 0.5}}, "usage": {}})))
    with pytest.raises(DecisionError, match="missing the answer to 'tone'"):
        await provider.decide("s", QUESTIONS)
    bad = {"model": "m", "answers": {"tone": {"type": "choice", "choice": "excited", "confidence": 1, "probabilities": {}}}, "usage": {}}
    provider, _ = jev(Recorder(httpx.Response(200, json=bad)))
    with pytest.raises(DecisionError, match="not one of the options"):
        await provider.decide("s", [QUESTIONS[1]])


# ── LLM fallback ────────────────────────────────────────────────────────────


class FakeLLM:
    """Honours structured_output through the forced tool call."""

    def __init__(self, answer: dict[str, Any] | None) -> None:
        self.answer = answer
        self.calls: list[dict[str, Any]] = []

    async def stream_turn(self, messages, *, system, tools, **kwargs):
        self.calls.append({"messages": messages, "system": system, "tools": tools})
        if self.answer is not None:
            yield PendingToolCall(call_id="c1", tool_name=tools[0]["name"], tool_input=self.answer)
        yield TurnCompleteEvent(has_pending_tool_calls=self.answer is not None)

    def build_tool_result_message(self, tool_calls, results, errors):
        return []


LLM_ANSWER = {
    "billing": {"answer": True, "confidence": 0.9},
    "tone": {"answer": "angry", "confidence": 0.6},
    "urgency": {"answer": 2, "confidence": 0.8},
}


@pytest.mark.asyncio
async def test_llm_fallback_answers_with_uncalibrated_confidence():
    llm = FakeLLM(LLM_ANSWER)
    results = await LLMDecisionProvider(llm).decide({"message": "pay me back"}, QUESTIONS)

    schema = llm.calls[0]["tools"][0]["parameters"]
    assert schema == response_schema(QUESTIONS)
    assert schema["properties"]["tone"]["properties"]["answer"]["enum"] == ["angry", "calm"]
    prompt = llm.calls[0]["messages"][0].text()
    assert '"message": "pay me back"' in prompt and "angry: An upset or hostile message" in prompt
    assert [r.answer for r in results] == [True, "angry", 2.0]
    assert all(r.probabilities is None and r.calibrated is False for r in results)
    assert results[1].confidence == 0.6


@pytest.mark.asyncio
async def test_llm_fallback_rejects_invalid_answers():
    with pytest.raises(DecisionError, match="not one of the options"):
        await LLMDecisionProvider(FakeLLM({**LLM_ANSWER, "tone": {"answer": "sad", "confidence": 1}})).decide("s", QUESTIONS)
    with pytest.raises(DecisionError, match="did not return a usable decision"):
        await LLMDecisionProvider(FakeLLM(None)).decide("s", QUESTIONS)


# ── Registry and configuration ──────────────────────────────────────────────


def test_backend_defaults_to_none_and_routing_off():
    assert resolve_decision_backend() == "none"
    assert resolve_min_confidence() == 0.7
    assert not routing_enabled("plan_gates")
    with pytest.raises(DecisionConfigurationError, match="decision.backend"):
        build_decision_provider()


def test_config_and_env_resolution(monkeypatch):
    write_config({"decision": {"backend": "typesafe", "min_confidence": 0.8, "routing": {"compaction": True},
                               "typesafe": {"api_key": "cfg-key", "model": "jev-1.13.0", "base_url": "https://ai-gateway.vercel.sh/typesafe"}}})
    provider = build_decision_provider()
    assert isinstance(provider, TypeSafeJevProvider)
    assert provider.api_key == "cfg-key"
    assert provider.model == "typesafe-ai/jev-1.13.0"
    assert provider.url == "https://ai-gateway.vercel.sh/typesafe/v1/systemone"
    assert resolve_min_confidence() == 0.8
    assert routing_enabled("compaction") and not routing_enabled("skill_routing")

    monkeypatch.setenv("TYPESAFE_API_KEY", "env-key")
    monkeypatch.setenv("DATACLAW_DECISION_BACKEND", "llm")
    assert resolve_decision_backend() == "llm"
    assert build_decision_provider("typesafe").api_key == "env-key"


def test_missing_typesafe_key_names_env_var_and_config_path():
    write_config({"decision": {"backend": "typesafe"}})
    with pytest.raises(DecisionConfigurationError) as info:
        build_decision_provider()
    assert "TYPESAFE_API_KEY or decision.typesafe.api_key" in str(info.value)


def test_unknown_backend_is_a_configuration_error():
    write_config({"decision": {"backend": "oracle", "routing": {"plan_gates": True}}})
    with pytest.raises(DecisionConfigurationError, match="oracle"):
        resolve_decision_backend()
    assert not routing_enabled("plan_gates")


def test_plugin_backend_registration():
    class Fixed:
        name = "fixed"

        async def decide(self, state, questions):
            return [DecisionResult(id=q.id, answer=True, confidence=1.0) for q in questions]

    spec = DecisionBackendSpec(id="fixed", label="Fixed", build=lambda cfg, llm: Fixed())
    register_decision_backend(spec)
    try:
        assert decision_registry.get_decision_backend("fixed") is spec
        assert "fixed" in [s.id for s in decision_registry.list_decision_backends()]
        write_config({"decision": {"backend": "fixed"}})
        assert isinstance(build_decision_provider(), Fixed)
        with pytest.raises(ValueError, match="built in"):
            register_decision_backend(DecisionBackendSpec(id="typesafe", label="x", build=spec.build))
        with pytest.raises(ValueError, match="built in"):
            register_decision_backend(DecisionBackendSpec(id="none", label="x", build=spec.build))
    finally:
        unregister_decision_backend("fixed")


def test_backend_specs_serialize_for_the_ui():
    specs = {s["id"]: s for s in (spec.to_dict() for spec in decision_registry.list_decision_backends())}
    assert {"typesafe", "llm"} <= set(specs)
    fields = {f["name"]: f for f in specs["typesafe"]["fields"]}
    assert fields["api_key"]["field_type"] == "secret" and fields["api_key"]["env"] == "TYPESAFE_API_KEY"
    assert fields["model"]["default"] == "jev-latest"


# ── Routing with fallback ───────────────────────────────────────────────────


class StaticProvider:
    def __init__(self, name: str, confidence: float | None = None, error: Exception | None = None) -> None:
        self.name = name
        self.confidence = confidence
        self.error = error
        self.calls = 0
        self.last_model = "jev-1.14.0"

    async def decide(self, state, questions):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return [DecisionResult(id=q.id, answer=True, confidence=self.confidence) for q in questions]


BOOL_Q = [DecisionQuestion(id="ok", kind="boolean", prompt="ok?")]


@pytest.mark.asyncio
async def test_confident_primary_answer_is_used():
    llm = FakeLLM({"ok": {"answer": False, "confidence": 0.9}})
    outcome = await decide_with_fallback("s", BOOL_Q, purpose="test", llm=llm, provider=StaticProvider("typesafe", 0.95))
    assert outcome.backend == "typesafe" and outcome.fallback_reason is None
    assert outcome.model == "jev-1.14.0"
    assert llm.calls == []


@pytest.mark.asyncio
async def test_low_confidence_falls_back_to_the_llm():
    llm = FakeLLM({"ok": {"answer": False, "confidence": 0.9}})
    outcome = await decide_with_fallback("s", BOOL_Q, purpose="test", llm=llm, provider=StaticProvider("typesafe", 0.5))
    assert outcome.backend == "llm" and outcome.primary_backend == "typesafe"
    assert "low confidence: ok=0.50 < 0.70" in outcome.fallback_reason
    assert outcome.result("ok").answer is False


@pytest.mark.asyncio
async def test_low_confidence_kept_when_fallback_disabled():
    llm = FakeLLM({"ok": {"answer": False, "confidence": 0.9}})
    outcome = await decide_with_fallback(
        "s", BOOL_Q, purpose="test", llm=llm, provider=StaticProvider("typesafe", 0.5), fallback_on_low_confidence=False
    )
    assert outcome.backend == "typesafe" and llm.calls == []
    assert not outcome.confident("ok")


@pytest.mark.asyncio
async def test_unavailable_primary_falls_back_to_the_llm():
    llm = FakeLLM({"ok": {"answer": True, "confidence": 0.8}})
    outcome = await decide_with_fallback(
        "s", BOOL_Q, purpose="test", llm=llm, provider=StaticProvider("typesafe", error=DecisionError("boom"))
    )
    assert outcome.backend == "llm"
    assert outcome.fallback_reason == "typesafe unavailable: boom"


@pytest.mark.asyncio
async def test_missing_key_falls_back_to_the_llm():
    write_config({"decision": {"backend": "typesafe"}})
    llm = FakeLLM({"ok": {"answer": True, "confidence": 0.8}})
    outcome = await decide_with_fallback("s", BOOL_Q, purpose="test", llm=llm)
    assert outcome.backend == "llm"
    assert "TYPESAFE_API_KEY" in outcome.fallback_reason


@pytest.mark.asyncio
async def test_failed_fallback_keeps_low_confidence_primary_answer():
    outcome = await decide_with_fallback("s", BOOL_Q, purpose="test", llm=FakeLLM(None), provider=StaticProvider("typesafe", 0.4))
    assert outcome.backend == "typesafe"
    assert "LLM fallback failed" in outcome.fallback_reason


@pytest.mark.asyncio
async def test_no_backend_can_answer():
    with pytest.raises(DecisionError, match="No decision backend could answer"):
        await decide_with_fallback(
            "s", BOOL_Q, purpose="test", llm=FakeLLM(None), provider=StaticProvider("typesafe", error=DecisionError("down"))
        )


@pytest.mark.asyncio
async def test_llm_backend_answers_directly():
    write_config({"decision": {"backend": "llm"}})
    llm = FakeLLM({"ok": {"answer": True, "confidence": 0.2}})
    outcome = await decide_with_fallback("s", BOOL_Q, purpose="test", llm=llm)
    assert outcome.backend == "llm" and outcome.fallback_reason is None
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_decision_is_emitted_on_the_run_stream():
    from dataclaw.api.context import current_emitter, current_thread_id
    from dataclaw.api.run_tracker import get_run_tracker
    from dataclaw.events.emitter import AgentEventEmitter

    tracker = get_run_tracker()
    run = tracker.start_run("decision-thread", "decision-run")
    emitter_token = current_emitter.set(AgentEventEmitter("decision-thread", "decision-run"))
    thread_token = current_thread_id.set("decision-thread")
    try:
        await decide_with_fallback("s", BOOL_Q, purpose="audit", llm=FakeLLM(None), provider=StaticProvider("typesafe", 0.9))
    finally:
        current_emitter.reset(emitter_token)
        current_thread_id.reset(thread_token)
        tracker.finish_run("decision-thread")
    encoded = "\n".join(event for _, event in run.events)
    assert "decision:result" in encoded and '"purpose":"audit"' in encoded.replace(" ", "")


@pytest.mark.skipif(not LIVE_TYPESAFE_KEY, reason="set TYPESAFE_API_KEY to run against the live Jev API")
@pytest.mark.asyncio
async def test_live_jev_round_trip():
    provider = TypeSafeJevProvider(LIVE_TYPESAFE_KEY, timeout=60)
    results = await provider.decide("I was charged twice for my subscription. Please refund me today!", QUESTIONS)
    by_id = {r.id: r for r in results}
    assert by_id["billing"].answer is True
    assert by_id["tone"].answer in {"angry", "calm"} and by_id["tone"].probabilities
    assert 0 <= float(by_id["urgency"].answer) <= 2
    assert (provider.last_model or "").startswith("jev-")
