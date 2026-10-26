"""API access control: Origin/Host validation and token authentication.

``SecurityMiddleware`` applies two layers to every HTTP and WebSocket request:

* **Origin/Host validation (always on).** Browsers do not apply CORS to
  WebSocket handshakes or to simple form-style requests, so WebSocket
  handshakes and state-changing requests (anything but GET/HEAD/OPTIONS) are
  rejected when they carry an ``Origin`` that is not one of the app's own
  origins. Requests without ``Origin`` (CLI tools, server-to-server calls)
  pass this check. When the server is bound to loopback, the ``Host`` header
  must also name a loopback host (or a configured one), so a foreign hostname
  that happens to resolve to 127.0.0.1 cannot reach the API.
* **Token authentication.** Required whenever the server binds a non-loopback
  address, or when ``app.auth`` / ``DATACLAW_AUTH`` is ``token``. Loopback
  requests are not exempt: on a ``0.0.0.0`` bind, loopback includes every
  local user and every browser tab. Browsers log in once (``/?token=...`` or
  the UI prompt) and then send an HttpOnly, SameSite=Strict cookie;
  programmatic clients send ``Authorization: Bearer <token>`` or
  ``X-Dataclaw-Token: <token>``. ``/api/health`` stays open for health checks.

The token is ``DATACLAW_TOKEN`` / ``app.token`` when set, otherwise a random
value generated on first start and stored in ``$DATACLAW_HOME/api-token``
(mode 0600). It is also the shared secret for the OpenClaw and Hermes
integrations, which send it on every call back into the API.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
import secrets
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode, urlsplit

from starlette.requests import HTTPConnection
from starlette.responses import JSONResponse, RedirectResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from dataclaw.config import paths
from dataclaw.config.resolver import resolve
from dataclaw.config.secure_io import write_private_text

logger = logging.getLogger(__name__)

TOKEN_HEADER = "X-Dataclaw-Token"
DEFAULT_ALLOWED_ORIGINS = (
    "http://localhost:5173",
    "http://localhost:8000",
    "http://localhost:3000",
)
COOKIE_MAX_AGE_SECONDS = 30 * 24 * 3600
SIGNED_URL_TTL_SECONDS = 12 * 3600

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_PUBLIC_API_PATHS = frozenset({"/api/health"})
# Login endpoints, and vendored static scripts that sandboxed artifact frames
# load (sandboxed frames have an opaque origin, so browsers withhold
# SameSite cookies from their subresource requests).
_PUBLIC_API_PREFIXES = ("/api/auth/", "/api/artifacts/artifact-runtime/")
_DOCS_PATHS = frozenset({"/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"})
_UNSPECIFIED_HOSTS = frozenset({"", "0.0.0.0", "::", "[::]"})


# ── Configuration ───────────────────────────────────────────────────────────


def _as_list(value: Any) -> list[str]:
    if isinstance(value, str):
        items = value.replace(",", " ").split()
    elif isinstance(value, (list, tuple)):
        items = [str(v) for v in value]
    else:
        return []
    return [item.strip() for item in items if item.strip()]


def bind_host() -> str:
    return str(resolve("app.host", "DATACLAW_HOST", "127.0.0.1") or "127.0.0.1").strip()


def bind_port() -> int:
    try:
        return int(resolve("app.port", "DATACLAW_PORT", "8000"))
    except (TypeError, ValueError):
        return 8000


def is_loopback_host(host: str) -> bool:
    name = host.strip().lower().rstrip(".")
    if name.startswith("[") and name.endswith("]"):
        name = name[1:-1]
    if name == "localhost" or name.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(name).is_loopback
    except ValueError:
        return False


def token_required() -> bool:
    """Whether API requests must authenticate.

    ``auto`` (the default) requires a token whenever the bind address is not
    loopback; ``token`` requires it everywhere. There is deliberately no way
    to switch authentication off for a non-loopback bind.
    """
    mode = str(resolve("app.auth", "DATACLAW_AUTH", "auto") or "auto").strip().lower()
    if mode == "token":
        return True
    return not is_loopback_host(bind_host())


def allowed_origins() -> list[str]:
    extra = _as_list(resolve("app.allowed_origins", "DATACLAW_ALLOWED_ORIGINS", ""))
    seen: dict[str, None] = {}
    for origin in (*DEFAULT_ALLOWED_ORIGINS, *extra):
        seen.setdefault(origin.strip().rstrip("/").lower(), None)
    return list(seen)


def _allowed_hostnames() -> set[str]:
    names = {h.lower() for h in _as_list(resolve("app.allowed_hosts", "DATACLAW_ALLOWED_HOSTS", ""))}
    for origin in allowed_origins():
        hostname = urlsplit(origin).hostname
        if hostname:
            names.add(hostname)
    names.add(bind_host().lower().strip("[]"))
    return names


def local_api_url() -> str:
    """Base URL for in-container/in-host calls back into this server."""
    host = bind_host()
    if host in _UNSPECIFIED_HOSTS:
        host = "127.0.0.1"
    elif ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"http://{host}:{bind_port()}"


# ── Token ───────────────────────────────────────────────────────────────────

_file_cache: tuple[str, int, str] | None = None


def _read_token_file() -> str:
    global _file_cache
    path = paths.api_token_path()
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        return ""
    if _file_cache and _file_cache[:2] == (str(path), mtime):
        return _file_cache[2]
    try:
        token = path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    _file_cache = (str(path), mtime, token)
    return token


def api_token() -> str:
    """The active API token, or ``""`` before one has been generated."""
    configured = str(resolve("app.token", "DATACLAW_TOKEN", "") or "").strip()
    return configured or _read_token_file()


def ensure_api_token() -> tuple[str, bool]:
    """Return ``(token, generated)``, generating and persisting one if needed.

    A token is generated even when authentication is not enforced, so local
    integrations (OpenClaw, Hermes) never fall back to a well-known secret.
    """
    token = api_token()
    if token:
        return token, False
    token = secrets.token_urlsafe(32)
    write_private_text(paths.api_token_path(), token + "\n")
    return token, True


def auth_headers() -> dict[str, str]:
    """Headers for server-side calls back into the Dataclaw API."""
    token = api_token()
    return {TOKEN_HEADER: token} if token else {}


def login_url(token: str) -> str:
    host = bind_host()
    if host in _UNSPECIFIED_HOSTS:
        host = "localhost"
    elif ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"http://{host}:{bind_port()}/?token={quote(token, safe='')}"


def log_startup_status() -> None:
    """Make sure a token exists and tell the operator how to log in."""
    path: Path = paths.api_token_path()
    try:
        token, generated = ensure_api_token()
    except OSError:
        logger.exception("Could not create the API token file at %s", path)
        return
    if not token_required():
        return
    if generated:
        logger.warning(
            "API authentication is enabled. Log in with: %s "
            "(the token is stored in %s)", login_url(token), path,
        )
    elif str(resolve("app.token", "DATACLAW_TOKEN", "") or "").strip():
        logger.warning("API authentication is enabled (token from DATACLAW_TOKEN / app.token).")
    else:
        logger.warning("API authentication is enabled (token stored in %s).", path)


# ── Credentials ─────────────────────────────────────────────────────────────


def _derive(token: str, purpose: str) -> bytes:
    return hmac.new(token.encode(), purpose.encode(), hashlib.sha256).digest()


def cookie_name() -> str:
    # Cookies are not port-scoped; the port suffix keeps two local instances
    # from overwriting each other's login.
    return f"dataclaw_auth_{bind_port()}"


def _cookie_value(token: str) -> str:
    # Store a derived value rather than the token itself; rotating the token
    # invalidates every existing cookie.
    return _derive(token, "session-cookie").hex()


def set_auth_cookie(response: Response, token: str, *, secure: bool) -> None:
    response.set_cookie(
        cookie_name(),
        _cookie_value(token),
        max_age=COOKIE_MAX_AGE_SECONDS,
        path="/",
        httponly=True,
        samesite="strict",
        secure=secure,
    )


def clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(cookie_name(), path="/", httponly=True, samesite="strict")


def token_matches(candidate: str | None) -> bool:
    token = api_token()
    return bool(token and candidate) and hmac.compare_digest(
        candidate.strip().encode(), token.encode()
    )


def is_authenticated(conn: HTTPConnection) -> bool:
    token = api_token()
    if not token:
        return False
    authorization = conn.headers.get("authorization", "")
    if authorization[:7].lower() == "bearer " and token_matches(authorization[7:]):
        return True
    if token_matches(conn.headers.get(TOKEN_HEADER)):
        return True
    cookie = conn.cookies.get(cookie_name())
    return bool(cookie) and hmac.compare_digest(cookie.encode(), _cookie_value(token).encode())


def _url_signature(token: str, path: str, params: dict[str, str]) -> str:
    items = sorted((k, v) for k, v in params.items() if k != "dc_sig")
    message = json.dumps([path, items], separators=(",", ":"))
    return hmac.new(_derive(token, "signed-url"), message.encode(), hashlib.sha256).hexdigest()


def sign_url_params(path: str, params: dict[str, str]) -> dict[str, str]:
    """Add a short-lived signature granting GET access to exactly ``path?params``.

    Used for subresource URLs inside sandboxed report frames, whose requests
    carry no SameSite cookies. Without enforced authentication the params are
    returned unchanged.
    """
    token = api_token()
    if not token_required() or not token:
        return params
    signed = {**params, "dc_exp": str(int(time.time()) + SIGNED_URL_TTL_SECONDS)}
    signed["dc_sig"] = _url_signature(token, path, signed)
    return signed


def _valid_signed_url(conn: HTTPConnection) -> bool:
    token = api_token()
    items = conn.query_params.multi_items()
    params = dict(items)
    signature, expiry = params.get("dc_sig"), params.get("dc_exp")
    if not token or not signature or not expiry or len(params) != len(items):
        return False
    try:
        if int(expiry) < time.time():
            return False
    except ValueError:
        return False
    expected = _url_signature(token, conn.url.path, params)
    return hmac.compare_digest(signature.encode(), expected.encode())


# ── Origin / Host ───────────────────────────────────────────────────────────


def origin_allowed(origin: str, host_header: str) -> bool:
    normalized = origin.strip().rstrip("/").lower()
    if normalized in allowed_origins():
        return True
    # The app's own origin (same host:port as the request).
    parsed = urlsplit(normalized)
    return (
        parsed.scheme in {"http", "https"}
        and bool(parsed.netloc)
        and parsed.netloc == host_header.strip().lower()
    )


def host_allowed(host_header: str) -> bool:
    if not is_loopback_host(bind_host()):
        # Non-loopback binds are reachable under any name; the token covers them.
        return True
    if not host_header:
        return True
    hostname = urlsplit(f"//{host_header.strip()}").hostname or ""
    return is_loopback_host(hostname) or hostname in _allowed_hostnames()


def _is_api_path(path: str) -> bool:
    return path == "/api" or path.startswith("/api/")


def _is_public(method: str, path: str, websocket: bool) -> bool:
    if method == "OPTIONS":
        # CORS preflights never carry credentials.
        return True
    if path in _PUBLIC_API_PATHS or path.startswith(_PUBLIC_API_PREFIXES):
        return not websocket
    if websocket or _is_api_path(path) or path in _DOCS_PATHS:
        return False
    # The SPA shell and its static assets: the UI must load to show the login prompt.
    return method in {"GET", "HEAD"}


# ── Middleware ──────────────────────────────────────────────────────────────


class SecurityMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return

        conn = HTTPConnection(scope)
        websocket = scope["type"] == "websocket"
        method = "GET" if websocket else scope["method"].upper()
        path = scope["path"]
        host_header = conn.headers.get("host", "")

        if not host_allowed(host_header):
            await _reject(scope, receive, send, 400, "Invalid Host header")
            return

        origin = conn.headers.get("origin")
        if (
            (websocket or method not in _SAFE_METHODS)
            and origin is not None
            and not origin_allowed(origin, host_header)
        ):
            await _reject(scope, receive, send, 403, "Origin not allowed")
            return

        if not websocket and method == "GET" and not _is_api_path(path) and "token" in conn.query_params:
            if token_matches(conn.query_params["token"]):
                await _login_redirect(conn, scope, receive, send)
                return

        if token_required() and not _is_public(method, path, websocket):
            signed = not websocket and method in {"GET", "HEAD"} and "dc_sig" in conn.query_params
            if not (is_authenticated(conn) or (signed and _valid_signed_url(conn))):
                await _reject(scope, receive, send, 401, "Authentication required")
                return

        await self.app(scope, receive, send)


async def _login_redirect(conn: HTTPConnection, scope: Scope, receive: Receive, send: Send) -> None:
    """Exchange ``?token=`` on a UI URL for a cookie, then drop it from the URL."""
    path = conn.url.path
    if not path.startswith("/") or path.startswith("//"):
        path = "/"
    remaining = [(k, v) for k, v in conn.query_params.multi_items() if k != "token"]
    location = quote(path) + (f"?{urlencode(remaining)}" if remaining else "")
    response = RedirectResponse(location, status_code=303)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    set_auth_cookie(response, api_token(), secure=scope.get("scheme") == "https")
    await response(scope, receive, send)


async def _reject(scope: Scope, receive: Receive, send: Send, status: int, detail: str) -> None:
    if scope["type"] == "websocket":
        # Closing before accept makes the server answer the handshake with 403.
        await send({"type": "websocket.close", "code": 1008, "reason": detail})
        return
    headers = {"WWW-Authenticate": "Bearer"} if status == 401 else None
    await JSONResponse({"detail": detail}, status_code=status, headers=headers)(scope, receive, send)
