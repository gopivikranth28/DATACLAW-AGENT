"""OpenRouter LLM backend: catalog, request shaping, reasoning state and cost.

No network: the catalog comes from a trimmed recording of the public
``GET /api/v1/models`` (tests/fixtures/openrouter_models.json) and Chat
Completions calls go to an httpx MockTransport handed to the OpenAI client.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import httpx
import pytest

from dataclaw.config.resolver import invalidate_cache
from dataclaw.providers.decision.implementations.llm_fallback import LLMDecisionProvider
from dataclaw.providers.decision.provider import DecisionQuestion
from dataclaw.providers.llm import openrouter
from dataclaw.providers.llm.implementations.factory import llm_from_config
from dataclaw.providers.llm.implementations.langchain_llm import LangChainLLM
from dataclaw.providers.llm.implementations.openrouter_chat import OpenRouterChatOpenAI
from dataclaw.providers.llm.model_listing import ModelCatalogError
from dataclaw.providers.llm.provider import PendingToolCall, TurnCompleteEvent, UsageEvent
from dataclaw.providers.llm.registry import LLMConfigurationError, get_llm_backend, resolve_backend_config
from dataclaw.providers.llm.structured import structured_output
from dataclaw.schema import Message

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "openrouter_models.json"
CATALOG: list[dict[str, Any]] = json.loads(FIXTURE.read_text())["data"]

_ENV = ["OPENROUTER_API_KEY", "OPENROUTER_MODEL", "OPENAI_API_KEY", "OPENAI_BASE_URL", "DATACLAW_UTILITY_BACKEND"]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch):
    for name in _ENV:
        monkeypatch.delenv(name, raising=False)
    openrouter.set_catalog(CATALOG)
    invalidate_cache()
    yield
    openrouter.clear_catalog()
    invalidate_cache()


def _write_config(home: Path, config: dict) -> None:
    (home / "dataclaw.config.json").write_text(json.dumps(config))
    invalidate_cache()


def _entry(model_id: str) -> dict[str, Any]:
    return next(item for item in CATALOG if item["id"] == model_id)


# ── Mock Chat Completions server ────────────────────────────────────────────


class FakeOpenRouter:
    """Records requests; answers each with the next queued response."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.responses: list[Callable[[], httpx.Response]] = []

    @property
    def bodies(self) -> list[dict[str, Any]]:
        return [json.loads(r.content) for r in self.requests]

    def stream(self, *chunks: dict[str, Any]) -> None:
        payload = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
        self.responses.append(lambda: httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=payload.encode()
        ))

    def reply(self, body: dict[str, Any]) -> None:
        self.responses.append(lambda: httpx.Response(200, json=body))

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.responses.pop(0)()


def _llm(fake: FakeOpenRouter, model: str = "anthropic/claude-opus-5.5", **kwargs: Any) -> LangChainLLM:
    chat = OpenRouterChatOpenAI(
        model=model,
        api_key="sk-or-test",
        base_url=openrouter.OPENROUTER_API_BASE,
        default_headers=openrouter.attribution_headers(),
        stream_usage=True,
        http_async_client=httpx.AsyncClient(transport=httpx.MockTransport(fake.handler)),
        **kwargs,
    )
    return LangChainLLM(chat, compat=True)


def _chunk(delta: dict[str, Any], *, finish: str | None = None, model: str = "anthropic/claude-opus-5.5") -> dict[str, Any]:
    return {
        "id": "gen-1",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }


def _usage_chunk(cost: float) -> dict[str, Any]:
    return {
        "id": "gen-1",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": "anthropic/claude-opus-5.5",
        "choices": [],
        "usage": {
            "prompt_tokens": 120,
            "completion_tokens": 30,
            "total_tokens": 150,
            "cost": cost,
            "prompt_tokens_details": {"cached_tokens": 100},
            "completion_tokens_details": {"reasoning_tokens": 12},
        },
    }


def _tool_turn(fake: FakeOpenRouter) -> None:
    """A streamed turn: reasoning in fragments, one tool call, usage with cost."""
    fake.stream(
        _chunk({"role": "assistant", "content": "", "reasoning_details": [
            {"type": "reasoning.text", "text": "Let me ", "format": "anthropic-claude-v1", "index": 0},
        ]}),
        _chunk({"reasoning_details": [
            {"type": "reasoning.text", "text": "check.", "format": "anthropic-claude-v1", "index": 0},
        ]}),
        _chunk({"reasoning_details": [
            {"type": "reasoning.text", "signature": "sig-abc", "format": "anthropic-claude-v1", "index": 0},
        ]}),
        _chunk({"tool_calls": [{"index": 0, "id": "call_1", "type": "function",
                                "function": {"name": "lookup", "arguments": "{\"q\": \"x\"}"}}]}),
        _chunk({}, finish="tool_calls"),
        _usage_chunk(0.00125),
    )


