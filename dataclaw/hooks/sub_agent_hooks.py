"""Sub-agent hook registry — lifecycle hooks for delegation and tool calls.

Separate from the pipeline HookRegistry because sub-agent hooks operate
on delegation-specific data types, not AgentState.
"""

from __future__ import annotations

from typing import Any, Callable, Awaitable

from dataclaw.hooks.base import HookError
from dataclaw.providers.sub_agent.provider import (
    DelegateEvent,
    SubAgentToolCallEvent,
    SubAgentToolResultEvent,
)

# Hook callable types
DelegateHook = Callable[[DelegateEvent], Awaitable[DelegateEvent]]
ToolCallHook = Callable[[SubAgentToolCallEvent], Awaitable[SubAgentToolCallEvent]]
ToolResultHook = Callable[[SubAgentToolResultEvent], Awaitable[SubAgentToolResultEvent]]


class SubAgentHookRegistry:
    """Manages hooks for the sub-agent delegation lifecycle.

    Four hook points:
        on_delegate          — before provider.run()
        on_delegate_response — after provider.run()
        on_subagent_tool_call   — before a sub-agent tool executes
        on_subagent_tool_result — after a sub-agent tool returns

    Hooks are called sequentially. Each receives the event from the
    previous hook and returns it (possibly modified). Raise HookError
    to abort.
    """

    def __init__(self) -> None:
        self._on_delegate: list[DelegateHook] = []
        self._on_delegate_response: list[DelegateHook] = []
        self._on_tool_call: list[ToolCallHook] = []
        self._on_tool_result: list[ToolResultHook] = []

    # ── Registration ───────────────────────────────────────────────────

    def on_delegate(self, hook: DelegateHook) -> None:
        """Register a hook that fires before sub-agent execution."""
        self._on_delegate.append(hook)

    def on_delegate_response(self, hook: DelegateHook) -> None:
        """Register a hook that fires after sub-agent execution."""
        self._on_delegate_response.append(hook)

    def on_subagent_tool_call(self, hook: ToolCallHook) -> None:
        """Register a hook that fires before each sub-agent tool call."""
        self._on_tool_call.append(hook)

    def on_subagent_tool_result(self, hook: ToolResultHook) -> None:
        """Register a hook that fires after each sub-agent tool result."""
        self._on_tool_result.append(hook)

    # ── Execution ──────────────────────────────────────────────────────

    async def run_delegate(self, event: DelegateEvent) -> DelegateEvent:
        """Run all on_delegate hooks. Raises HookError to abort."""
        for hook in self._on_delegate:
            event = await hook(event)
        return event

    async def run_delegate_response(self, event: DelegateEvent) -> DelegateEvent:
        """Run all on_delegate_response hooks."""
        for hook in self._on_delegate_response:
            event = await hook(event)
        return event

    async def run_tool_call(self, event: SubAgentToolCallEvent) -> SubAgentToolCallEvent:
        """Run all on_subagent_tool_call hooks. Raises HookError to abort."""
        for hook in self._on_tool_call:
            event = await hook(event)
        return event

    async def run_tool_result(self, event: SubAgentToolResultEvent) -> SubAgentToolResultEvent:
        """Run all on_subagent_tool_result hooks."""
        for hook in self._on_tool_result:
            event = await hook(event)
        return event
