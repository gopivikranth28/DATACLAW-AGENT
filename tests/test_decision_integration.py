"""Decision models in the app: the ``decide`` tool, config API, compaction trigger."""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from dataclaw.api.app import create_app
from dataclaw.api.routers import chat
from dataclaw.api.run_tracker import get_run_tracker
from dataclaw.config.paths import config_path
from dataclaw.config.resolver import invalidate_cache
from dataclaw.hooks.registry import HookRegistry
from dataclaw.providers.compaction import early
from dataclaw.providers.compaction.implementations.drop_old import DropOldCompactor
from dataclaw.providers.compaction.implementations.noop import NoopCompactor
from dataclaw.providers.decision import routing
from dataclaw.providers.decision.implementations.llm_fallback import LLMDecisionProvider
from dataclaw.providers.decision.provider import DecisionResult
from dataclaw.providers.decision.tool import DECIDE_TOOL_NAME, decide_tool, register_decide_tool
from dataclaw.providers.llm.provider import PendingToolCall, TextDeltaEvent, TurnCompleteEvent
from dataclaw.providers.tool.implementations.registry import DefaultToolAvailability
from dataclaw.schema import Message
from dataclaw.storage import sessions


@pytest.fixture(autouse=True)
def _fresh_config(monkeypatch):
    for name in ("TYPESAFE_API_KEY", "DATACLAW_DECISION_BACKEND", "DATACLAW_DECISION_MIN_CONFIDENCE"):
        monkeypatch.delenv(name, raising=False)
    invalidate_cache()
    yield
    invalidate_cache()


def write_config(data: dict[str, Any]) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    invalidate_cache()