TOOLS = [{"name": "lookup", "description": "Look up", "parameters": {"type": "object", "properties": {"q": {"type": "string"}}}}]


async def _collect(llm: LangChainLLM, messages: list[Message], **kwargs: Any) -> list[Any]:
    return [event async for event in llm.stream_turn(messages, system="You are DataClaw.", tools=TOOLS, **kwargs)]


# ── Catalog ─────────────────────────────────────────────────────────────────


def test_catalog_entry_maps_onto_model_info():
    info = openrouter.model_info(_entry("anthropic/claude-opus-5.5"))
    assert info is not None
    assert info.id == "anthropic/claude-opus-5.5"
    assert info.label == "Anthropic: Claude Opus 5.5 (anthropic/claude-opus-5.5)"
    assert info.context_window == 1_000_000
    assert info.max_output == 128_000
    assert info.supports_tools and info.supports_reasoning and info.supports_vision
    assert info.supports_structured_output
    # Lowest first; "none" is absent because reasoning is mandatory.
    assert info.reasoning_efforts == ["low", "medium", "high", "xhigh", "max"]
    assert info.prompt_price_per_mtok == pytest.approx(4.0)
    assert info.completion_price_per_mtok == pytest.approx(20.0)
    assert info.transport == "openai_chat"


def test_catalog_mapping_edge_cases():
    haiku = openrouter.model_info(_entry("anthropic/claude-haiku-5.5"))
    assert haiku is not None and haiku.reasoning_efforts[0] == "none"  # reasoning is optional
    # Routers have no fixed price ("-1").
    router = openrouter.model_info(_entry("typesafe/jev-router"))
    assert router is not None
    assert router.prompt_price_per_mtok is None and router.completion_price_per_mtok is None
    assert router.reasoning_efforts == []
    # Batch-only variants are not offered for chat.
    batch = next(item for item in CATALOG if item["id"].endswith(":batch"))
    assert openrouter.model_info(batch) is None
    # No tools, no structured outputs.
    moondream = openrouter.model_info(_entry("moondream/moondream3-preview"))
    assert moondream is not None and not moondream.supports_tools
    assert not moondream.supports_structured_output
    flint = openrouter.model_info(_entry("recursive/flint-v1.0:free"))
    assert flint is not None and flint.supports_tools and not flint.supports_structured_output


@pytest.mark.asyncio
async def test_list_models_is_sorted_and_skips_batch_variants():
    spec = get_llm_backend("openrouter")
    assert spec is not None and spec.list_models is not None
    models = await spec.list_models(resolve_backend_config("openrouter"))
    ids = [m.id for m in models]
    assert ids == sorted(ids, key=str.lower)
    assert not any(i.endswith(":batch") for i in ids)
    assert "google/gemini-3.8-flash" in ids


@pytest.mark.asyncio
async def test_catalog_is_fetched_without_credentials_and_cached(monkeypatch):
    openrouter.clear_catalog()
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"data": CATALOG})

    transport = httpx.MockTransport(handler)
    assert await openrouter.ensure_catalog(transport=transport)
    assert await openrouter.ensure_catalog(transport=transport)  # fresh: no second request
    assert len(seen) == 1
    assert str(seen[0].url) == "https://openrouter.ai/api/v1/models"
    assert "authorization" not in seen[0].headers
    assert openrouter.cached_model("x-ai/grok-4.7")["context_length"] == 500_000
    # Variant suffixes fall back to the base model's entry.
    assert openrouter.cached_model("x-ai/grok-4.7:nitro")["id"] == "x-ai/grok-4.7"

    # Past the TTL it is fetched again; a failure keeps the stale copy.
    openrouter.set_catalog(CATALOG, loaded_at=0.0)
    failing = httpx.MockTransport(lambda request: httpx.Response(503))
    assert await openrouter.ensure_catalog(transport=failing)
    assert openrouter.cached_model("x-ai/grok-4.7") is not None


@pytest.mark.asyncio
async def test_list_models_reports_an_unavailable_catalog(monkeypatch):
    openrouter.clear_catalog()

    async def unreachable(**kwargs):
        raise openrouter.OpenRouterCatalogError("Unable to reach OpenRouter to load models (ConnectError).")

    monkeypatch.setattr(openrouter, "fetch_catalog", unreachable)
    with pytest.raises(ModelCatalogError):
        await openrouter.list_models(resolve_backend_config("openrouter"))


