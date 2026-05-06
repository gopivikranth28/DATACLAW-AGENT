"""Interactive Codex OAuth login manager.

Uses the Codex app-server's built-in ``account/login/start`` RPC to
drive browser-based OAuth and device-code flows. DataClaw does not
reimplement OAuth — it triggers the server's flow and relays auth
URLs / device codes to the caller.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class BrowserLoginResult:
    """Result of starting a browser OAuth flow."""
    auth_url: str
    login_id: str


@dataclass
class DeviceCodeLoginResult:
    """Result of starting a device-code flow."""
    verification_url: str
    user_code: str
    login_id: str


@dataclass
class LoginCompleted:
    """Final login outcome."""
    success: bool
    login_id: str | None = None
    error: str | None = None


class CodexLoginManager:
    """Manages interactive Codex OAuth login via the app-server RPC.

    Usage::

        mgr = CodexLoginManager()
        result = await mgr.start_browser_login()
        # ... open result.auth_url in browser ...
        completed = await mgr.wait_for_login()
        mgr.close()
    """

    def __init__(self, codex_bin: str | None = None) -> None:
        from codex_app_server import AppServerClient, AppServerConfig
        from dataclaw.auth.codex_bridge import prepare_codex_env

        resolved_bin = codex_bin or shutil.which("codex") or "codex"
        config = AppServerConfig(
            codex_bin=resolved_bin,
            env=prepare_codex_env(),
        )
        self._client = AppServerClient(config=config)
        self._started = False

    def _ensure_started(self) -> None:
        if not self._started:
            self._client.start()
            self._client.initialize()
            self._started = True

    async def start_browser_login(self) -> BrowserLoginResult:
        """Start a browser-based OAuth flow.

        Returns the auth URL that the user should open.
        """
        from codex_app_server.generated.v2_all import (
            ChatgptLoginAccountResponse,
            LoginAccountResponse,
        )

        await asyncio.to_thread(self._ensure_started)
        raw: dict[str, Any] = await asyncio.to_thread(
            self._client._request_raw,
            "account/login/start",
            {"type": "chatgpt"},
        )
        resp = LoginAccountResponse.model_validate(raw)
        inner = resp.root
        if not isinstance(inner, ChatgptLoginAccountResponse):
            raise RuntimeError(f"Unexpected login response type: {type(inner).__name__}")
        return BrowserLoginResult(auth_url=inner.auth_url, login_id=inner.login_id)

    async def start_device_code_login(self) -> DeviceCodeLoginResult:
        """Start a device-code OAuth flow.

        Returns the verification URL and user code.
        """
        from codex_app_server.generated.v2_all import (
            ChatgptDeviceCodeLoginAccountResponse,
            LoginAccountResponse,
        )

        await asyncio.to_thread(self._ensure_started)
        raw: dict[str, Any] = await asyncio.to_thread(
            self._client._request_raw,
            "account/login/start",
            {"type": "chatgptDeviceCode"},
        )
        resp = LoginAccountResponse.model_validate(raw)
        inner = resp.root
        if not isinstance(inner, ChatgptDeviceCodeLoginAccountResponse):
            raise RuntimeError(f"Unexpected login response type: {type(inner).__name__}")
        return DeviceCodeLoginResult(
            verification_url=inner.verification_url,
            user_code=inner.user_code,
            login_id=inner.login_id,
        )

    async def start_api_key_login(self, api_key: str) -> None:
        """Submit an API key directly."""
        await asyncio.to_thread(self._ensure_started)
        await asyncio.to_thread(
            self._client._request_raw,
            "account/login/start",
            {"type": "apiKey", "apiKey": api_key},
        )

    async def wait_for_login(self, timeout: float = 300) -> LoginCompleted:
        """Wait for the ``account/login/completed`` notification.

        Args:
            timeout: Maximum seconds to wait (default 5 minutes).

        Returns the login outcome.
        """

        def _wait() -> LoginCompleted:
            from codex_app_server.generated.v2_all import AccountLoginCompletedNotification

            while True:
                notification = self._client.next_notification()
                if notification.method == "account/login/completed":
                    payload = notification.payload
                    if isinstance(payload, AccountLoginCompletedNotification):
                        return LoginCompleted(
                            success=payload.success,
                            login_id=payload.login_id,
                            error=payload.error,
                        )

        try:
            return await asyncio.wait_for(
                asyncio.to_thread(_wait),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            return LoginCompleted(success=False, error="Login timed out")

    def close(self) -> None:
        """Shut down the temporary app-server."""
        if self._started:
            self._client.close()
            self._started = False

    async def aclose(self) -> None:
        """Async close."""
        await asyncio.to_thread(self.close)
