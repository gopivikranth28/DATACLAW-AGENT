"""LangChain-backed agent provider.

Uses the registered LLMProvider to stream a single agent turn,
passing the fully resolved system prompt, tools, and conversation
history from the pipeline state.
"""

from __future__ import annotations

from typing import Any, AsyncIterator

from dataclaw.providers.agent.provider import AgentProvider, ConfigField
from dataclaw.providers.llm.provider import BrokerEvent, LLMProvider
from dataclaw.state import AgentState


class LangChainAgentProvider:
    """Agent provider that delegates to an LLMProvider."""

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    @classmethod
    def config_schema(cls) -> list[ConfigField]:
        return [
            ConfigField(
                name="llm_backend",
                field_type="select",
                label="LLM Backend",
                description="Which LLM provider to use",
                required=True,
                default="anthropic",
                options=[
                    {"value": "mock", "label": "Mock (Testing)"},
                    {"value": "anthropic", "label": "Anthropic (Claude)"},
                    {"value": "openai", "label": "OpenAI"},
                    {"value": "gemini", "label": "Google Gemini"},
                ],
            ),
            ConfigField(
                name="llm_model",
                field_type="string",
                label="Model ID",
                description="Model identifier (leave empty for default)",
            ),
            ConfigField(
                name="max_turns",
                field_type="int",
                label="Max Turns",
                description="Maximum agent turns before stopping",
                default=30,
            ),
        ]

    async def stream_turn(self, state: AgentState) -> AsyncIterator[BrokerEvent]:
        system = state.get("system_prompt", "")
        messages = list(state.get("messages", []))
        tools = list(state.get("tools", []))

        async for event in self._llm.stream_turn(
            messages, system=system, tools=tools
        ):
            yield event