# ── Build and credentials ───────────────────────────────────────────────────


def test_build_uses_openrouter_key_defaults_and_attribution(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-env")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-openai")
    llm = llm_from_config(backend="openrouter")
    assert isinstance(llm, LangChainLLM)
    model = llm._model
    assert isinstance(model, OpenRouterChatOpenAI)
    assert model.model_name == "anthropic/claude-opus-5.5"
    assert model.openai_api_base == "https://openrouter.ai/api/v1"
    assert model.openai_api_key.get_secret_value() == "sk-or-v1-env"
    assert model.default_headers == {
        "HTTP-Referer": "https://github.com/gopivikranth28/DATACLAW-AGENT",
        "X-OpenRouter-Title": "DataClaw",
    }
    assert model.use_responses_api is False
    assert model.stream_usage is True


def test_missing_key_never_falls_back_to_openai_key(tmp_dataclaw_home, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-openai")
    _write_config(tmp_dataclaw_home, {"llm": {"backends": {"openrouter": {"model": "x-ai/grok-4.7"}}}})
    with pytest.raises(LLMConfigurationError) as exc_info:
        llm_from_config(backend="openrouter")
    message = str(exc_info.value)
    assert "OPENROUTER_API_KEY" in message and "llm.backends.openrouter.api_key" in message
    assert "sk-real-openai" not in message


@pytest.mark.asyncio
async def test_requests_carry_only_the_openrouter_key(tmp_dataclaw_home, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-openai")
    _write_config(tmp_dataclaw_home, {"llm": {"backends": {"openrouter": {
        "api_key": "sk-or-v1-config",
        "model": "google/gemini-3.8-flash",
        "headers": {"X-OpenRouter-Title": "My Lab", "HTTP-Referer": ""},
    }}}})
    llm = llm_from_config(backend="openrouter")
    fake = FakeOpenRouter()
    fake.stream(_chunk({"role": "assistant", "content": "hi"}, finish="stop"), _usage_chunk(0.0))
    # Swap the OpenAI client's HTTP transport for the mock; the client as
    # built (key, base URL, headers) is what is under test.
    llm._model.root_async_client._client = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))
    await _collect(llm, [Message.user("hi")])
    request = fake.requests[0]
    assert request.url == "https://openrouter.ai/api/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer sk-or-v1-config"
    assert "sk-real-openai" not in request.headers.get("authorization", "")
    # A configured header overrides the default; an empty one removes it.
    assert request.headers["x-openrouter-title"] == "My Lab"
    assert "http-referer" not in request.headers


# ── Request shaping ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reasoning_is_sent_only_when_the_model_supports_it(monkeypatch):
    fake = FakeOpenRouter()
    for _ in range(3):
        fake.stream(_chunk({"role": "assistant", "content": "ok"}, finish="stop"), _usage_chunk(0.0))

    # Gemini accepts low/medium/high: "minimal" maps to the nearest, "low".
    await _collect(_llm(fake, "google/gemini-3.8-flash"), [Message.user("hi")], reasoning_effort="minimal", text_verbosity="low")
    body = fake.bodies[0]
    assert body["reasoning"] == {"effort": "low"}
    assert "reasoning_effort" not in body
    assert "verbosity" not in body  # not in Gemini's supported_parameters

    # A model without "reasoning" in supported_parameters gets neither knob.
    no_reasoning = dict(_entry("google/gemini-3.8-flash"), id="acme/plain")
    no_reasoning["supported_parameters"] = ["tools", "max_tokens"]
    openrouter.set_catalog([*CATALOG, no_reasoning])
    await _collect(_llm(fake, "acme/plain"), [Message.user("hi")], reasoning_effort="high")
    assert "reasoning" not in fake.bodies[1] and "reasoning_effort" not in fake.bodies[1]

    # Claude lists verbosity; unknown catalog state sends nothing optional.
    await _collect(_llm(fake, "anthropic/claude-opus-5.5"), [Message.user("hi")], reasoning_effort="high", text_verbosity="low")
    assert fake.bodies[2]["reasoning"] == {"effort": "high"}
    assert fake.bodies[2]["verbosity"] == "low"


def test_unknown_catalog_omits_optional_parameters():
    openrouter.clear_catalog()
    chat = _llm(FakeOpenRouter())._model
    payload = chat._get_request_payload([("user", "hi")], reasoning_effort="high", verbosity="low")
    assert "reasoning" not in (payload.get("extra_body") or {})
    assert "verbosity" not in (payload.get("extra_body") or {})
    assert "reasoning_effort" not in payload


