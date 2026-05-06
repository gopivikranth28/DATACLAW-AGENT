"""SubAgentProvider protocol and associated data types.

Sub-agents are delegated a task, receive a context bag with tools/config,
and run for a limited number of turns. They expose their config needs
to the UI via config_schema().
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, runtime_checkable

from dataclaw.providers.config_field import ConfigField


# ── Data types ─────────────────────────────────────────────────────────────


@dataclass
class SubAgentContext:
    """Everything the delegation tool knows — providers take what they need.

    Fields:
        definition: Full subagent JSON definition.
        tools: Filtered tool schemas (may be empty for non-tool agents).
        tool_callables: Filtered tool callables (may be empty).
        config: definition["config"] — max_turns, model, collection_name, etc.
        emit: Optional callback to push SSE events for UI progress.
        sub_agent_hooks: Optional hook registry for tool-call hooks.
    """

    definition: dict[str, Any]
    tools: list[dict[str, Any]] = field(default_factory=list)
    tool_callables: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)
    emit: Callable[[str], None] | None = None
    sub_agent_hooks: Any | None = None  # SubAgentHookRegistry (avoid circular import)
    prior_messages: list[dict[str, Any]] = field(default_factory=list)
    conversation_id: str = ""


@dataclass
class SubAgentResult:
    """Standardized output from a sub-agent execution."""

    status: str  # "completed" | "max_turns_reached" | "error"
    result: str
    turns_used: int = 0
    conversation_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "status": self.status,
            "result": self.result,
            "turns_used": self.turns_used,
        }
        if self.conversation_id:
            d["conversation_id"] = self.conversation_id
        if self.metadata:
            d["metadata"] = self.metadata
        return d


# ── Hook event types ───────────────────────────────────────────────────────


@dataclass
class DelegateEvent:
    """Passed to on_delegate and on_delegate_response hooks."""

    subagent_name: str
    agent_type: str
    task: str
    context: SubAgentContext
    result: SubAgentResult | None = None  # None in pre-hook, populated in post-hook


@dataclass
class SubAgentToolCallEvent:
    """Passed to on_subagent_tool_call hooks (before tool execution)."""

    subagent_name: str
    agent_type: str
    tool_name: str
    tool_input: dict[str, Any]


@dataclass
class SubAgentToolResultEvent:
    """Passed to on_subagent_tool_result hooks (after tool execution)."""

    subagent_name: str
    agent_type: str
    tool_name: str
    tool_input: dict[str, Any]
    result: dict[str, Any]
    error: Exception | None = None


# ── Provider protocol ──────────────────────────────────────────────────────


@runtime_checkable
class SubAgentProvider(Protocol):
    """Executes a delegated task for a specific agent_type."""

    agent_type: str

    @classmethod
    def config_schema(cls) -> list[ConfigField]:
        """Return config fields this agent type needs. Broadcast to UI."""
        ...

    async def run(self, task: str, *, context: SubAgentContext) -> SubAgentResult:
        """Execute the delegated task.

        Providers read what they need from context and ignore the rest.
        Use context.emit to push progress events to the UI.
        """
        ...
