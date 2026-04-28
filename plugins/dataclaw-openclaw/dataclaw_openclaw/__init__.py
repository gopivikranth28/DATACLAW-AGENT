"""dataclaw-openclaw — OpenClaw agent runtime plugin.

Replaces the default AgentProvider with one that delegates to an
OpenClaw instance. Tool calls from OpenClaw are executed directly
via the tool proxy; final responses arrive via the callback endpoint.
"""

from __future__ import annotations

import logging
from pathlib import Path

from dataclaw.plugins.base import (
    DataclawPlugin,
    PluginContext,
    PluginUIManifest,
    PluginConfigField,
)

from dataclaw_openclaw.agent_provider import OpenClawAgentProvider
from dataclaw_openclaw.install_router import router as install_router
from dataclaw_openclaw.skill_sync import router as skill_sync_router
from dataclaw_openclaw.tool_proxy import router as tool_proxy_router

logger = logging.getLogger(__name__)


class OpenClawPlugin:
    name = "dataclaw-openclaw"
    depends_on: list[str] = []

    def register(self, ctx: PluginContext) -> None:
        # Always register these routes — needed before OpenClaw is fully configured
        ctx.include_api_router(install_router, prefix="/openclaw", tags=["openclaw-install"])
        ctx.include_api_router(skill_sync_router, prefix="/openclaw", tags=["openclaw-skills"])
        ctx.include_api_router(tool_proxy_router, tags=["openclaw-tools"])
        logger.info("OpenClaw plugin: install + skill sync + tool proxy routers registered")

        cfg = ctx.config.plugins.get("openclaw", {})
        url = cfg.get("url", "")

        if not url:
            logger.info("OpenClaw plugin: no URL configured, skipping agent provider swap")
            return

        frontend_token = cfg.get("frontend_token", cfg.get("token", ""))
        tools_token = cfg.get("tools_token", cfg.get("token", ""))
        wait_ms = int(cfg.get("wait_ms", 0))

        # Replace the agent provider
        provider = OpenClawAgentProvider(url=url, token=frontend_token, wait_ms=wait_ms)
        ctx.providers.replace("agent", provider)
        logger.info("OpenClaw plugin: agent provider replaced (url=%s)", url)

    def ui_manifest(self) -> PluginUIManifest:
        return PluginUIManifest(
            id="openclaw",
            label="OpenClaw",
            icon="",
            pages=[],
            config_title="OpenClaw Bridge",
            config_fields=[
                PluginConfigField(
                    name="url",
                    field_type="string",
                    label="OpenClaw Gateway URL",
                    description="Base URL of the OpenClaw gateway (e.g. http://127.0.0.1:18789)",
                    default="http://127.0.0.1:18789",
                ),
                PluginConfigField(
                    name="frontend_token",
                    field_type="string",
                    label="Frontend Token",
                    description="Token sent TO OpenClaw — must match DATACLAW_FRONTEND_TOKEN / channels.dataclaw-frontend.token on the OpenClaw side",
                    default="dataclaw-local",
                ),
                PluginConfigField(
                    name="tools_token",
                    field_type="string",
                    label="Tools Token",
                    description="Token expected FROM OpenClaw — must match DATACLAW_TOOLS_TOKEN on the OpenClaw side",
                    default="dataclaw-local",
                ),
                PluginConfigField(
                    name="wait_ms",
                    field_type="int",
                    label="Wait Timeout (ms)",
                    description="How long to wait for OpenClaw to respond (0 = no timeout)",
                    default=0,
                ),
                PluginConfigField(
                    name="openclaw_cmd",
                    field_type="string",
                    label="OpenClaw CLI Command",
                    description="Path or command to run the OpenClaw CLI (e.g. 'openclaw' or 'docker exec container openclaw')",
                    default="openclaw",
                ),
                PluginConfigField(
                    name="openclaw_dir",
                    field_type="string",
                    label="OpenClaw Config Directory",
                    description="Path to the directory containing .openclaw/ (used for token fetching)",
                    default="~",
                ),
                PluginConfigField(
                    name="plugins_source_dir",
                    field_type="string",
                    label="Plugin Source Directory",
                    description="Path to the openclaw-plugins directory containing dataclaw-tools and dataclaw-frontend",
                    default=str(Path(__file__).resolve().parent.parent.parent.parent / "openclaw-plugins"),
                ),
            ],
        )
