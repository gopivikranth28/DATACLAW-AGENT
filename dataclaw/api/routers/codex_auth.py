"""Codex authentication routes — interactive OAuth login and API key setup."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

router = APIRouter()

# Single login manager per server lifetime; replaced on each new login attempt.
_active_manager: object | None = None  # CodexLoginManager, lazily imported


def _get_codex_bin(request: Request) -> str | None:
    """Read codex_bin from the app's runtime config if available."""
    registry = getattr(request.app.state, "registry", None)
    if registry and hasattr(registry, "config"):
        codex_cfg = getattr(registry.config, "llm", None)
        if codex_cfg:
            return getattr(getattr(codex_cfg, "codex", None), "codex_bin", None) or None
    return None


@router.post("/login/start")
async def login_start(request: Request) -> dict[str, Any]:
    """Start an interactive Codex login flow.

    Body (optional):
        {"method": "browser" | "device_code"}  — defaults to "browser"

    Returns auth URL or device code depending on method.
    """
    global _active_manager

    body = await request.json() if await request.body() else {}
    method = body.get("method", "browser")

    # Tear down any previous login session
    if _active_manager is not None:
        await _active_manager.aclose()
        _active_manager = None

    from dataclaw.auth.codex_login import CodexLoginManager

    codex_bin = _get_codex_bin(request)
    mgr = CodexLoginManager(codex_bin=codex_bin)
    _active_manager = mgr

    try:
        if method == "device_code":
            result = await mgr.start_device_code_login()
            return {
                "method": "device_code",
                "verification_url": result.verification_url,
                "user_code": result.user_code,
                "login_id": result.login_id,
            }
        else:
            result = await mgr.start_browser_login()
            return {
                "method": "browser",
                "auth_url": result.auth_url,
                "login_id": result.login_id,
            }
    except Exception:
        await mgr.aclose()
        _active_manager = None
        raise


@router.get("/login/status")
async def login_status(request: Request) -> StreamingResponse:
    """SSE endpoint that streams login status until completed or timeout."""

    async def _stream():
        global _active_manager
        mgr = _active_manager
        if mgr is None:
            yield f"data: {json.dumps({'error': 'No active login session'})}\n\n"
            return

        yield f"data: {json.dumps({'status': 'waiting'})}\n\n"

        completed = await mgr.wait_for_login(timeout=300)
        payload = {
            "status": "completed" if completed.success else "failed",
            "success": completed.success,
        }
        if completed.error:
            payload["error"] = completed.error
        if completed.login_id:
            payload["login_id"] = completed.login_id

        # Re-run agent hot-reload so codex LLM picks up the new tokens
        # without needing a manual save afterwards. See docstring on
        # ``_hot_reload_agent_after_login`` for context.
        if completed.success:
            await _hot_reload_agent_after_login(request)

        yield f"data: {json.dumps(payload)}\n\n"

        # Clean up
        await mgr.aclose()
        _active_manager = None

    return StreamingResponse(_stream(), media_type="text/event-stream")


