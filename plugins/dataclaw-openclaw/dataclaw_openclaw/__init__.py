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

        token = cfg.get("token", cfg.get("frontend_token", cfg.get("tools_token", "")))
        wait_ms = int(cfg.get("wait_ms", 0))

        # Replace the agent provider
        provider = OpenClawAgentProvider(url=url, token=token, wait_ms=wait_ms)
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
                    name="token",
                    field_type="string",
                    label="Shared Token",
                    description="Bearer token shared between Dataclaw and OpenClaw (sent in X-Dataclaw-Token header in both directions). Must match DATACLAW_TOKEN on the OpenClaw side.",
                    default="dataclaw-local",
                ),
                PluginConfigField(
                    name="tools_api_url",
                    field_type="string",
                    label="Dataclaw API URL (as seen by OpenClaw)",
                    description="Base URL OpenClaw uses to call back into Dataclaw (DATACLAW_API_URL env var on the OpenClaw side). Use http://host.docker.internal:8000 when OpenClaw runs in Docker on the same host, or your bridge URL when running across containers.",
                    default="http://localhost:8000",
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
                    label="Plugin Source Directory (Dataclaw side)",
                    description="Path to the openclaw-plugins directory as Dataclaw sees it. Used for the pre-flight manifest read.",
                    default=str(Path(__file__).resolve().parent.parent.parent.parent / "openclaw-plugins"),
                ),
                PluginConfigField(
                    name="openclaw_plugins_dir",
                    field_type="string",
                    label="Plugin Source Directory (OpenClaw side)",
                    description="Path to openclaw-plugins as the OpenClaw CLI sees it. Override this when OpenClaw runs in Docker and the source is mounted at a different path (e.g. /dataclaw/openclaw-plugins). Leave blank to reuse the Dataclaw-side path.",
                    default="",
                ),
            ],
        )
