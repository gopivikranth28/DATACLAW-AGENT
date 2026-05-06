"""Guardrail protocol and verdict model."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

from dataclaw.state import AgentState


@dataclass
class GuardrailVerdict:
    """Result of a guardrail evaluation that triggered."""

    tool_call_id: str
    guardrail_id: str
    message: str
    mode: Literal["auto_reply", "user_approval"]
    phase: Literal["pre", "post"] = "pre"
    severity: Literal["info", "warning", "danger"] = "warning"
    # Post-phase only: the original tool result before redaction.
    original_result: str | None = None


@runtime_checkable
class Guardrail(Protocol):
    """A guardrail that evaluates a tool call and optionally triggers.

    Pre-phase guardrails receive the tool call dict with keys:
        call_id, tool_name, tool_input

    Post-phase guardrails receive the same dict plus:
        result  — the serialized tool result string
    """

    id: str
    phase: Literal["pre", "post"]
    mode: Literal["auto_reply", "user_approval"]

    def evaluate(
        self, tool_call: dict[str, Any], state: AgentState
    ) -> GuardrailVerdict | None:
        """Return a verdict if this guardrail triggers, else None."""
        ...
