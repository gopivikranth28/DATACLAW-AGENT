"""Tests for LLM providers."""

import pytest

from dataclaw.providers.llm.provider import TextDeltaEvent, TurnCompleteEvent
from tests.conftest import MockLLMProvider


@pytest.mark.asyncio
async def test_mock_llm_text_response():
    llm = MockLLMProvider(response_text="Hello!")
    events = []
    async for event in llm.stream_turn(
        [{"role": "user", "content": "hi"}],
        system="test",
        tools=[],
    ):
        events.append(event)

    assert any(isinstance(e, TextDeltaEvent) and e.text == "Hello!" for e in events)
    assert any(isinstance(e, TurnCompleteEvent) and not e.has_pending_tool_calls for e in events)


def test_native_reasoning_kwargs_maps_effort_per_provider():
    """Provider-agnostic effort maps to each SDK's native thinking field."""
    from dataclaw.providers.llm.implementations.langchain_llm import _native_reasoning_kwargs

    # Fake models identified only by class name (no SDK import needed).
    ChatOpenAI = type("ChatOpenAI", (), {})
    ChatAnthropic = type("ChatAnthropic", (), {})
    ChatGoogleGenerativeAI = type("ChatGoogleGenerativeAI", (), {})
    Unknown = type("SomeOtherModel", (), {})

    assert _native_reasoning_kwargs(ChatOpenAI(), "low") == {"reasoning_effort": "low"}
    assert _native_reasoning_kwargs(ChatAnthropic(), "medium") == {"effort": "medium"}
    # Anthropic 'effort' has no 'minimal' tier — fold it into 'low'.
    assert _native_reasoning_kwargs(ChatAnthropic(), "minimal") == {"effort": "low"}
    assert _native_reasoning_kwargs(ChatGoogleGenerativeAI(), "minimal") == {"thinking_level": "minimal"}
    # No effort, or an unrecognized model, leaves the call unchanged.
    assert _native_reasoning_kwargs(ChatOpenAI(), None) == {}
    assert _native_reasoning_kwargs(Unknown(), "low") == {}


@pytest.mark.asyncio
async def test_langchain_stream_binds_reasoning_effort():
    """LangChainLLM.stream_turn applies the native reasoning kwarg via bind()."""
    from dataclaw.providers.llm.implementations.langchain_llm import LangChainLLM

    bound_kwargs = {}

    class _FakeChunk:
        content = "hi"
        tool_call_chunks: list = []
        tool_calls: list = []
        def __add__(self, other):
            return self

    class _FakeBound:
        async def astream(self, messages):
            yield _FakeChunk()

    class ChatGoogleGenerativeAI:  # name drives the mapping
        def bind_tools(self, tools):
            return self
        def bind(self, **kwargs):
            bound_kwargs.update(kwargs)
            return _FakeBound()

    llm = LangChainLLM(ChatGoogleGenerativeAI())
    events = [e async for e in llm.stream_turn([], system="s", tools=[], reasoning_effort="low")]
    assert bound_kwargs == {"thinking_level": "low"}
    assert any(isinstance(e, TextDeltaEvent) for e in events)
