"""AG-UI event emitter — helper class for streaming agent events.

Wraps the AG-UI EventEncoder and provides typed helper methods
for each event type used in the agent pipeline.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from ag_ui.core import (
    EventType,
    RunStartedEvent,
    RunFinishedEvent,
    RunErrorEvent,
    StepStartedEvent,
    StepFinishedEvent,
    TextMessageStartEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    ToolCallStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    StateSnapshotEvent,
    StateDeltaEvent,
    CustomEvent,
)
from ag_ui.encoder import EventEncoder


class AgentEventEmitter:
    """Emits AG-UI protocol events as SSE-encoded strings."""

    def __init__(self, thread_id: str, run_id: str | None = None) -> None:
        self.encoder = EventEncoder()
        self.thread_id = thread_id
        self.run_id = run_id or str(uuid.uuid4())
        self._message_id: str | None = None

    # ── Lifecycle events ────────────────────────────────────────────────

    def run_started(self) -> str:
        return self.encoder.encode(
            RunStartedEvent(
                type=EventType.RUN_STARTED,
                thread_id=self.thread_id,
                run_id=self.run_id,
            )
        )

    def run_finished(self) -> str:
        return self.encoder.encode(
            RunFinishedEvent(
                type=EventType.RUN_FINISHED,
                thread_id=self.thread_id,
                run_id=self.run_id,
            )
        )

    def run_error(self, message: str) -> str:
        return self.encoder.encode(
            RunErrorEvent(
                type=EventType.RUN_ERROR,
                message=message,
            )
        )

    def step_started(self, step_name: str) -> str:
        return self.encoder.encode(
            StepStartedEvent(
                type=EventType.STEP_STARTED,
                step_name=step_name,
            )
        )

    def step_finished(self, step_name: str) -> str:
        return self.encoder.encode(
            StepFinishedEvent(
                type=EventType.STEP_FINISHED,
                step_name=step_name,
            )
        )

    # ── Text message events ─────────────────────────────────────────────

    def text_message_start(self, message_id: str | None = None) -> str:
        self._message_id = message_id or str(uuid.uuid4())
        return self.encoder.encode(
            TextMessageStartEvent(
                type=EventType.TEXT_MESSAGE_START,
                message_id=self._message_id,
                role="assistant",
            )
        )

    def text_delta(self, delta: str, message_id: str | None = None) -> str:
        return self.encoder.encode(
            TextMessageContentEvent(
                type=EventType.TEXT_MESSAGE_CONTENT,
                message_id=message_id or self._message_id or "",
                delta=delta,
            )
        )

    def text_message_end(self, message_id: str | None = None) -> str:
        return self.encoder.encode(
            TextMessageEndEvent(
                type=EventType.TEXT_MESSAGE_END,
                message_id=message_id or self._message_id or "",
            )
        )

    # ── Tool call events ────────────────────────────────────────────────

    def tool_call_start(self, tool_call_id: str, tool_call_name: str) -> str:
        return self.encoder.encode(
            ToolCallStartEvent(
                type=EventType.TOOL_CALL_START,
                tool_call_id=tool_call_id,
                tool_call_name=tool_call_name,
            )
        )

    def tool_call_args(self, tool_call_id: str, delta: str) -> str:
        return self.encoder.encode(
            ToolCallArgsEvent(
                type=EventType.TOOL_CALL_ARGS,
                tool_call_id=tool_call_id,
                delta=delta,
            )
        )

    def tool_call_end(self, tool_call_id: str) -> str:
        return self.encoder.encode(
            ToolCallEndEvent(
                type=EventType.TOOL_CALL_END,
                tool_call_id=tool_call_id,
            )
        )

    def tool_call_result(self, tool_call_id: str, content: str, message_id: str | None = None) -> str:
        return self.encoder.encode(
            ToolCallResultEvent(
                type=EventType.TOOL_CALL_RESULT,
                tool_call_id=tool_call_id,
                content=content,
                message_id=message_id or self._message_id or "",
            )
        )

    # ── State events ────────────────────────────────────────────────────

    def state_snapshot(self, snapshot: dict[str, Any]) -> str:
        return self.encoder.encode(
            StateSnapshotEvent(
                type=EventType.STATE_SNAPSHOT,
                snapshot=snapshot,
            )
        )

    def state_delta(self, delta: list[dict[str, Any]]) -> str:
        return self.encoder.encode(
            StateDeltaEvent(
                type=EventType.STATE_DELTA,
                delta=delta,
            )
        )

    # ── Custom events ───────────────────────────────────────────────────

    def custom(self, name: str, value: Any = None) -> str:
        return self.encoder.encode(
            CustomEvent(
                type=EventType.CUSTOM,
                name=name,
                value=value,
            )
        )
