"""ToolCallBridge — bidirectional async channel between agent provider and tool proxy.

When OpenClaw calls /tools/{name}/call, the tool proxy pushes a tool call
into the bridge. The agent provider's stream_turn() picks it up and yields
it as a PendingToolCall. After chat.py executes the tool, stream_turn()
pushes the result back, unblocking the tool proxy to respond to OpenClaw.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Global registry of active bridges, keyed by session_id
_bridges: dict[str, ToolCallBridge] = {}


@dataclass
class ToolCallBridge:
    """Bidirectional async channel for a single agent session."""
    session_id: str
    # Tool proxy → agent provider
    incoming_calls: asyncio.Queue[dict[str, Any]] = field(default_factory=asyncio.Queue)
    # Agent provider → tool proxy
    outgoing_results: asyncio.Queue[dict[str, Any]] = field(default_factory=asyncio.Queue)
    # Signal that the OpenClaw HTTP response has arrived
    _response_event: asyncio.Event = field(default_factory=asyncio.Event)
    _response_data: dict[str, Any] | None = None

    # ── Tool proxy side ─────────────────────────────────────────────────

    async def push_tool_call(self, call: dict[str, Any]) -> None:
        """Called by tool proxy when OpenClaw requests a tool."""
        await self.incoming_calls.put(call)

    async def wait_for_tool_result(self, timeout: float = 300) -> dict[str, Any] | None:
        """Called by tool proxy — blocks until agent provider sends the result."""
        try:
            return await asyncio.wait_for(self.outgoing_results.get(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("Tool result timeout for session %s", self.session_id)
            return None

    # ── Agent provider side ─────────────────────────────────────────────

    async def push_tool_result(self, result: dict[str, Any]) -> None:
        """Called by agent provider after chat.py executed the tool."""
        await self.outgoing_results.put(result)

    def set_response(self, data: dict[str, Any]) -> None:
        """Called when the OpenClaw HTTP response arrives."""
        self._response_data = data
        self._response_event.set()

    async def wait_for_call_or_response(self, timeout: float | None = None) -> dict[str, Any]:
        """Wait for either a tool call from OpenClaw or the final HTTP response.

        Args:
            timeout: Seconds to wait, or None for no timeout.

        Returns:
            {"type": "tool_call", "call_id": ..., "tool_name": ..., "tool_input": ...}
            {"type": "response", "text": ..., "message_id": ...}
            {"type": "timeout"}
        """
        response_task = asyncio.create_task(self._wait_response())
        call_task = asyncio.create_task(self._wait_call())

        try:
            done, pending = await asyncio.wait(
                {response_task, call_task},
                timeout=timeout,  # None = wait forever
                return_when=asyncio.FIRST_COMPLETED,
            )

            # Cancel whichever didn't finish
            for task in pending:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

            if not done:
                return {"type": "timeout"}

            result = done.pop().result()
            return result

        except Exception as e:
            logger.exception("Bridge wait error for session %s", self.session_id)
            return {"type": "timeout"}

    async def _wait_response(self) -> dict[str, Any]:
        await self._response_event.wait()
        data = self._response_data or {}
        response = data.get("response") or {}
        text = response.get("text", "")
        if data.get("error"):
            text = str(data["error"])
        return {
            "type": "response",
            "text": text,
            "message_id": response.get("messageId", ""),
            "timed_out": data.get("timedOut", False),
        }

    async def _wait_call(self) -> dict[str, Any]:
        call = await self.incoming_calls.get()
        return {"type": "tool_call", **call}


# ── Registry ────────────────────────────────────────────────────────────────


def create_bridge(session_id: str) -> ToolCallBridge:
    """Create and register a new bridge for a session."""
    bridge = ToolCallBridge(session_id=session_id)
    _bridges[session_id] = bridge
    logger.debug("Created bridge for session %s", session_id)
    return bridge


def get_bridge(session_id: str) -> ToolCallBridge | None:
    """Look up an active bridge by session_id."""
    return _bridges.get(session_id)


async def wait_for_bridge(session_id: str, timeout: float = 5.0) -> ToolCallBridge | None:
    """Wait briefly for a bridge to appear (handles race between creation and tool call arrival)."""
    bridge = _bridges.get(session_id)
    if bridge is not None:
        return bridge

    interval = 0.1
    elapsed = 0.0
    while elapsed < timeout:
        await asyncio.sleep(interval)
        elapsed += interval
        bridge = _bridges.get(session_id)
        if bridge is not None:
            logger.debug("Bridge appeared for session %s after %.1fs", session_id, elapsed)
            return bridge

    return None


def list_bridge_session_ids() -> list[str]:
    """Return the session_ids of all active bridges (for diagnostics)."""
    return list(_bridges.keys())


def destroy_bridge(session_id: str) -> None:
    """Remove a bridge from the registry."""
    _bridges.pop(session_id, None)
    logger.debug("Destroyed bridge for session %s", session_id)
