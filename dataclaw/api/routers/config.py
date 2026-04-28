"""Config router — read/update configuration with hot-reload of agent backend."""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Request

from dataclaw.config.paths import config_path
from dataclaw.config.resolver import invalidate_cache, resolve
from dataclaw.config.schema import DataclawConfig

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("")
async def get_config(request: Request) -> dict[str, Any]:
    """Get the current configuration (secrets masked)."""
    path = config_path()
    if path.exists():
        raw = json.loads(path.read_text())
    else:
        raw = DataclawConfig().model_dump()

    # Mask API keys
    for section in ("anthropic", "openai", "gemini"):
        llm = raw.get("llm", {})
        if section in llm and "api_key" in llm[section]:
            key = llm[section]["api_key"]
            if key:
                llm[section]["api_key"] = key[:8] + "..." + key[-4:] if len(key) > 12 else "***"

    # Include current active agent backend
    raw["_active_agent"] = _detect_active_agent(request)

    return raw


@router.patch("")
async def update_config(updates: dict[str, Any], request: Request) -> dict[str, Any]:
    """Merge updates into the config file and hot-reload agent if backend changed."""
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        raw = json.loads(path.read_text())
    else:
        raw = {}

    _strip_masked_secrets(updates)
    _deep_merge(raw, updates)
    path.write_text(json.dumps(raw, indent=2))
    invalidate_cache()

    # Hot-reload agent provider if backend changed
    _hot_reload_agent(request)

    return {"status": "updated"}


def _hot_reload_agent(request: Request) -> None:
    """Rebuild the agent (and LLM) provider from current config."""
    try:
        providers = request.app.state.providers
        invalidate_cache()

        backend = resolve("llm.backend", "DATACLAW_LLM_BACKEND", "openclaw")
        openclaw_url = resolve("plugins.openclaw.url", "DATACLAW_OPENCLAW_URL", "")

        # llm.backend=openclaw is the canonical signal
        if backend == "openclaw" and not openclaw_url:
            openclaw_url = "http://127.0.0.1:18789"

        if openclaw_url:
            # OpenClaw mode
            try:
                from dataclaw_openclaw.agent_provider import OpenClawAgentProvider
                token = resolve("plugins.openclaw.frontend_token", "DATACLAW_FRONTEND_TOKEN",
                        resolve("plugins.openclaw.token", "DATACLAW_OPENCLAW_TOKEN", ""))
                wait_ms = int(resolve("plugins.openclaw.wait_ms", "DATACLAW_OPENCLAW_WAIT_MS", "300000"))
                providers.agent = OpenClawAgentProvider(url=openclaw_url, token=token, wait_ms=wait_ms)
                logger.info("Hot-reloaded agent: OpenClaw (%s)", openclaw_url)
            except ImportError:
                logger.warning("dataclaw-openclaw plugin not installed, falling back to LLM")
                _reload_llm_agent(providers, backend)
        else:
            # Local LLM mode
            _reload_llm_agent(providers, backend)

    except Exception:
        logger.exception("Failed to hot-reload agent provider")


def _reload_llm_agent(providers: Any, backend: str) -> None:
    """Reload the LLM-based agent provider."""
    from dataclaw.providers.llm.implementations.factory import llm_from_config
    from dataclaw.providers.agent.implementations.langchain_agent import LangChainAgentProvider
    from dataclaw.providers.compaction.implementations.llm_summarizer import LLMSummarizingCompactor

    llm = llm_from_config(backend=backend)
    providers.llm = llm
    providers.agent = LangChainAgentProvider(llm)
    providers.compaction = LLMSummarizingCompactor(llm)
    logger.info("Hot-reloaded agent: %s LLM", backend)


def _detect_active_agent(request: Request) -> str:
    """Return the name of the currently active agent provider."""
    try:
        backend = resolve("llm.backend", "DATACLAW_LLM_BACKEND", "openclaw")
        if backend == "openclaw":
            return "openclaw"
        agent = request.app.state.providers.agent
        name = type(agent).__name__
        if "OpenClaw" in name:
            return "openclaw"
        return backend
    except Exception:
        return "unknown"


def _strip_masked_secrets(updates: dict) -> None:
    """Remove masked API key values so they don't overwrite real keys."""
    llm = updates.get("llm")
    if isinstance(llm, dict):
        for section in ("anthropic", "openai", "gemini"):
            sub = llm.get(section)
            if isinstance(sub, dict) and "api_key" in sub:
                val = sub["api_key"]
                if isinstance(val, str) and ("..." in val or val == "***"):
                    del sub["api_key"]
    # Also check plugin tokens
    plugins = updates.get("plugins")
    if isinstance(plugins, dict):
        for plugin_cfg in plugins.values():
            if isinstance(plugin_cfg, dict):
                for key in list(plugin_cfg.keys()):
                    if "token" in key:
                        val = plugin_cfg[key]
                        if isinstance(val, str) and ("..." in val or val == "***"):
                            del plugin_cfg[key]


def _deep_merge(base: dict, updates: dict) -> None:
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
