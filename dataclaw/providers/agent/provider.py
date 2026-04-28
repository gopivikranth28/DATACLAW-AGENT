"""AgentProvider protocol and ConfigField.

The agent provider takes the fully populated pipeline state
and streams a response (text and/or tool calls). It broadcasts
its needed configuration via config_schema() so the UI can
render dynamic settings forms.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, AsyncIterator, Protocol, runtime_checkable

from dataclaw.providers.llm.provider import BrokerEvent
from dataclaw.state import AgentState


@dataclass
class ConfigField:
    """Describes a config field a provider needs, broadcast to the UI."""

    name: str
    field_type: str  # "string" | "text" | "int" | "bool" | "select" | "multiselect"
    label: str
    description: str = ""
    required: bool = False
    default: Any = None
    options: list[dict[str, str]] | None = None  # for select/multiselect

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "field_type": self.field_type,
            "label": self.label,
            "description": self.description,
            "required": self.required,
        }
        if self.default is not None:
            d["default"] = self.default
        if self.options is not None:
            d["options"] = self.options
        return d


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
