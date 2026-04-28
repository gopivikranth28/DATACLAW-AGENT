"""dataclaw-browser — AI-driven browser automation plugin."""

from __future__ import annotations

from dataclaw.plugins.base import (
    DataclawPlugin,
    PluginContext,
    PluginUIManifest,
    PluginConfigField,
)
from dataclaw.providers.tool.implementations.python_tool import PythonTool

from dataclaw_browser.tools import browser_use


class BrowserPlugin:
    name = "dataclaw-browser"
    depends_on: list[str] = ["dataclaw-workspace"]

    def register(self, ctx: PluginContext) -> None:
        plugin_cfg = ctx.config.plugins.get("browser", {})
        enabled = plugin_cfg.get("enabled", False)
        timeout_default = int(plugin_cfg.get("timeout_default", 300))
        timeout_max = int(plugin_cfg.get("timeout_max", 600))
        max_steps = int(plugin_cfg.get("max_steps", 100))
        llm_provider = plugin_cfg.get("llm_provider", "anthropic")
        llm_model = plugin_cfg.get("llm_model", "claude-sonnet-4-20250514")
        api_key = plugin_cfg.get("api_key", "")

        async def browser_use_wrapper(**kw):
            return await browser_use(
                enabled=enabled,
                timeout=kw.pop("timeout", timeout_default),
                max_steps=kw.pop("max_steps", max_steps),
                llm_provider=llm_provider,
                llm_model=llm_model,
                api_key=api_key,
                timeout_max=timeout_max,
                **kw,
            )

        ctx.tool_registry.register_tool(PythonTool(
            name="browser_use",
            description="Use an AI-driven browser to browse the web, extract content, and complete tasks",
            fn=browser_use_wrapper,
            parameters={
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "What to accomplish in the browser"},
                    "url": {"type": "string", "description": "Starting URL (optional)"},
                    "timeout": {"type": "integer", "description": f"Timeout in seconds (default {timeout_default}, max {timeout_max})"},
                    "max_steps": {"type": "integer", "description": f"Max browser actions (default {max_steps})"},
                    "save_to": {"type": "string", "description": "Save extracted content to this workspace file"},
                },
                "required": ["task"],
            },
        ))

    def ui_manifest(self) -> PluginUIManifest:
        return PluginUIManifest(
            id="browser",
            label="Browser",
            icon="",
            pages=[],
            config_title="Browser Automation",
            config_fields=[
                PluginConfigField(name="enabled", field_type="bool", label="Enabled", description="Enable browser automation tool", default=False),
                PluginConfigField(name="timeout_default", field_type="int", label="Default Timeout (sec)", default=300),
                PluginConfigField(name="timeout_max", field_type="int", label="Max Timeout (sec)", default=600),
                PluginConfigField(name="max_steps", field_type="int", label="Max Steps", default=100),
                PluginConfigField(name="llm_provider", field_type="select", label="Browser LLM Provider",
                                  options=[{"value": "anthropic", "label": "Anthropic"}, {"value": "openai", "label": "OpenAI"}],
                                  default="anthropic"),
                PluginConfigField(name="llm_model", field_type="string", label="Browser LLM Model", default="claude-sonnet-4-20250514"),
                PluginConfigField(name="api_key", field_type="string", label="API Key (override)", description="Leave empty to use the main LLM key"),
            ],
        )
