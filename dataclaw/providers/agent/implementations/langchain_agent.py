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
        from dataclaw.providers.llm.registry import list_llm_backends

        backends = list_llm_backends(include_hidden=True)
        return [
            ConfigField(
                name="llm_backend",
                field_type="select",
                label="LLM Backend",
                description="Which LLM provider to use",
                required=True,
                default="codex",
                options=[{"value": spec.id, "label": spec.label} for spec in backends],
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

        # Pass dynamic system prompt parts if the LLM supports it
        extra_kwargs: dict[str, Any] = {}
        system_dynamic = state.get("system_prompt_dynamic", "")
        if system_dynamic:
            extra_kwargs["system_dynamic"] = system_dynamic
        # Per-turn reasoning budget. Set by upstream nodes/hooks for turns that
        # warrant deeper thinking (e.g. the plans plugin elevates it while a plan
        # is being drafted). Unset on ordinary turns leaves the model at default.
        reasoning_effort = state.get("reasoning_effort")
        if reasoning_effort:
            extra_kwargs["reasoning_effort"] = reasoning_effort

        async for event in self._llm.stream_turn(
            messages, system=system, tools=tools, **extra_kwargs
        ):
            yield event
