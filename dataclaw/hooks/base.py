"""Hook protocol and error types."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from dataclaw.state import AgentState


class HookError(Exception):
    """Raised by a hook to abort the pipeline.

    If user_facing is True, the message is surfaced to the end user.
    Otherwise it is logged and the pipeline terminates silently.
    """

    def __init__(self, message: str, *, user_facing: bool = True) -> None:
        super().__init__(message)
        self.user_facing = user_facing


@runtime_checkable
class Hook(Protocol):
    """A pipeline hook.

    Receives the current AgentState and returns it — possibly modified.
    Raise HookError to abort the pipeline.
    """

    async def __call__(self, state: AgentState) -> AgentState: ...