@pytest.mark.asyncio
async def test_routing_preferences_and_fallbacks_reach_the_body():
    fake = FakeOpenRouter()
    fake.stream(_chunk({"role": "assistant", "content": "ok"}, finish="stop"), _usage_chunk(0.0))
    routing = {
        "data_collection": "deny",
        "zdr": True,
        "sort": "throughput",
        "order": ["anthropic", "amazon-bedrock"],
        "ignore": "deepinfra, together",
        "allow_fallbacks": False,
        "require_parameters": True,
        "max_price": {"prompt": 5, "completion": 25},
        "models": ["openai/gpt-6.1-sol", "google/gemini-3.8-flash"],
    }
    await _collect(_llm(fake, routing=routing), [Message.user("hi")])
    body = fake.bodies[0]
    assert body["provider"] == {
        "data_collection": "deny",
        "zdr": True,
        "order": ["anthropic", "amazon-bedrock"],
        "ignore": ["deepinfra", "together"],
        "allow_fallbacks": False,
        "require_parameters": True,
        "sort": "throughput",
        "max_price": {"prompt": 5.0, "completion": 25.0},
    }
    assert body["models"] == ["anthropic/claude-opus-5.5", "openai/gpt-6.1-sol", "google/gemini-3.8-flash"]
    assert body["model"] == "anthropic/claude-opus-5.5"


def test_default_routing_changes_nothing():
    for routing in (None, {}, {"data_collection": "allow", "zdr": False, "sort": "", "order": [], "models": []}):
        assert openrouter.routing_request_fields(routing, "anthropic/claude-opus-5.5") == {}


@pytest.mark.asyncio
async def test_claude_system_prompt_gets_a_cache_breakpoint_and_others_do_not():
    fake = FakeOpenRouter()
    for _ in range(2):
        fake.stream(_chunk({"role": "assistant", "content": "ok"}, finish="stop"), _usage_chunk(0.0))
    await _collect(_llm(fake, "anthropic/claude-opus-5.5"), [Message.user("hi")])
    await _collect(_llm(fake, "openai/gpt-6.1-sol"), [Message.user("hi")])
    claude_system = fake.bodies[0]["messages"][0]
    assert claude_system["role"] == "system"
    assert claude_system["content"] == [
        {"type": "text", "text": "You are DataClaw.", "cache_control": {"type": "ephemeral"}},
    ]
    assert fake.bodies[1]["messages"][0] == {"role": "system", "content": "You are DataClaw."}


# ── Reasoning details and cost ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reasoning_details_round_trip_across_a_tool_turn():
    fake = FakeOpenRouter()
    _tool_turn(fake)
    fake.stream(_chunk({"role": "assistant", "content": "Done."}, finish="stop"), _usage_chunk(0.0005))
    llm = _llm(fake)

    history = [Message.user("Look up x")]
    events = await _collect(llm, history, reasoning_effort="high")
    calls = [e for e in events if isinstance(e, PendingToolCall)]
    assert [c.tool_name for c in calls] == ["lookup"] and calls[0].tool_input == {"q": "x"}
    assert isinstance(events[-1], TurnCompleteEvent) and events[-1].has_pending_tool_calls

    tool_call, tool_result = llm.build_tool_result_message(calls, [{"value": 1}], [None])
    state = tool_call.provider_state
    assert state is not None
    assert state["provider"] == "OpenRouterChatOpenAI:anthropic/claude-opus-5.5"
    # Fragments are joined: text concatenated, the late signature kept.
    expected = [{
        "type": "reasoning.text",
        "text": "Let me check.",
        "format": "anthropic-claude-v1",
        "signature": "sig-abc",
        "index": 0,
    }]
    assert state["additional_kwargs"]["reasoning_details"] == expected
    # Survives serialization (sessions persist Messages as dicts).
    tool_call = Message.from_dict(json.loads(json.dumps(tool_call.to_dict())))

    await _collect(llm, [*history, tool_call, tool_result])
    assistant = fake.bodies[1]["messages"][2]
    assert assistant["role"] == "assistant"
    assert assistant["tool_calls"][0]["id"] == "call_1"
    assert assistant["reasoning_details"] == expected
    assert fake.bodies[1]["messages"][3] == {"role": "tool", "tool_call_id": "call_1", "content": "{\"value\": 1}"}


