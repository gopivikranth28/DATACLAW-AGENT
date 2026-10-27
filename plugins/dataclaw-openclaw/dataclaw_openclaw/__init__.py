"""dataclaw-openclaw — OpenClaw agent runtime plugin."""

from __future__ import annotations

import logging
from pathlib import Path

from dataclaw.plugins.base import (
    DataclawPlugin,
    PluginContext,
    PluginUIManifest,
    PluginConfigField,
)

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
        if ctx.session_cleanup_registry is not None:
            from dataclaw_openclaw.bridge import destroy_bridge

            def _cleanup_bridge(session):
                destroy_bridge(str(session.get("id") or ""))
                return {"removed": True}

            ctx.session_cleanup_registry.register("openclaw_bridge", _cleanup_bridge)
        logger.info("OpenClaw plugin: install + skill sync + tool proxy routers registered")

        async def _factory(factory_ctx):
            from dataclaw.config.resolver import resolve
            from dataclaw.providers.agent.factory import (
                RuntimeBundle,
                RuntimeDiagnostics,
                RuntimeIdentity,
            )
            from dataclaw_openclaw.agent_provider import OpenClawAgentProvider

            url = resolve(
                "plugins.openclaw.url",
                "DATACLAW_OPENCLAW_URL",
                "http://127.0.0.1:18789",
            )
            from dataclaw_openclaw.shared_token import resolve_shared_token

            token = resolve_shared_token()
            wait_ms = int(
                resolve(
                    "plugins.openclaw.wait_ms",
                    "DATACLAW_OPENCLAW_WAIT_MS",
                    "0",
                )
            )
            provider = OpenClawAgentProvider(
                url=url, token=token, wait_ms=wait_ms
            )
            # Every runtime receives the same DataClaw-owned utility model for
            # compaction and delegated sub-agents.
            base = factory_ctx.base_bundle
            return RuntimeBundle(
                agent=provider,
                utility_llm=base.llm,
                compaction=base.compaction,
                tool_availability=base.tool_availability,
                sub_agent_registry=base.sub_agent_registry,
                sub_agent_hooks=base.sub_agent_hooks,
                memory=base.memory,
                system_prompt=base.system_prompt,
                skill=base.skill,
                hooks=factory_ctx.hooks.clone(),
                runtime_control=None,
                identity=RuntimeIdentity(runtime="openclaw"),
                diagnostics=RuntimeDiagnostics(
                    details={"url": url}
                ),
            )

        ctx.providers.register_runtime_factory("openclaw", _factory)
        logger.info("OpenClaw plugin: runtime factory registered")

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
                    description="Token shared between Dataclaw and OpenClaw (sent in the X-Dataclaw-Token header in both directions). Leave empty to use the Dataclaw API token; when API authentication is enforced the API token is always used. Reinstall the plugin after changing it.",
                    default="",
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
