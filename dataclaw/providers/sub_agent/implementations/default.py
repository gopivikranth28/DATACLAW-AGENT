"""Default sub-agent — limited-turn agent loop.

Receives a task, a set of tools and skills, and runs a simple
multi-turn loop with the registered LLM until the task is done
or max_turns is reached.
"""

from __future__ import annotations

from typing import Any

from dataclaw.providers.agent.provider import ConfigField
from dataclaw.providers.llm.provider import (
    LLMProvider,
    PendingToolCall,
    TextDeltaEvent,
    TurnCompleteEvent,
)
from dataclaw.schema import Message


class DefaultSubAgentProvider:
    """Executes a delegated task with a limited-turn agent loop."""

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    @classmethod
    def config_schema(cls) -> list[ConfigField]:
        return [
            ConfigField(
                name="max_turns",
                field_type="int",
                label="Max Turns",
                description="Maximum turns for sub-agent execution",
                default=10,
            ),
        ]

    async def run(
        self,
        task: str,
        *,
        tools: list[dict[str, Any]],
        skills: list[dict[str, Any]],
        tool_callables: dict[str, Any] | None = None,
        max_turns: int = 10,
    ) -> dict[str, Any]:
        tool_callables = tool_callables or {}
        system = f"You are a sub-agent. Complete the following task:\n\n{task}"

        messages: list[Message] = [Message.user(task)]

        for turn in range(max_turns):
            text_chunks: list[str] = []
            pending: list[PendingToolCall] = []

            async for event in self._llm.stream_turn(
                messages, system=system, tools=tools
            ):
                if isinstance(event, TextDeltaEvent):
                    text_chunks.append(event.text)
                elif isinstance(event, PendingToolCall):
                    pending.append(event)
                elif isinstance(event, TurnCompleteEvent):
                    if not event.has_pending_tool_calls:
                        return {
                            "status": "completed",
                            "result": "".join(text_chunks),
                            "turns_used": turn + 1,
                        }

            # Execute tool calls
            results: list[dict[str, Any]] = []
            errors: list[Exception | None] = []
            for tc in pending:
                fn = tool_callables.get(tc.tool_name)
                if fn is None:
                    results.append({})
                    errors.append(ValueError(f"Unknown tool: {tc.tool_name}"))
                    continue
                try:
                    result = await fn(**tc.tool_input)
                    results.append(result)
                    errors.append(None)
                except Exception as e:
                    results.append({})
                    errors.append(e)

            # Build tool result messages and continue
            tool_msgs = self._llm.build_tool_result_message(pending, results, errors)
            messages.extend(tool_msgs)

        return {
            "status": "max_turns_reached",
            "result": "",
            "turns_used": max_turns,
        }