@pytest.mark.asyncio
async def test_reasoning_details_are_not_replayed_to_another_model():
    fake = FakeOpenRouter()
    _tool_turn(fake)
    fake.stream(_chunk({"role": "assistant", "content": "ok"}, finish="stop", model="openai/gpt-6.1-sol"), _usage_chunk(0.0))
    claude = _llm(fake)
    events = await _collect(claude, [Message.user("Look up x")])
    calls = [e for e in events if isinstance(e, PendingToolCall)]
    tool_call, tool_result = claude.build_tool_result_message(calls, [{"value": 1}], [None])

    await _collect(_llm(fake, "openai/gpt-6.1-sol"), [Message.user("Look up x"), tool_call, tool_result])
    assistant = fake.bodies[1]["messages"][2]
    assert assistant["tool_calls"][0]["id"] == "call_1"
    assert "reasoning_details" not in assistant


@pytest.mark.asyncio
async def test_cost_lands_in_the_usage_event():
    fake = FakeOpenRouter()
    _tool_turn(fake)
    events = await _collect(_llm(fake), [Message.user("Look up x")])
    usage = [e for e in events if isinstance(e, UsageEvent)]
    assert len(usage) == 1
    assert usage[0].cost_usd == pytest.approx(0.00125)
    assert usage[0].input_tokens == 120 and usage[0].output_tokens == 30
    assert usage[0].cached_input_tokens == 100 and usage[0].reasoning_tokens == 12


def test_collapse_keeps_complete_and_separate_items():
    details = [
        {"type": "reasoning.summary", "summary": "Plan", "_or_index": 0},
        {"type": "reasoning.encrypted", "data": "abc", "_or_index": 1},
        {"type": "reasoning.encrypted", "data": "def", "_or_index": 1},
        {"type": "reasoning.text", "text": "a"},
        {"type": "reasoning.text", "text": "b"},
    ]
    assert openrouter.collapse_reasoning_details(details) == [
        {"type": "reasoning.summary", "summary": "Plan", "index": 0},
        {"type": "reasoning.encrypted", "data": "abcdef", "index": 1},
        {"type": "reasoning.text", "text": "ab"},
    ]


# ── Structured output ───────────────────────────────────────────────────────

SCHEMA = {
    "type": "object",
    "properties": {"choice": {"type": "string"}, "confidence": {"type": "number"}},
    "required": ["choice", "confidence"],
    "additionalProperties": False,
}


def _completion(message: dict[str, Any], model: str) -> dict[str, Any]:
    return {
        "id": "gen-2",
        "object": "chat.completion",
        "created": 1,
        "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", **message}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15, "cost": 0.0001},
    }


@pytest.mark.asyncio
async def test_structured_output_uses_json_schema_when_the_model_lists_structured_outputs():
    fake = FakeOpenRouter()
    fake.reply(_completion({"content": json.dumps({"choice": "a", "confidence": 0.9})}, "anthropic/claude-haiku-5.5"))
    result = await structured_output(_llm(fake, "anthropic/claude-haiku-5.5"), [Message.user("pick")], SCHEMA, name="pick")
    assert result == {"choice": "a", "confidence": 0.9}
    body = fake.bodies[0]
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["name"] == "pick"
    assert "tools" not in body


@pytest.mark.asyncio
async def test_structured_output_falls_back_to_a_tool_call_otherwise():
    fake = FakeOpenRouter()
    model = "recursive/flint-v1.0:free"  # tools and response_format, but no structured_outputs
    fake.stream(
        _chunk({"role": "assistant", "content": "", "tool_calls": [{"index": 0, "id": "c", "type": "function",
                "function": {"name": "pick", "arguments": json.dumps({"choice": "b", "confidence": 0.6})}}]}, model=model),
        _chunk({}, finish="tool_calls", model=model),
    )
    result = await structured_output(_llm(fake, model), [Message.user("pick")], SCHEMA, name="pick")
    assert result == {"choice": "b", "confidence": 0.6}
    body = fake.bodies[0]
    assert "response_format" not in body
    assert [t["function"]["name"] for t in body["tools"]] == ["pick"]


@pytest.mark.asyncio
async def test_llm_decision_fallback_runs_on_the_openrouter_utility_model():
    fake = FakeOpenRouter()
    answers = {"route": {"answer": "sql", "confidence": 0.8}}
    fake.reply(_completion({"content": json.dumps(answers)}, "anthropic/claude-haiku-5.5"))
    provider = LLMDecisionProvider(_llm(fake, "anthropic/claude-haiku-5.5"))
    question = DecisionQuestion(id="route", kind="choice", prompt="Which tool?", options=["sql", "python"])
    results = await provider.decide("Count rows in the orders table", [question])
    assert results[0].answer == "sql"
    assert fake.bodies[0]["response_format"]["type"] == "json_schema"
