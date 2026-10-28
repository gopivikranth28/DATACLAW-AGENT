"""Shared ConfigField — describes a provider/plugin config field for the UI.

Providers and plugins use this to broadcast their configuration needs
so the frontend can auto-render settings forms without hardcoding.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ConfigField:
    """Describes a config field a provider needs, broadcast to the UI."""

    name: str
    field_type: str  # "string" | "secret" | "text" | "int" | "bool" | "select" | "multiselect" | "headers"
    label: str
    description: str = ""
    required: bool = False
    default: Any = None
    options: list[dict[str, str]] | None = None  # for select/multiselect
    env: str | None = None  # environment variable that overrides the saved value

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
        if self.env is not None:
            d["env"] = self.env
        return d