@router.post("/login/finish-redirect")
async def login_finish_redirect(request: Request) -> dict[str, Any]:
    """Manual redirect-URL replay for the browser login flow.

    The browser flow tells Codex to listen on a loopback callback URL (e.g.
    ``http://localhost:1455/...``); after the user signs in, OpenAI bounces
    the browser to that URL with the auth code as a query param. When
    DataClaw runs in Docker, the browser's loopback isn't the container's
    loopback, so the redirect fails and the flow stalls.

    This endpoint replays the redirect URL server-side: the GET originates
    from inside the container, where Codex's listener is reachable. Codex
    completes the OAuth handshake and emits the
    ``account/login/completed`` notification the existing SSE picks up.

    Body: ``{"url": "http://localhost:1455/auth/callback?code=...&state=..."}``

    SSRF guard: only loopback hosts (``localhost`` / ``127.0.0.1`` /
    ``::1``) are accepted, since that's the only legitimate target.
    """
    from urllib.parse import urlparse

    import httpx

    body = await request.json()
    url = (body.get("url") or "").strip()
    if not url:
        return {"success": False, "error": "url is required"}

    try:
        parsed = urlparse(url)
    except ValueError as exc:
        return {"success": False, "error": f"invalid url: {exc}"}

    if parsed.scheme not in ("http", "https"):
        return {"success": False, "error": "url must be http or https"}

    host = (parsed.hostname or "").lower()
    if host not in ("localhost", "127.0.0.1", "::1"):
        return {
            "success": False,
            "error": (
                "url must point at a loopback address (localhost / 127.0.0.1) — "
                "that's the only place Codex's auth listener runs."
            ),
        }

    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=10.0) as client:
            r = await client.get(url)
    except httpx.ConnectError as exc:
        return {
            "success": False,
            "error": (
                f"connection refused calling {url}: {exc}. The codex listener "
                "may have already shut down — try Login with Browser again."
            ),
        }
    except Exception as exc:
        return {"success": False, "error": f"replay failed: {exc}"}

    # Codex's app-server doesn't reliably emit ``account/login/completed``
    # when the OAuth callback arrives via this server-side replay (vs. a
    # direct browser hit), but it DOES write ``auth.json`` with the new
    # tokens once the loopback handler succeeds. Poll auth.json briefly so
    # the UI gets immediate confirmation instead of waiting on an SSE event
    # that may never come.
    from dataclaw.auth.codex_bridge import CODEX_HOME

    auth_path = CODEX_HOME / "auth.json"
    completed = False
    for _ in range(50):  # ~5s, 100ms ticks
        if auth_path.exists():
            try:
                data = json.loads(auth_path.read_text())
                if data.get("tokens", {}).get("access_token"):
                    completed = True
                    break
            except (json.JSONDecodeError, OSError):
                pass
        await asyncio.sleep(0.1)

    # Auth wrote tokens — re-run the agent hot-reload so the codex LLM picks
    # them up immediately. Without this, a user who switches the dropdown to
    # Codex *before* logging in has to save twice (the first PATCH's
    # hot-reload silently fails when auth.json doesn't exist yet, leaves
    # providers.agent on OpenClaw, and chats come back "OpenClaw not
    # running"). Triggering the reload here makes the login complete the
    # configuration in a single user-visible step.
    if completed:
        await _hot_reload_agent_after_login(request)

    return {"success": True, "status_code": r.status_code, "completed": completed}


async def _hot_reload_agent_after_login(request: Request) -> None:
    """Re-run the agent provider hot-reload after a successful Codex login.

    Safe to call on every login completion — when ``llm.backend`` isn't
    codex the reload is effectively a no-op (the existing provider for the
    selected backend is rebuilt with the same config).
    """
    try:
        from dataclaw.api.routers.config import _hot_reload_agent

        await asyncio.to_thread(_hot_reload_agent, request)
    except Exception:  # never block login completion on a hot-reload failure
        logger.exception("Failed to hot-reload agent after Codex login")


@router.post("/login/api-key")
async def login_api_key(request: Request) -> dict[str, Any]:
    """Store an API key for Codex authentication.

    Body: {"api_key": "sk-..."}
    """
    body = await request.json()
    api_key = body.get("api_key", "")
    if not api_key:
        return {"success": False, "error": "api_key is required"}

    # Write to config
    from dataclaw.config.paths import config_path
    from dataclaw.config.resolver import invalidate_cache

    import json as _json

    cfg_path = config_path()
    raw = _json.loads(cfg_path.read_text()) if cfg_path.exists() else {}
    raw.setdefault("llm", {}).setdefault("codex", {})["api_key"] = api_key
    raw["llm"]["codex"]["auth_mode"] = "api_key"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(_json.dumps(raw, indent=2) + "\n")
    invalidate_cache()

    return {"success": True}