class Primary:
    name = "typesafe"
    last_model = "jev-1.14.0"

    def __init__(self, answer: Any = True, confidence: float = 0.9) -> None:
        self.answer = answer
        self.confidence = confidence
        self.calls = 0

    async def decide(self, state, questions):
        self.calls += 1
        return [
            DecisionResult(id=q.id, answer=self.answer, confidence=self.confidence, probabilities={"true": self.confidence, "false": 1 - self.confidence})
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
    state: dict[str, Any] = {"primary": Primary(), "llm": FakeLLM(None), "builds": []}

    def build(backend=None, *, llm=None):
        state["builds"].append(backend)
        if backend == "llm":
            return LLMDecisionProvider(state["llm"])
        return state["primary"]

    monkeypatch.setattr(routing, "build_decision_provider", build)
    return state


# ── decide tool ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_decide_tool_offered_only_when_a_backend_is_selected():
    registry = DefaultToolAvailability()
    register_decide_tool(registry)

    listing = {t["name"]: t for t in registry.get_all_tools_with_status()}
    assert listing[DECIDE_TOOL_NAME]["available"] is False
    defs, callables = await registry.resolve_tools({})
    assert DECIDE_TOOL_NAME not in callables

    write_config({"decision": {"backend": "typesafe"}})
    defs, callables = await registry.resolve_tools({})
    assert DECIDE_TOOL_NAME in callables
    definition = next(d for d in defs if d["name"] == DECIDE_TOOL_NAME)
    assert definition["parameters"]["required"] == ["state", "questions"]
    assert definition["parameters"]["properties"]["questions"]["items"]["properties"]["kind"]["enum"] == ["choice", "score", "boolean"]


def test_decide_tool_is_in_the_live_registry(tmp_path, monkeypatch):
    with TestClient(create_app()) as client:
        tools = {t["name"]: t for t in client.get("/api/tools").json()["tools"]}
    assert DECIDE_TOOL_NAME in tools
    assert tools[DECIDE_TOOL_NAME]["available"] is False


@pytest.mark.asyncio
async def test_decide_tool_disabled_without_a_backend(backends):
    result = await decide_tool(state="s", questions=[{"id": "q", "kind": "boolean", "prompt": "?"}])
    assert result["success"] is False and result["error"]["code"] == "decision_disabled"
    assert backends["builds"] == []


@pytest.mark.asyncio
async def test_decide_tool_returns_answers_and_backend(backends):
    write_config({"decision": {"backend": "typesafe", "min_confidence": 0.95}})
    result = await decide_tool(
        state='{"ticket": "charged twice"}',
        questions=[{"id": "billing", "kind": "boolean", "prompt": "About billing?"}],
        session_id="ignored-context",
    )
    assert result["success"] is True
    assert result["backend"] == "typesafe" and result["model"] == "jev-1.14.0"
    [answer] = result["answers"]
    assert answer["id"] == "billing" and answer["answer"] is True and answer["kind"] == "boolean"
    assert answer["probabilities"]["true"] == 0.9
    # Below the threshold is reported, not replaced by the LLM.
    assert answer["below_min_confidence"] is True
    assert backends["builds"] == ["typesafe"]


@pytest.mark.asyncio
async def test_decide_tool_validates_questions(backends):
    write_config({"decision": {"backend": "typesafe"}})
    bad = await decide_tool(state="s", questions=[{"id": "q", "kind": "choice", "prompt": "?"}])
    assert bad["error"]["code"] == "invalid_questions" and "needs options" in bad["error"]["message"]
    dup = await decide_tool(state="s", questions=[{"id": "q", "kind": "boolean", "prompt": "?"}] * 2)
    assert dup["error"]["message"] == "question ids must be unique"


@pytest.mark.asyncio
async def test_decide_tool_falls_back_when_jev_is_unavailable(monkeypatch):
    write_config({"decision": {"backend": "typesafe"}})  # no API key
    from dataclaw.providers.decision import registry

    llm = FakeLLM({"q": {"answer": True, "confidence": 0.6}})
    monkeypatch.setattr(routing, "utility_llm", lambda: llm)

    result = await decide_tool(state="s", questions=[{"id": "q", "kind": "boolean", "prompt": "?"}])

    assert registry.resolve_decision_backend() == "typesafe"
    assert result["backend"] == "llm"
    assert "TYPESAFE_API_KEY" in result["fallback_reason"]
    assert result["answers"][0]["calibrated"] is False
    assert llm.calls == 1


# ── Config API ──────────────────────────────────────────────────────────────


def test_decision_secrets_are_masked_and_backends_listed():
    write_config({"decision": {"backend": "typesafe", "typesafe": {"api_key": "ts-secret-value-1234", "model": "jev-latest"}}})
    with TestClient(create_app()) as client:
        config = client.get("/api/config").json()
        backends = client.get("/api/providers/decision-backends").json()
        # A masked value sent back does not overwrite the stored key.
        client.patch("/api/config", json={"decision": {"typesafe": {"api_key": config["decision"]["typesafe"]["api_key"]}}})
    assert config["decision"]["typesafe"]["api_key"] != "ts-secret-value-1234"
    assert "ts-secret-value-1234" not in json.dumps(config)
    assert config["decision"]["typesafe"]["model"] == "jev-latest"
    assert json.loads(config_path().read_text())["decision"]["typesafe"]["api_key"] == "ts-secret-value-1234"
    assert {b["id"] for b in backends} >= {"typesafe", "llm"}


def test_default_config_has_decision_section_off():
    from dataclaw.config.schema import DataclawConfig

    decision = DataclawConfig().decision
    assert decision.backend == "none" and decision.min_confidence == 0.7
    assert decision.typesafe.model == "jev-latest"
    assert not (decision.routing.plan_gates or decision.routing.skill_routing or decision.routing.compaction)


# ── Compaction trigger ──────────────────────────────────────────────────────


def history(turns: int) -> list[Message]:
    messages: list[Message] = []
    for i in range(turns):
        messages.append(Message(role="user", content=f"question {i}"))
        messages.append(Message(role="assistant", content=f"answer {i}"))
    return messages


THRESHOLDS = {"max_messages": 10, "keep_recent": 2, "max_tokens": 100_000}


@pytest.mark.asyncio
async def test_early_compaction_toggle_off_makes_no_calls(backends):
    write_config({"decision": {"backend": "typesafe"}})
    assert await early.should_compact_early(DropOldCompactor(), history(8), **THRESHOLDS) is False
    assert backends["builds"] == []


@pytest.mark.asyncio
async def test_early_compaction_skips_until_near_threshold_or_when_impossible(backends):
    write_config({"decision": {"backend": "typesafe", "routing": {"compaction": True}}})
    assert await early.should_compact_early(DropOldCompactor(), history(4), **THRESHOLDS) is False
    assert await early.should_compact_early(NoopCompactor(), history(8), **THRESHOLDS) is False
    assert backends["builds"] == []


@pytest.mark.asyncio
async def test_early_compaction_follows_a_confident_yes(backends):
    write_config({"decision": {"backend": "typesafe", "routing": {"compaction": True}}})
    assert await early.should_compact_early(DropOldCompactor(), history(6), **THRESHOLDS) is True
    backends["primary"] = Primary(answer=False, confidence=0.9)
    assert await early.should_compact_early(DropOldCompactor(), history(6), **THRESHOLDS) is False


@pytest.mark.asyncio
async def test_early_compaction_low_confidence_falls_back_to_the_llm(backends):
    write_config({"decision": {"backend": "typesafe", "routing": {"compaction": True}}})
    backends["primary"] = Primary(answer=True, confidence=0.5)
    backends["llm"] = FakeLLM({"compact_now": {"answer": False, "confidence": 0.9}})
    assert await early.should_compact_early(DropOldCompactor(), history(6), **THRESHOLDS) is False
    assert backends["llm"].calls == 1


class RecordingCompactor:
    def __init__(self, required: bool) -> None:
        self.required = required
        self.compact_kwargs: list[dict[str, Any]] = []

    def will_compact(self, messages, *, max_messages=30, max_tokens=0):
        return self.required

    async def compact(self, messages, **kwargs):
        self.compact_kwargs.append(kwargs)
        return messages


class Agent:
    async def stream_turn(self, state):
        yield TextDeltaEvent(text="ok")
        yield TurnCompleteEvent(has_pending_tool_calls=False)


async def _run_chat(session_id: str, mock_providers) -> None:
    await sessions.create_session(session_id=session_id, title="decisions")
    mock_providers.agent = Agent()
    get_run_tracker().start_run(session_id, f"{session_id}-run")
    await chat._run_agent_loop(session_id, f"{session_id}-run", [{"role": "user", "content": "hi"}], "hi", mock_providers, HookRegistry())


@pytest.mark.asyncio
async def test_chat_compacts_early_with_keep_recent_as_the_limit(mock_providers, monkeypatch):
    calls: list[dict[str, Any]] = []

    async def yes(compaction, messages, **kwargs):
        calls.append(kwargs)
        return True

    monkeypatch.setattr(chat, "should_compact_early", yes)
    mock_providers.compaction = RecordingCompactor(required=False)
    await _run_chat("early-compaction", mock_providers)
    assert len(calls) == 1
    [kwargs] = mock_providers.compaction.compact_kwargs
    assert kwargs["max_messages"] == kwargs["keep_recent"] == calls[0]["keep_recent"]


@pytest.mark.asyncio
async def test_chat_required_compaction_never_consults_the_decision_model(mock_providers, monkeypatch):
    async def fail(*args, **kwargs):
        raise AssertionError("decision consulted for a required compaction")

    monkeypatch.setattr(chat, "should_compact_early", fail)
    mock_providers.compaction = RecordingCompactor(required=True)
    await _run_chat("required-compaction", mock_providers)
    [kwargs] = mock_providers.compaction.compact_kwargs
    assert kwargs["max_messages"] == 30
