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

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from dataclaw.api.deps import init_providers
from dataclaw.api.security import SecurityMiddleware, allowed_origins, log_startup_status
from dataclaw.config.paths import config_path, ensure_dirs
from dataclaw.config.schema import DataclawConfig
from dataclaw.config.secure_io import restrict_permissions, write_private_text
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
        write_private_text(cfg_path, json.dumps(raw, indent=2))
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
        write_private_text(cfg_path, json.dumps(raw, indent=2))
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
        write_private_text(cfg_path, json.dumps(DataclawConfig().model_dump(), indent=2))
        logger.info("Created default config at %s", cfg_path)
    else:
        # Config files written by older versions used the default umask.
        restrict_permissions(cfg_path)
        from dataclaw.config.migrations import migrate_config

        try:
            raw = json.loads(cfg_path.read_text())
            if migrate_config(raw):
                write_private_text(cfg_path, json.dumps(raw, indent=2))
                logger.info("Migrated runtime and LLM backend config in %s", cfg_path)
        except Exception:
            logger.exception("Failed to migrate runtime/LLM backend configuration")
        # File exists — backfill any new schema defaults the user is missing.
        _bootstrap_core_schema_defaults(cfg_path)

    log_startup_status()

    config = _load_config()
    registry = ProviderRegistry()
    hooks = HookRegistry()
    tool_registry = init_providers(registry)
    from dataclaw.storage.session_cleanup import SessionCleanupRegistry
    session_cleanup_registry = SessionCleanupRegistry()

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

    # Refresh the skill provider's request-local resolved set before each tool
    # call. Native chat resolves it earlier in the pipeline; bridge and other
    # entrypoints need the same session-aware boundary immediately before a
    # list/fetch operation. FileSkillProvider stores this in a ContextVar, so
    # concurrent sessions cannot overwrite each other's allowlists.
    skill_provider = registry.skill

    async def _refresh_resolved_skills(state):
        # Capability resolution is a security boundary. A resolution failure
        # must block the call rather than reuse another request's ContextVar or
        # fall back to every installed skill.
        await skill_provider.resolve_skills(state)
        return state

    hooks.register("preToolCallHook", _refresh_resolved_skills)

    ctx = PluginContext(
        hooks=hooks,
        providers=registry,
        app=app,
        config=config,
        tool_registry=tool_registry,
        guardrail_registry=guardrail_registry,
        session_cleanup_registry=session_cleanup_registry,
    )

    plugins = discover_plugins()
    for plugin in plugins:
        try:
            with tool_registry.registration_source(f"plugin:{plugin.name}"):
                plugin.register(ctx)
            logger.info("Registered plugin: %s", plugin.name)
        except Exception:
            logger.exception("Failed to register plugin: %s", plugin.name)
    # Run core filesystem removal after plugin handlers have closed kernels and
    # removed records from shared stores.
    from dataclaw.storage.session_cleanup import cleanup_core_session_files
    session_cleanup_registry.register("core", cleanup_core_session_files)

    # Bootstrap plugin config defaults into the config file
    from dataclaw.config.resolver import invalidate_cache
    _bootstrap_plugin_defaults(plugins, cfg_path)
    invalidate_cache()  # Ensure resolver picks up newly written defaults

    # Post-registration runtime selection. External plugins have registered
    # factories by this point, and their config defaults are now visible.
    from dataclaw.providers.agent.factory import (
        RuntimeManager,
        build_direct_bundle,
    )
    from dataclaw.storage.runtime_runs import RuntimeRunStore

    # Runtime plugins may capture this store in their factories. Create it
    # before selection so the adapter, callback routes, and restart recovery
    # all share one instance.
    runtime_run_store = getattr(
        app.state, "runtime_run_store", RuntimeRunStore()
    )
    app.state.runtime_run_store = runtime_run_store
    await runtime_run_store.fail_nonterminal_runs()
    provisional_bundle = build_direct_bundle(registry, hooks, "mock")
    runtime_manager = RuntimeManager(registry, hooks, provisional_bundle)
    registry.runtime_manager = runtime_manager
    await runtime_manager.select(startup=True)

    app.state.providers = registry
    app.state.hooks = runtime_manager.active_bundle.hooks
    app.state.runtime_manager = runtime_manager
    app.state.config = config
    app.state.plugins_list = plugins
    app.state.guardrail_registry = guardrail_registry
    app.state.session_cleanup_registry = session_cleanup_registry

    errors = registry.validate()
    for err in errors:
        logger.error("Provider error: %s", err)

    # Run async plugin initialization (e.g. MCP server connections).
    # on_event("startup") handlers are ignored when a lifespan is used,
    # so we call them here explicitly.
    for handler in app.router.on_startup:
        await handler()
    tool_registry.finalize_registration()

    # Mount SPA static files AFTER all plugin routes are registered,
    # so the catch-all /{path:path} doesn't shadow plugin routes.
    _mount_spa(app)

    try:
        yield
    finally:
        # Run shutdown handlers
        for handler in app.router.on_shutdown:
            await handler()
        await runtime_manager.aclose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Dataclaw API",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Origin/Host checks and token auth (see dataclaw.api.security). Added
    # before CORS so CORS stays outermost and answers preflights itself.
    app.add_middleware(SecurityMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Core routers — all under /api
    from dataclaw.api.routers import auth, chat, config, skills, skill_library, tools, providers, files, terminal
    from dataclaw.api.routers import plugins_router, codex_auth, guardrails, models
    from dataclaw.api.routers.chat import agent_router

    app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
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
    app.include_router(models.router, prefix="/api/models", tags=["models"])

    @app.get("/api/health", tags=["health"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


def _mount_spa(app: FastAPI, ui_dir: Path | None = None) -> None:
    """Mount SPA static files. Called after all routes (including plugin routes) are registered."""
    ui_dir = ui_dir or Path(__file__).parent.parent.parent / "ui" / "dist"
    if not ui_dir.is_dir():
        return

    from fastapi.staticfiles import StaticFiles

    assets_dir = ui_dir / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="static-assets")

    ui_root = ui_dir.resolve()

    @app.get("/{path:path}")
    async def spa_fallback(path: str):
        """Serve the UI. API routes take precedence over this catch-all."""
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404)
        # Resolve before checking containment: an absolute `path` (from a
        # request like `//etc/passwd`) would otherwise replace ui_dir entirely.
        file = (ui_root / path).resolve()
        if file.is_relative_to(ui_root) and file.is_file():
            return FileResponse(file)
        return FileResponse(ui_root / "index.html")
