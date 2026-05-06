"""AgentProvider protocol.

The agent provider takes the fully populated pipeline state
and streams a response (text and/or tool calls). It broadcasts
its needed configuration via config_schema() so the UI can
render dynamic settings forms.
"""

from __future__ import annotations

from typing import AsyncIterator, Protocol, runtime_checkable

from dataclaw.providers.config_field import ConfigField  # noqa: F401 — re-export for backwards compat
from dataclaw.providers.llm.provider import BrokerEvent
from dataclaw.state import AgentState


@runtime_checkable
class AgentProvider(Protocol):
    """Orchestrates an LLM turn given the full pipeline state."""

    @classmethod
    def config_schema(cls) -> list[ConfigField]:
        """Return config fields this agent needs. Broadcast to UI."""
        ...

    def stream_turn(self, state: AgentState) -> AsyncIterator[BrokerEvent]:
        """Stream a single agent turn, yielding BrokerEvents."""
        ...
