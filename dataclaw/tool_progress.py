"""Request-scoped progress reporting for long-running tools.

Tool schemas intentionally contain only model-supplied arguments. The agent
runner installs a callback in this context variable while a tool executes, so
deep helpers can report progress without adding private schema parameters or
coupling plugins to the HTTP layer.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Callable, Iterator


ToolProgressCallback = Callable[[dict[str, Any]], None]

_progress_callback: ContextVar[ToolProgressCallback | None] = ContextVar(
    "dataclaw_tool_progress_callback",
    default=None,
)


@contextmanager
def tool_progress_context(callback: ToolProgressCallback) -> Iterator[None]:
    """Make ``callback`` available to the currently executing async tool."""
    token = _progress_callback.set(callback)
    try:
        yield
    finally:
        _progress_callback.reset(token)


def emit_tool_progress(phase: str, label: str, **details: Any) -> None:
    """Emit a best-effort progress update for the current tool invocation."""
    callback = _progress_callback.get()
    if callback is None:
        return
    try:
        callback({
            "phase": phase,
            "label": label,
            **{key: value for key, value in details.items() if value is not None},
        })
    except Exception:
        # Progress is observability, never part of the tool's correctness path.
        return
