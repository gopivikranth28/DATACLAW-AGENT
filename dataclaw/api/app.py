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
            logger.warning("Failed to parse config file, using defaults")
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

    config = _load_config()
    registry = ProviderRegistry()
    hooks = HookRegistry()
    tool_registry = init_providers(registry)

    ctx = PluginContext(
        hooks=hooks,
        providers=registry,
        app=app,
        config=config,
        tool_registry=tool_registry,
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

    errors = registry.validate()
    for err in errors:
        logger.error("Provider error: %s", err)

    # Mount SPA static files AFTER all plugin routes are registered,
    # so the catch-all /{path:path} doesn't shadow plugin routes.
    _mount_spa(app)

    yield


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
    from dataclaw.api.routers import chat, config, skills, tools, providers, files, terminal
    from dataclaw.api.routers import plugins_router
    from dataclaw.api.routers.chat import agent_router

    app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
    app.include_router(config.router, prefix="/api/config", tags=["config"])
    app.include_router(skills.router, prefix="/api/skills", tags=["skills"])
    app.include_router(tools.router, prefix="/api/tools", tags=["tools"])
    app.include_router(providers.router, prefix="/api/providers", tags=["providers"])
    app.include_router(plugins_router.router, prefix="/api/plugins", tags=["plugins"])
    app.include_router(agent_router, prefix="/api", tags=["agent"])
    app.include_router(files.router, prefix="/api/workspace", tags=["workspace-files"])
    app.include_router(terminal.router, prefix="/api/terminal", tags=["terminal"])

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
