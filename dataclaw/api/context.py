"""Context variables for the agent loop.

Set by _run_agent_loop in chat.py so that tools executing within the
loop can access the current thread_id and event emitter without
explicit parameter plumbing.
"""

from __future__ import annotations

import contextvars
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dataclaw.events.emitter import AgentEventEmitter

current_thread_id: contextvars.ContextVar[str] = contextvars.ContextVar("current_thread_id")
current_emitter: contextvars.ContextVar[AgentEventEmitter] = contextvars.ContextVar("current_emitter")
