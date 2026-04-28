"""OpenClawAgentProvider — delegates agent turns to an OpenClaw runtime.

Fire-and-forget: POSTs the user message to OpenClaw, then yields a
TurnCompleteEvent immediately. Tool calls and the final response arrive
via separate HTTP endpoints (tool proxy + callback).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator

import httpx

from dataclaw.providers.agent.provider import AgentProvider, ConfigField
from dataclaw.providers.llm.provider import (
    BrokerEvent,
    TextDeltaEvent,
    TurnCompleteEvent,
)
from dataclaw.schema import Message
from dataclaw.state import AgentState

logger = logging.getLogger(__name__)


class OpenClawAgentProvider:
    """Agent provider that delegates to an OpenClaw runtime via HTTP."""

    def __init__(
        self,
        url: str,
        token: str = "",
        wait_ms: int = 0,
    ) -> None:
        self._url = url.rstrip("/")
        self._token = token
        self._wait_ms = wait_ms

    @classmethod
    def config_schema(cls) -> list[ConfigField]:
        return [
            ConfigField(
                name="openclaw_url",
                field_type="string",
                label="OpenClaw URL",
                description="Base URL of the OpenClaw gateway (e.g. http://127.0.0.1:18789)",
                required=True,
            ),
            ConfigField(
                name="openclaw_token",
                field_type="string",
                label="OpenClaw Token",
                description="Authentication token for the OpenClaw bridge",
            ),
            ConfigField(
                name="openclaw_wait_ms",
                field_type="int",
                label="Wait Timeout (ms)",
                description="How long to wait for OpenClaw response (0 = no timeout)",
                default=0,
            ),
        ]

    async def stream_turn(self, state: AgentState) -> AsyncIterator[BrokerEvent]:
        """Fire-and-forget POST to OpenClaw. Tool calls and response come via separate endpoints."""
        session_id = state.get("session_id", "default")
        messages = list(state.get("messages", []))

        user_text = _extract_last_user_text(messages)
        if not user_text:
            yield TextDeltaEvent(text="No user message found.")
            yield TurnCompleteEvent(has_pending_tool_calls=False)
            return

        # Health check — verify OpenClaw is reachable before sending
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                await client.get(f"{self._url}/dataclaw-frontend/health")
        except Exception:
            yield TextDeltaEvent(
                text="OpenClaw is not running or not reachable at "
                     f"`{self._url}`. Install and start OpenClaw from the "
                     "**Config** page, or switch to a direct LLM backend."
            )
            yield TurnCompleteEvent(has_pending_tool_calls=False)
            return

        # Fire HTTP request to OpenClaw (don't await — tool calls and response
        # arrive via tool proxy and callback endpoints)
        asyncio.create_task(self._post_to_openclaw(session_id, user_text))

        # Yield TurnCompleteEvent with skip_persist=True — the callback endpoint
        # will handle persisting the final response and emitting events.
        yield TurnCompleteEvent(has_pending_tool_calls=False, skip_persist=True)

    async def _post_to_openclaw(self, session_id: str, user_text: str) -> None:
        """POST user message to OpenClaw. Fire and forget."""
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._token:
            headers["X-Dataclaw-Token"] = self._token

        # When wait_ms=0 (no timeout), tell OpenClaw to wait a very long time.
        # OpenClaw interprets 0 as "don't wait", so we use 24 hours instead.
        oclaw_wait = self._wait_ms if self._wait_ms > 0 else 86_400_000

        payload = {
            "sessionId": session_id,
            "userId": "dataclaw",
            "text": user_text,
            "waitForResponseMs": oclaw_wait,
        }

        http_timeout = ((self._wait_ms / 1000) + 30) if self._wait_ms > 0 else None
        try:
            async with httpx.AsyncClient(timeout=http_timeout) as client:
                response = await client.post(
                    f"{self._url}/dataclaw-frontend/message",
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()

                # If OpenClaw returned a response, deliver it via the callback endpoint.
                # This handles the case where OpenClaw responds directly without tool calls.
                resp = data.get("response")
                if resp and resp.get("text"):
                    try:
                        async with httpx.AsyncClient(timeout=10) as cb_client:
                            await cb_client.post(
                                f"http://127.0.0.1:8000/api/agent/callback/{session_id}",
                                json={"text": resp["text"]},
                            )
                    except Exception:
                        logger.exception("Failed to deliver OpenClaw response via callback")

        except httpx.TimeoutException:
            logger.warning("OpenClaw HTTP timeout for session %s", session_id)
        except Exception as e:
            logger.exception("OpenClaw HTTP error for session %s", session_id)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _extract_last_user_text(messages: list[Message]) -> str:
    """Extract the text content of the last user message."""
    for msg in reversed(messages):
        if msg.role == "user" and isinstance(msg.content, str):
            return msg.content
    return ""
