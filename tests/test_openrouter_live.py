"""Live OpenRouter checks, skipped unless OPENROUTER_API_KEY is set.

Each makes one tiny paid request: a few-token chat completion on the cheap
utility default model, and one Jev decision (input tokens only).
"""

from __future__ import annotations

import os

import pytest

from dataclaw.providers.decision.implementations.openrouter_jev import OpenRouterJevProvider
from dataclaw.providers.decision.provider import DecisionQuestion
from dataclaw.providers.llm import openrouter
from dataclaw.providers.llm.implementations.langchain_llm import LangChainLLM
from dataclaw.providers.llm.implementations.openrouter_chat import OpenRouterChatOpenAI
from dataclaw.providers.llm.provider import TextDeltaEvent, UsageEvent
from dataclaw.schema import Message

LIVE_KEY = os.environ.get("OPENROUTER_API_KEY", "").strip()
pytestmark = pytest.mark.skipif(not LIVE_KEY, reason="set OPENROUTER_API_KEY to run live OpenRouter tests")


@pytest.mark.asyncio
async def test_live_tiny_completion_reports_cost():
    llm = LangChainLLM(
        OpenRouterChatOpenAI(
            model=openrouter.UTILITY_DEFAULT_MODEL,
            api_key=LIVE_KEY,
            base_url=openrouter.OPENROUTER_API_BASE,
            default_headers=openrouter.attribution_headers(),
            stream_usage=True,
            max_tokens=16,
        ),
        compat=True,
    )
    events = [e async for e in llm.stream_turn([Message.user("Reply with the single word: pong")], system="Be terse.", tools=[])]
    text = "".join(e.text for e in events if isinstance(e, TextDeltaEvent))
    usage = [e for e in events if isinstance(e, UsageEvent)]
    assert "pong" in text.lower()
    assert usage and usage[0].output_tokens > 0
    assert usage[0].cost_usd is not None and usage[0].cost_usd >= 0


@pytest.mark.asyncio
async def test_live_tiny_jev_decision():
    provider = OpenRouterJevProvider(LIVE_KEY, timeout=60)
    results = await provider.decide(
        "I was charged twice for my subscription.",
        [DecisionQuestion(id="billing", kind="boolean", prompt="Is this about billing?")],
    )
    assert results[0].answer is True
    assert (provider.last_model or "").startswith("typesafe/jev")
    assert provider.last_cost_usd is not None
