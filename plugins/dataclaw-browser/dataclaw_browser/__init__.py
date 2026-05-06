"""dataclaw-browser — AI-driven browser automation plugin.

Registers a BrowserSubAgentProvider (agent_type="browser") so that
browser tasks can be delegated via the subagent system.
"""

from __future__ import annotations

from dataclaw.plugins.base import (
    DataclawPlugin,
    PluginContext,
    PluginUIManifest,
)

from dataclaw_browser.provider import BrowserSubAgentProvider


class BrowserPlugin:
    name = "dataclaw-browser"
    depends_on: list[str] = ["dataclaw-workspace"]

    def register(self, ctx: PluginContext) -> None:
        ctx.sub_agent_registry.register(BrowserSubAgentProvider())

    def ui_manifest(self) -> PluginUIManifest:
        return PluginUIManifest(
            id="browser",
            label="Browser",
            icon="",
            pages=[],
        )
