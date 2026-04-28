"""DataclawPlugin protocol and PluginContext.

Plugins are discovered via Python entry points and registered at startup.
Each plugin receives a PluginContext with all extension points.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from fastapi import FastAPI

from dataclaw.config.schema import DataclawConfig
from dataclaw.hooks.registry import HookRegistry
from dataclaw.plugins.registry import ProviderRegistry


@dataclass
class PluginContext:
    """Bundled extension points passed to plugins during registration."""
    hooks: HookRegistry
    providers: ProviderRegistry
    app: FastAPI
    config: DataclawConfig
    tool_registry: Any  # DefaultToolAvailability (avoid circular import)

    def include_api_router(self, router: Any, **kwargs: Any) -> None:
        """Register a router under the /api prefix. Plugins should use this instead of app.include_router()."""
        prefix = kwargs.pop("prefix", "")
        self.app.include_router(router, prefix=f"/api{prefix}", **kwargs)


@dataclass
class PluginPage:
    """Declares a UI page this plugin provides."""
    path: str       # e.g. "/data"
    label: str      # e.g. "Datasets"


@dataclass
class PluginConfigField:
    """Describes a config field for the plugin's UI config section."""
    name: str
    field_type: str  # "string" | "int" | "bool" | "select"
    label: str
    description: str = ""
    default: Any = None
    options: list[dict[str, str]] | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "field_type": self.field_type,
            "label": self.label,
            "description": self.description,
        }
        if self.default is not None:
            d["default"] = self.default
        if self.options is not None:
            d["options"] = self.options
        return d


@dataclass
class PluginUIManifest:
    """UI manifest for a plugin — drives frontend nav and config rendering."""
    id: str
    label: str
    icon: str = ""                          # Ant Design icon name
    pages: list[PluginPage] = field(default_factory=list)
    config_title: str = ""
    config_fields: list[PluginConfigField] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "icon": self.icon,
            "pages": [{"path": p.path, "label": p.label} for p in self.pages],
            "config_schema": {
                "title": self.config_title,
                "fields": [f.to_dict() for f in self.config_fields],
            } if self.config_title else None,
        }


@runtime_checkable
class DataclawPlugin(Protocol):
    """A dataclaw plugin. Discovered via entry points at startup."""

    name: str
    depends_on: list[str]

    def register(self, ctx: PluginContext) -> None:
        """Called once at startup. Register hooks, tools, routes, or swap providers."""
        ...

    def ui_manifest(self) -> PluginUIManifest | None:
        """Return a UI manifest, or None if this plugin has no UI presence."""
        ...
