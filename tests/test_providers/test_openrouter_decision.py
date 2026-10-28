"""OpenRouter decision backend (Jev via the alpha Decisions API). No network."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from dataclaw.config.paths import config_path
from dataclaw.config.resolver import invalidate_cache
from dataclaw.providers.decision.implementations.openrouter_jev import (
    DECISIONS_URL,
    SYSTEMONE_URL,
    OpenRouterDecisionAPIError,
    OpenRouterJevProvider,
)
from dataclaw.providers.decision.provider import DecisionConfigurationError, DecisionQuestion
from dataclaw.providers.decision.registry import build_decision_provider, get_decision_backend
from dataclaw.providers.decision.routing import decide_with_fallback

QUESTIONS = [
    DecisionQuestion(id="billing", kind="boolean", prompt="Is this about billing?"),
    DecisionQuestion(id="tone", kind="choice", prompt="Tone?", options=["angry", "calm"],
                     option_descriptions={"angry": "Upset customer"}),
    DecisionQuestion(id="urgency", kind="score", prompt="Urgency?", options=["low", "medium", "high"]),
]

# Response shape from DecisionsResponse in https://openrouter.ai/openapi.json.
RESPONSE = {
    "id": "gen-dec-1",
    "model": "typesafe/jev-1.14-20261014",
    "provider": "TypeSafe",
    "answers": {
        "billing": {"type": "noul", "noul": 0.96},
        "tone": {"type": "choice", "choice": "angry", "confidence": 0.8, "probabilities": {"angry": 0.9, "calm": 0.1}},
        "urgency": {"type": "score", "score": 1.7, "confidence": 0.7, "legend": {"0": "low", "1": "medium", "2": "high"},
                    "probabilities": {"0": 0.05, "1": 0.2, "2": 0.75}},
    },
    "usage": {"input_tokens": 476, "output_tokens": 70, "cost": 1.9992e-05},
}


def write_config(data: dict[str, Any]) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    invalidate_cache()


@pytest.fixture(autouse=True)
def _fresh_config(monkeypatch):
    for name in ("OPENROUTER_API_KEY", "TYPESAFE_API_KEY", "DATACLAW_DECISION_BACKEND"):
        monkeypatch.delenv(name, raising=False)
    invalidate_cache()
    yield
    invalidate_cache()


class Recorder:
    def __init__(self, *responses: httpx.Response | Exception) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def provider(handler: Recorder, **kwargs: Any) -> tuple[OpenRouterJevProvider, list[float]]:
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    return OpenRouterJevProvider("sk-or-v1-test", transport=httpx.MockTransport(handler), sleep=sleep, **kwargs), sleeps


@pytest.mark.asyncio
async def test_decide_posts_the_decisions_request_and_parses_answers():
    handler = Recorder(httpx.Response(200, json=RESPONSE))
    jev, _ = provider(handler, routing={"data_collection": "deny", "zdr": True, "models": ["ignored/here"]})
    results = await jev.decide({"ticket": "I was charged twice"}, QUESTIONS)

    request = handler.requests[0]
    assert str(request.url) == DECISIONS_URL == "https://openrouter.ai/api/alpha/decisions"
    assert request.headers["authorization"] == "Bearer sk-or-v1-test"
    assert request.headers["x-openrouter-title"] == "DataClaw"
    assert "x-typesafe-retry-count" not in request.headers
    body = json.loads(request.content)
    assert body == {
        "model": "~typesafe/jev-latest",
        "state": {"ticket": "I was charged twice"},
        "questions": {
            "billing": {"type": "noul", "instructions": "Is this about billing?"},
            "tone": {"type": "choice", "instructions": "Tone?", "criteria": {"angry": "Upset customer", "calm": None}},
            "urgency": {"type": "score", "instructions": "Urgency?", "criteria": ["low", "medium", "high"]},
        },
        # Privacy routing applies; model fallbacks are chat-only.
        "provider": {"data_collection": "deny", "zdr": True},
    }

    by_id = {r.id: r for r in results}
    assert by_id["billing"].answer is True and by_id["billing"].confidence == pytest.approx(0.96)
    assert by_id["tone"].answer == "angry" and by_id["tone"].probabilities == {"angry": 0.9, "calm": 0.1}
    assert by_id["urgency"].answer == pytest.approx(1.7)
    assert jev.last_model == "typesafe/jev-1.14-20261014"
    assert jev.last_cost_usd == pytest.approx(1.9992e-05)


@pytest.mark.asyncio
async def test_system_one_endpoint_and_pinned_model():
    handler = Recorder(httpx.Response(200, json=RESPONSE))
    jev, _ = provider(handler, endpoint="systemone", model="typesafe/jev-1.13")
    await jev.decide("text state", QUESTIONS)
    assert str(handler.requests[0].url) == SYSTEMONE_URL
    body = json.loads(handler.requests[0].content)
    assert body["model"] == "typesafe/jev-1.13" and "provider" not in body


@pytest.mark.asyncio
async def test_retries_rate_limits_then_reports_openrouter_errors():
    handler = Recorder(
        httpx.Response(429, headers={"retry-after": "2"}, json={"error": {"code": 429, "message": "slow down"}}),
        httpx.Response(402, json={"error": {"code": 402, "message": "Insufficient credits"}}),
    )
    jev, sleeps = provider(handler)
    with pytest.raises(OpenRouterDecisionAPIError) as exc_info:
        await jev.decide("s", QUESTIONS)
    assert sleeps == [2.0]
    assert exc_info.value.status == 402
    assert str(exc_info.value).startswith("OpenRouter Decisions API error 402: Insufficient credits")
    assert "no credits" in str(exc_info.value)
    assert "sk-or-v1-test" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_gives_up_after_max_retries_on_transport_errors():
    handler = Recorder(httpx.ConnectError("down"), httpx.ConnectError("down"))
    jev, sleeps = provider(handler, max_retries=1)
    with pytest.raises(Exception, match="OpenRouter Decisions request failed: ConnectError"):
        await jev.decide("s", QUESTIONS)
    assert len(sleeps) == 1


def test_backend_uses_the_llm_backend_key_and_routing(monkeypatch):
    spec = get_decision_backend("openrouter")
    assert spec is not None and "alpha" in spec.label.lower()
    assert {f.name for f in spec.config_fields} == {"model", "endpoint", "timeout", "max_retries"}

    write_config({"decision": {"backend": "openrouter"}})
    with pytest.raises(DecisionConfigurationError, match="OPENROUTER_API_KEY or llm.backends.openrouter.api_key"):
        build_decision_provider()

    write_config({
        "decision": {"backend": "openrouter", "openrouter": {"model": "typesafe/jev-1.14", "timeout": 12}},
        "llm": {"backends": {"openrouter": {"api_key": "sk-or-v1-shared", "routing": {"zdr": True}}}},
    })
    built = build_decision_provider()
    assert isinstance(built, OpenRouterJevProvider)
    assert built.api_key == "sk-or-v1-shared"
    assert built.model == "typesafe/jev-1.14"
    assert built.timeout == 12
    assert built.url == DECISIONS_URL
    assert built._provider == {"zdr": True}

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-env")
    invalidate_cache()
    assert build_decision_provider().api_key == "sk-or-v1-env"

    write_config({
        "decision": {"backend": "openrouter", "openrouter": {"endpoint": "nope"}},
        "llm": {"backends": {"openrouter": {"api_key": "k"}}},
    })
    with pytest.raises(DecisionConfigurationError, match="Unknown OpenRouter decision endpoint"):
        build_decision_provider()


@pytest.mark.asyncio
async def test_missing_key_falls_back_to_the_llm():
    write_config({"decision": {"backend": "openrouter"}})

    class FakeLLM:
        async def structured_output(self, messages, schema, **kwargs):
            return {"billing": {"answer": True, "confidence": 0.9}}

        async def stream_turn(self, *args, **kwargs):  # pragma: no cover - not used
            if False:
                yield None

        def build_tool_result_message(self, *args):  # pragma: no cover - not used
            return []

    outcome = await decide_with_fallback("s", QUESTIONS[:1], llm=FakeLLM(), purpose="test")
    assert outcome.backend == "llm"
    assert "OpenRouter API key is not configured" in (outcome.fallback_reason or "")
