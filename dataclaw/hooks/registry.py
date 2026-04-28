"""Hook registry — ordered hook lists per pipeline point."""

from __future__ import annotations

from dataclaw.hooks.base import Hook
from dataclaw.state import AgentState

HOOK_POINTS: list[str] = [
    "userQueryHook",
    "postCompactionHook",
    "postSystemPromptHook",
    "postMemoryHook",
    "postSkillHook",
    "postToolAvailabilityHook",
    "preToolCallHook",
    "postToolCallHook",
    "postAgentMessageHook",
]


class HookRegistry:
    """Manages ordered hook lists for each pipeline point."""

    def __init__(self) -> None:
        self._hooks: dict[str, list[Hook]] = {point: [] for point in HOOK_POINTS}

    def register(self, point: str, hook: Hook) -> None:
        """Register a hook at the given pipeline point."""
        if point not in self._hooks:
            raise ValueError(
                f"Unknown hook point: {point!r}. Valid points: {HOOK_POINTS}"
            )
        self._hooks[point].append(hook)

    def unregister(self, point: str, hook: Hook) -> None:
        """Remove a hook from a pipeline point."""
        if point not in self._hooks:
            raise ValueError(
                f"Unknown hook point: {point!r}. Valid points: {HOOK_POINTS}"
            )
        self._hooks[point].remove(hook)

    async def run(self, point: str, state: AgentState) -> AgentState:
        """Run all hooks at the given point sequentially.

        Each hook receives the state returned by the previous hook.
        HookError propagates immediately, aborting the chain.
        """
        for hook in self._hooks.get(point, []):
            state = await hook(state)
        return state
