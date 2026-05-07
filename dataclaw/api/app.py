"""FastAPI application factory.

All API routes live under /api/. Core routes are mounted here.
Plugins register routes via ctx.include_api_router() which auto-prefixes /api.
"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from dataclaw.api.deps import init_providers
from dataclaw.config.paths import config_path, ensure_dirs
from dataclaw.config.schema import DataclawConfig
from dataclaw.hooks.registry import HookRegistry
from dataclaw.plugins.base import PluginContext
from dataclaw.plugins.loader import discover_plugins
from dataclaw.plugins.registry import ProviderRegistry

logger = logging.getLogger(__name__)


def _bootstrap_core_schema_defaults(cfg_path: Path) -> None:
    """Backfill missing keys from the core DataclawConfig schema into the
    on-disk config.

    The first-run bootstrap only writes defaults when the file doesn't
    exist. Once it exists, new schema fields (e.g. ``compaction.max_tokens``
    added later) never make it onto disk, so ``resolve()`` falls back to
    the literal default in each call site — which can silently disagree
    with the schema default. This walks the schema defaults and adds only
    keys that are missing, never overwriting values the user has set.
    """
    if not cfg_path.exists():
        return
    try:
        raw = json.loads(cfg_path.read_text())
    except Exception:
        return

    defaults = DataclawConfig().model_dump()

    def _merge(dst: dict, src: dict) -> bool:
        changed = False
        for key, default_val in src.items():
            if key not in dst:
                dst[key] = default_val
                changed = True
            elif isinstance(default_val, dict) and isinstance(dst.get(key), dict):
                if _merge(dst[key], default_val):
                    changed = True
        return changed

    if _merge(raw, defaults):
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(json.dumps(raw, indent=2))
        logger.info("Backfilled missing core schema defaults into %s", cfg_path)


def _bootstrap_plugin_defaults(plugins: list, cfg_path: Path) -> None:
    """Write plugin config field defaults into the config file if not already set."""
    try:
        raw = json.loads(cfg_path.read_text()) if cfg_path.exists() else {}
    except Exception:
        raw = {}

    changed = False
    for plugin in plugins:
        if not hasattr(plugin, "ui_manifest"):
            continue
        try:
            manifest = plugin.ui_manifest()
        except Exception:
            continue
        if not manifest or not manifest.config_fields:
            continue

        plugin_id = manifest.id
        plugin_cfg = raw.setdefault("plugins", {}).setdefault(plugin_id, {})
        for field in manifest.config_fields:
            if field.name not in plugin_cfg and field.default is not None:
                plugin_cfg[field.name] = field.default
                changed = True

    if changed:
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(json.dumps(raw, indent=2))
        logger.info("Bootstrapped plugin config defaults into %s", cfg_path)


def _load_config() -> DataclawConfig:
    path = config_path()
    if path.exists():
        try:
            return DataclawConfig(**json.loads(path.read_text()))
        except Exception:
            # Log with traceback — silently falling back to defaults makes the
            # UI report the wrong backend in /api/providers because the in-memory
            # config diverges from what the resolver reads off disk.
            logger.exception(
                "Failed to parse %s; falling back to defaults. "
                "The Config UI will misreport active backends until this is fixed.",
                path,
            )
    return DataclawConfig()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    ensure_dirs()

    # Bootstrap default config on first run so settings are persisted
    cfg_path = config_path()
    if not cfg_path.exists():
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(json.dumps(DataclawConfig().model_dump(), indent=2))
        logger.info("Created default config at %s", cfg_path)
    else:
        # File exists — backfill any new schema defaults the user is missing.
        _bootstrap_core_schema_defaults(cfg_path)

    config = _load_config()
    registry = ProviderRegistry()
    hooks = HookRegistry()
    tool_registry = init_providers(registry)

    # Register memory ingest hook if a real memory provider is active
    from dataclaw.providers.memory.implementations.noop import NoopMemoryProvider
    if not isinstance(registry.memory, NoopMemoryProvider):
        from dataclaw.providers.memory.hooks import MemoryIngestHook
        hooks.register("postAgentMessageHook", MemoryIngestHook(registry.memory))

    # Register guardrail hooks
    from dataclaw.guardrails.registry import GuardrailRegistry
    from dataclaw.guardrails.definitions import (
        FileDeleteGuardrail,
        OutsideProjectGuardrail,
        CodeOutsideWorkspaceGuardrail,
        PlanCompletionGuardrail,
        CredentialDetectionGuardrail,
        ResponseTruncationGuardrail,
    )
    guardrail_registry = GuardrailRegistry()
    guardrail_registry.register(FileDeleteGuardrail())
    guardrail_registry.register(OutsideProjectGuardrail())
    guardrail_registry.register(CodeOutsideWorkspaceGuardrail())
    guardrail_registry.register(PlanCompletionGuardrail())
    guardrail_registry.register(CredentialDetectionGuardrail())
    guardrail_registry.register(ResponseTruncationGuardrail())
    hooks.register("preToolCallHook", guardrail_registry.as_pre_hook())
    hooks.register("postToolCallHook", guardrail_registry.as_post_hook())

    # Refresh the skill provider's per-request resolved set before each tool
    # call. Without this, `list_skills` and `fetch_skill` rely on
    # `FileSkillProvider._resolved_skills`, which is only populated by the
    # native chat router's `resolve_skills(state)` call — so tools reaching
    # the skill provider via the openclaw bridge proxy (or any other
    # non-chat-loop entrypoint) get an unfiltered or stale list. Note: this
    # writes to instance state, so concurrent requests with different
    # session_ids race; a contextvar-based fix is the proper cure but
    # overkill for the local single-user setup.
    skill_provider = registry.skill

    async def _refresh_resolved_skills(state):
        try:
            await skill_provider.resolve_skills(state)
        except Exception:
            logger.debug("skill provider resolve_skills failed during preToolCallHook", exc_info=True)
        return state

    hooks.register("preToolCallHook", _refresh_resolved_skills)

    ctx = PluginContext(
        hooks=hooks,
        providers=registry,
        app=app,
        config=config,
        tool_registry=tool_registry,
        guardrail_registry=guardrail_registry,
    )

    plugins = discover_plugins()
    for plugin in plugins:
        try:
            plugin.register(ctx)
            logger.info("Registered plugin: %s", plugin.name)
        except Exception:
            logger.exception("Failed to register plugin: %s", plugin.name)

    # Bootstrap plugin config defaults into the config file
    from dataclaw.config.resolver import invalidate_cache
    _bootstrap_plugin_defaults(plugins, cfg_path)
    invalidate_cache()  # Ensure resolver picks up newly written defaults

    app.state.providers = registry
    app.state.hooks = hooks
    app.state.config = config
    app.state.plugins_list = plugins
    app.state.guardrail_registry = guardrail_registry

    errors = registry.validate()
    for err in errors:
        logger.error("Provider error: %s", err)

    # Run async plugin initialization (e.g. MCP server connections).
    # on_event("startup") handlers are ignored when a lifespan is used,
    # so we call them here explicitly.
    for handler in app.router.on_startup:
        await handler()

    # Mount SPA static files AFTER all plugin routes are registered,
    # so the catch-all /{path:path} doesn't shadow plugin routes.
    _mount_spa(app)

    try:
        yield
    finally:
        # Run shutdown handlers
        for handler in app.router.on_shutdown:
            await handler()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Dataclaw API",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://localhost:8000", "http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Core routers — all under /api
    from dataclaw.api.routers import chat, config, skills, skill_library, tools, providers, files, terminal
    from dataclaw.api.routers import plugins_router, codex_auth, guardrails
    from dataclaw.api.routers.chat import agent_router

    app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
    app.include_router(config.router, prefix="/api/config", tags=["config"])
    app.include_router(skills.router, prefix="/api/skills", tags=["skills"])
    app.include_router(skill_library.router, prefix="/api/skill-library", tags=["skill-library"])
    app.include_router(tools.router, prefix="/api/tools", tags=["tools"])
    app.include_router(guardrails.router, prefix="/api/guardrails", tags=["guardrails"])
    app.include_router(providers.router, prefix="/api/providers", tags=["providers"])
    app.include_router(plugins_router.router, prefix="/api/plugins", tags=["plugins"])
    app.include_router(agent_router, prefix="/api", tags=["agent"])
    app.include_router(files.router, prefix="/api/workspace", tags=["workspace-files"])
    app.include_router(terminal.router, prefix="/api/terminal", tags=["terminal"])
    app.include_router(codex_auth.router, prefix="/api/codex", tags=["codex-auth"])

    return app


def _mount_spa(app: FastAPI) -> None:
    """Mount SPA static files. Called after all routes (including plugin routes) are registered."""
    ui_dir = Path(__file__).parent.parent.parent / "ui" / "dist"
    if not ui_dir.is_dir():
        return

    from fastapi.staticfiles import StaticFiles

    assets_dir = ui_dir / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="static-assets")

    @app.get("/{path:path}")
    async def spa_fallback(path: str):
        """Serve the UI. API routes take precedence over this catch-all."""
        file = ui_dir / path
        if file.is_file() and ".." not in path:
            return FileResponse(file)
        return FileResponse(ui_dir / "index.html")
