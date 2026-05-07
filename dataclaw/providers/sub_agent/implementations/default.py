"""Default sub-agent — limited-turn agent loop.

Receives a task and a SubAgentContext, runs a simple multi-turn loop
with the registered LLM until the task is done or max_turns is reached.
Emits progress events and fires tool-call hooks.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from dataclaw.providers.config_field import ConfigField
from dataclaw.providers.llm.provider import (
    LLMProvider,
    PendingToolCall,
    TextDeltaEvent,
    TurnCompleteEvent,
)
from dataclaw.providers.sub_agent.provider import (
    SubAgentContext,
    SubAgentResult,
    SubAgentToolCallEvent,
    SubAgentToolResultEvent,
)
from dataclaw.schema import Message

logger = logging.getLogger(__name__)


class DefaultSubAgentProvider:
    """Executes a delegated task with a limited-turn agent loop."""

    agent_type: str = "llm"

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    @classmethod
    def config_schema(cls) -> list[ConfigField]:
        return [
            ConfigField(
                name="system_prompt",
                field_type="text",
                label="System Prompt",
                description="Custom instructions for the sub-agent. If empty, a default prompt is used.",
            ),
            ConfigField(
                name="max_turns",
                field_type="int",
                label="Max Turns",
                description="Maximum turns for sub-agent execution",
                default=10,
            ),
        ]

    async def run(self, task: str, *, context: SubAgentContext) -> SubAgentResult:
        tools = context.tools
        tool_callables = context.tool_callables
        max_turns = context.config.get("max_turns", 10)
        emit = context.emit
        hooks = context.sub_agent_hooks
        subagent_name = context.definition.get("name", "unknown")

        conversation_id = context.conversation_id or str(uuid.uuid4())

        custom_prompt = context.config.get("system_prompt", "")
        if custom_prompt:
            system = f"{custom_prompt}\n\nYour task:\n\n{task}"
        else:
            system = f"You are a sub-agent. Complete the following task:\n\n{task}"

        # Resume from prior conversation or start fresh
        if context.prior_messages:
            messages = [Message.from_dict(m) for m in context.prior_messages]
            messages.append(Message.user(task))
        else:
            messages: list[Message] = [Message.user(task)]

        # Emit start event
        if emit:
            from dataclaw.events.emitter import AgentEventEmitter
            _emitter = AgentEventEmitter.__new__(AgentEventEmitter)
            _emitter.encoder = __import__("ag_ui.encoder", fromlist=["EventEncoder"]).EventEncoder()
            emit(_emitter.custom("subagent:started", {
                "name": subagent_name,
                "agent_type": self.agent_type,
                "task": task,
                "conversation_id": conversation_id,
            }))

        for turn in range(max_turns):
            # Emit turn start
            if emit:
                emit(_emitter.step_started(f"subagent:turn:{turn + 1}"))

            text_chunks: list[str] = []
            pending: list[PendingToolCall] = []

            async for event in self._llm.stream_turn(
                messages, system=system, tools=tools
            ):
                if isinstance(event, TextDeltaEvent):
                    text_chunks.append(event.text)
                    if emit:
                        emit(_emitter.custom("subagent:text_delta", {
                            "name": subagent_name,
                            "text": event.text,
                        }))
                elif isinstance(event, PendingToolCall):
                    pending.append(event)
                elif isinstance(event, TurnCompleteEvent):
                    if not event.has_pending_tool_calls:
                        if emit:
                            emit(_emitter.step_finished(f"subagent:turn:{turn + 1}"))
                            emit(_emitter.custom("subagent:finished", {
                                "name": subagent_name,
                                "status": "completed",
                                "turns_used": turn + 1,
                                "conversation_id": conversation_id,
                            }))
                        final_text = "".join(text_chunks)
                        messages.append(Message.assistant(final_text))
                        return SubAgentResult(
                            status="completed",
                            result=final_text,
                            turns_used=turn + 1,
                            conversation_id=conversation_id,
                            metadata={"messages": [m.to_dict() for m in messages]},
                        )

            # Execute tool calls
            results: list[dict[str, Any]] = []
            errors: list[Exception | None] = []
            for tc in pending:
                # Pre-hook: on_subagent_tool_call
                tool_name = tc.tool_name
                tool_input = tc.tool_input
                if hooks:
                    hook_event = SubAgentToolCallEvent(
                        subagent_name=subagent_name,
                        agent_type=self.agent_type,
                        tool_name=tool_name,
                        tool_input=tool_input,
                    )
                    hook_event = await hooks.run_tool_call(hook_event)
                    tool_name = hook_event.tool_name
                    tool_input = hook_event.tool_input

                if emit:
                    emit(_emitter.custom("subagent:tool_call", {
                        "name": subagent_name,
                        "tool_name": tool_name,
                        "tool_input": tool_input,
                    }))

                fn = tool_callables.get(tool_name)
                if fn is None:
                    results.append({})
                    err = ValueError(f"Unknown tool: {tool_name}")
                    errors.append(err)
                    if hooks:
                        await hooks.run_tool_result(SubAgentToolResultEvent(
                            subagent_name=subagent_name,
                            agent_type=self.agent_type,
                            tool_name=tool_name,
                            tool_input=tool_input,
                            result={},
                            error=err,
                        ))
                    continue
                try:
                    result = await fn(**tool_input)
                    results.append(result)
                    errors.append(None)
                except Exception as e:
                    result = {}
                    results.append(result)
                    errors.append(e)

                # Post-hook: on_subagent_tool_result
                if hooks:
                    result_event = SubAgentToolResultEvent(
                        subagent_name=subagent_name,
                        agent_type=self.agent_type,
                        tool_name=tool_name,
                        tool_input=tool_input,
                        result=result,
                        error=errors[-1],
                    )
                    result_event = await hooks.run_tool_result(result_event)
                    results[-1] = result_event.result

                if emit:
                    emit(_emitter.custom("subagent:tool_result", {
                        "name": subagent_name,
                        "tool_name": tool_name,
                        "status": "error" if errors[-1] else "ok",
                    }))

            # Build tool result messages and continue
            tool_msgs = self._llm.build_tool_result_message(pending, results, errors)
            messages.extend(tool_msgs)

            if emit:
                emit(_emitter.step_finished(f"subagent:turn:{turn + 1}"))

        # Max turns reached
        if emit:
            emit(_emitter.custom("subagent:finished", {
                "name": subagent_name,
                "status": "max_turns_reached",
                "turns_used": max_turns,
                "conversation_id": conversation_id,
            }))

        return SubAgentResult(
            status="max_turns_reached",
            result="",
            turns_used=max_turns,
            conversation_id=conversation_id,
            metadata={"messages": [m.to_dict() for m in messages]},
        )
