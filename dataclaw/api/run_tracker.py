"""Run Tracker — in-memory event log for agent runs.

Stores SSE events server-side so frontends can disconnect and reconnect
without losing events. All agent providers (streaming LLM, OpenClaw, etc.)
write events here; the frontend tails the log via SSE.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Literal

logger = logging.getLogger(__name__)

# How long to keep finished runs for reconnection (seconds)
_FINISHED_RUN_TTL = 600  # 10 minutes
_MAX_EVENTS = 10_000


@dataclass
class RunState:
    run_id: str
    thread_id: str
    status: Literal["running", "finished", "error"] = "running"
    events: list[tuple[int, str]] = field(default_factory=list)
    cursor: int = 0
    queued_messages: asyncio.Queue[str] = field(default_factory=asyncio.Queue)
    task: asyncio.Task[Any] | None = None
    finished_at: float | None = None
    _waiters: list[asyncio.Event] = field(default_factory=list)
    _completion: asyncio.Event = field(default_factory=asyncio.Event)

    def append_event(self, event_str: str) -> int:
        """Append an event, notify all waiters, return cursor."""
        self.cursor += 1
        self.events.append((self.cursor, event_str))
        # Cap event log size
        if len(self.events) > _MAX_EVENTS:
            self.events = self.events[-_MAX_EVENTS:]
        # Wake up all tailers
        for w in self._waiters:
            w.set()
        self._waiters.clear()
        return self.cursor

    def get_events_after(self, after_cursor: int) -> list[tuple[int, str]]:
        """Return events with cursor > after_cursor."""
        return [(c, e) for c, e in self.events if c > after_cursor]

    async def wait_for_events(self, after_cursor: int, timeout: float = 15.0) -> list[tuple[int, str]]:
        """Wait for new events after the given cursor. Returns empty on timeout."""
        # Check for already-available events first
        available = self.get_events_after(after_cursor)
        if available:
            return available
        # Register a waiter and wait for notification
        waiter = asyncio.Event()
        self._waiters.append(waiter)
        try:
            await asyncio.wait_for(waiter.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            pass
        finally:
            # Clean up in case of timeout
            try:
                self._waiters.remove(waiter)
            except ValueError:
                pass
        return self.get_events_after(after_cursor)


class RunTracker:
    """Registry of active and recently-finished agent runs."""

    def __init__(self) -> None:
        self._runs: dict[str, RunState] = {}

    def start_run(self, thread_id: str, run_id: str, task: asyncio.Task[Any] | None = None) -> RunState:
        """Register a new active run. Replaces any existing run for this thread."""
        run = RunState(run_id=run_id, thread_id=thread_id, task=task)
        self._runs[thread_id] = run
        logger.info("Run started: thread=%s run=%s", thread_id, run_id)
        return run

    def get_run(self, thread_id: str) -> RunState | None:
        """Get the run state for a thread, or None."""
        self._cleanup_expired()
        return self._runs.get(thread_id)

    def append_event(self, thread_id: str, event_str: str) -> int:
        """Append an event to the run's log. Returns cursor or -1 if no run."""
        run = self._runs.get(thread_id)
        if run is None:
            return -1
        return run.append_event(event_str)

    def finish_run(self, thread_id: str, status: Literal["finished", "error"] = "finished") -> None:
        """Mark a run as finished. Starts the TTL countdown for cleanup."""
        run = self._runs.get(thread_id)
        if run is None:
            return
        run.status = status
        run.finished_at = time.monotonic()
        run._completion.set()
        # Wake up all tailers so they see the run is done
        for w in run._waiters:
            w.set()
        run._waiters.clear()
        logger.info("Run %s: thread=%s run=%s", status, thread_id, run.run_id)

    def cancel_run(self, thread_id: str) -> bool:
        """Cancel a running task. Returns True if cancelled."""
        run = self._runs.get(thread_id)
        if run is None or run.status != "running":
            return False
        if run.task is not None:
            run.task.cancel()
        return True

    def queue_message(self, thread_id: str, text: str) -> bool:
        """Queue a message for the running agent loop. Returns False if no active run."""
        run = self._runs.get(thread_id)
        if run is None or run.status != "running":
            return False
        run.queued_messages.put_nowait(text)
        return True

    def _cleanup_expired(self) -> None:
        """Remove finished runs past their TTL."""
        now = time.monotonic()
        expired = [
            tid for tid, run in self._runs.items()
            if run.finished_at is not None and (now - run.finished_at) > _FINISHED_RUN_TTL
        ]
        for tid in expired:
            del self._runs[tid]


# Singleton
_tracker: RunTracker | None = None


def get_run_tracker() -> RunTracker:
    """Get or create the global RunTracker singleton."""
    global _tracker
    if _tracker is None:
        _tracker = RunTracker()
    return _tracker
