"""Subprocess wrapper around the `gbrain call <tool> <json>` interface.

`gbrain call` returns the same structured JSON as the MCP server, which makes
it the cleanest programmatic interface — no scraping prose CLI output.

Brain location is selected per-call via the GBRAIN_HOME env var. gbrain
appends `.gbrain` to GBRAIN_HOME, so passing `~/.dataclaw/memory` as the
home yields a brain at `~/.dataclaw/memory/.gbrain/`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default `BUN_INSTALL` path — many users have `gbrain` installed via bun, in which
# case the binary lives at `~/.bun/bin/gbrain`. The DataClaw process may not have
# `~/.bun/bin` on PATH, so we add it to the subprocess env.
_BUN_BIN = str(Path.home() / ".bun" / "bin")


class GbrainCallError(RuntimeError):
    """Raised when `gbrain call` exits non-zero."""


class GbrainClient:
    """Thin wrapper around `gbrain call <tool> <json>`."""

    def __init__(
        self,
        *,
        brain_home: Path,
        gbrain_bin: str = "gbrain",
        timeout_seconds: float = 30.0,
    ) -> None:
        self._brain_home = brain_home
        self._gbrain_bin = gbrain_bin
        self._timeout = timeout_seconds

    # ── Public tool wrappers ───────────────────────────────────────────

    async def put_page(self, slug: str, content: str) -> dict[str, Any]:
        """Write or update a page. Returns gbrain's put_page response."""
        return await self._call("put_page", {"slug": slug, "content": content})

    async def query(
        self,
        query: str,
        *,
        limit: int = 5,
        detail: str = "medium",
        expand: bool = True,
    ) -> list[dict[str, Any]]:
        """Hybrid (vector + keyword) search. Returns the list of hits."""
        result = await self._call(
            "query",
            {"query": query, "limit": limit, "detail": detail, "expand": expand},
        )
        # gbrain's query returns a list directly; some versions wrap it.
        if isinstance(result, list):
            return result
        if isinstance(result, dict) and "results" in result:
            return result["results"]
        return []

    async def get_page(self, slug: str) -> dict[str, Any] | None:
        """Read a page by slug. Returns None if missing."""
        try:
            return await self._call("get_page", {"slug": slug})
        except GbrainCallError:
            return None

    # ── Internals ──────────────────────────────────────────────────────

    async def _call(self, tool: str, params: dict[str, Any]) -> Any:
        """Invoke `gbrain call <tool> <json>` and parse stdout as JSON."""
        argv = [self._gbrain_bin, "call", tool, json.dumps(params)]
        env = self._build_env()

        def _run() -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                argv,
                env=env,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                check=False,
            )

        try:
            result = await asyncio.to_thread(_run)
        except FileNotFoundError as exc:
            raise GbrainCallError(
                f"gbrain binary not found at {self._gbrain_bin!r}. "
                "Install it with `bun install -g gbrain` or set memory.gbrain.gbrain_bin."
            ) from exc

        if result.returncode != 0:
            raise GbrainCallError(
                f"gbrain call {tool} failed (exit {result.returncode}): "
                f"{result.stderr.strip() or result.stdout.strip()}"
            )

        stdout = result.stdout.strip()
        if not stdout:
            return None
        try:
            return json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise GbrainCallError(
                f"gbrain call {tool} returned non-JSON output: {stdout[:200]}"
            ) from exc

    def _build_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["GBRAIN_HOME"] = str(self._brain_home)
        path = env.get("PATH", "")
        if _BUN_BIN not in path.split(os.pathsep):
            env["PATH"] = f"{_BUN_BIN}{os.pathsep}{path}" if path else _BUN_BIN
        return env
