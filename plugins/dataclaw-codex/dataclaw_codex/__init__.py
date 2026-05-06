"""dataclaw-codex — OpenAI Codex subagent plugin.

Registers a CodexSubAgentProvider (agent_type="codex") so that
coding tasks can be delegated via the subagent system.
"""

from __future__ import annotations

from dataclaw.plugins.base import (
    DataclawPlugin,
    PluginContext,
    PluginUIManifest,
    PluginConfigField,
)

from dataclaw_codex.provider import CodexSubAgentProvider


class CodexPlugin:
    name = "dataclaw-codex"
    depends_on: list[str] = []

    def register(self, ctx: PluginContext) -> None:
        ctx.sub_agent_registry.register(CodexSubAgentProvider())

    def ui_manifest(self) -> PluginUIManifest:
        return PluginUIManifest(
            id="codex",
            label="Codex",
            icon="",
            pages=[],
            config_title="OpenAI Codex",
            config_fields=[
                PluginConfigField(
                    name="enabled",
                    field_type="bool",
                    label="Enabled",
                    description="Enable Codex subagent provider",
                    default=False,
                ),
            ],
        )
