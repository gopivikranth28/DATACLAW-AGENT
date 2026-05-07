"""GbrainMemoryProvider — implements MemoryProvider protocol on top of gbrain."""

from __future__ import annotations

import logging
import os
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dataclaw.providers.config_field import ConfigField
from dataclaw.state import AgentState

from dataclaw_gbrain.client import GbrainClient, GbrainCallError

logger = logging.getLogger(__name__)

_MAX_MEMORY_CHARS = 300
_BUN_BIN = str(Path.home() / ".bun" / "bin")


class GbrainMemoryProvider:
    """Memory provider that reads from and (optionally) writes to a gbrain brain."""

    @classmethod
    def config_schema(cls) -> list[ConfigField]:
        return [
            ConfigField(
                name="location",
                field_type="select",
                label="Brain location",
                description=(
                    "`new` auto-initializes a DataClaw-managed brain at the brain "
                    "home below. `existing` points at a brain you already have."
                ),
                default="new",
                options=[
                    {"label": "New (DataClaw-managed)", "value": "new"},
                    {"label": "Existing", "value": "existing"},
                ],
            ),
            ConfigField(
                name="brain_home",
                field_type="string",
                label="Brain home",
                description=(
                    "Parent dir for the gbrain database. gbrain creates "
                    "`.gbrain/` inside this path. Set to `~` to reuse "
                    "the default `~/.gbrain` brain."
                ),
                default="~/.dataclaw/memory",
            ),
            ConfigField(
                name="mode",
                field_type="select",
                label="Mode",
                description=(
                    "`read_write` lets the agent save memories. "
                    "`read_only` hides save_memory and treats writes as no-ops."
                ),
                default="read_write",
                options=[
                    {"label": "Read / Write", "value": "read_write"},
                    {"label": "Read only", "value": "read_only"},
                ],
            ),
            ConfigField(
                name="top_k",
                field_type="int",
                label="Top K",
                description="Number of memories to retrieve per turn.",
                default=5,
            ),
            ConfigField(
                name="gbrain_bin",
                field_type="string",
                label="gbrain binary",
                description="Path to the gbrain executable (advanced).",
                default="gbrain",
            ),
        ]

    def __init__(
        self,
        *,
        brain_home: Path,
        mode: str = "read_write",
        top_k: int = 5,
        location: str = "new",
        gbrain_bin: str = "gbrain",
        client: GbrainClient | None = None,
    ) -> None:
        if mode not in {"read_write", "read_only"}:
            raise ValueError(f"Unknown gbrain mode: {mode!r}")
        if location not in {"new", "existing"}:
            raise ValueError(f"Unknown gbrain location: {location!r}")
        self._brain_home = brain_home
        self._mode = mode
        self._top_k = top_k
        self._location = location
        self._gbrain_bin = gbrain_bin
        if location == "new":
            _ensure_brain_initialized(brain_home, gbrain_bin)
        self._client = client or GbrainClient(brain_home=brain_home, gbrain_bin=gbrain_bin)

    # ── Protocol: Read ─────────────────────────────────────────────────

    async def retrieve_memories(self, state: AgentState) -> list[str]:
        query = (state.get("user_query") or "").strip()
        if not query:
            return []
        try:
            hits = await self._client.query(query, limit=self._top_k, detail="medium")
        except GbrainCallError:
            logger.warning("gbrain query failed; returning no memories", exc_info=True)
            return []

        out: list[str] = []
        for hit in hits:
            slug = hit.get("slug") or "?"
            text = (hit.get("chunk_text") or "").strip()
            if not text:
                continue
            out.append(f"[gbrain:{slug}] {text[:_MAX_MEMORY_CHARS]}")
        return out

    async def search_memory(
        self,
        query: str,
        *,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        try:
            hits = await self._client.query(query, limit=limit, detail="medium")
        except GbrainCallError as exc:
            logger.warning("gbrain search_memory failed: %s", exc)
            return []

        return [
            {
                "id": hit.get("slug", ""),
                "score": round(float(hit.get("score") or 0.0), 4),
                "content": hit.get("chunk_text", ""),
                "metadata": {
                    "title": hit.get("title"),
                    "type": hit.get("type"),
                    "page_id": hit.get("page_id"),
                    "source_id": hit.get("source_id"),
                },
            }
            for hit in hits
        ]

    def as_tool_definition(self) -> dict[str, Any] | None:
        return {
            "name": "search_memory",
            "description": (
                "Search saved memories in the gbrain knowledge base using hybrid "
                "vector + keyword search. Returns the most relevant memories matching the query."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results to return.",
                        "default": 10,
                    },
                },
                "required": ["query"],
            },
        }

    # ── Protocol: Write ────────────────────────────────────────────────

    async def save_memory(
        self,
        content: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self._mode == "read_only":
            return {"status": "noop", "reason": "read_only"}

        slug = self._make_slug()
        page = self._render_page(content, metadata or {})
        try:
            await self._client.put_page(slug, page)
        except GbrainCallError as exc:
            logger.warning("gbrain put_page failed: %s", exc)
            return {"id": slug, "status": "error", "error": str(exc)}
        logger.info("Saved gbrain memory %s", slug)
        return {"id": slug, "status": "saved"}

    def as_save_tool_definition(self) -> dict[str, Any] | None:
        if self._mode == "read_only":
            return None
        return {
            "name": "save_memory",
            "description": (
                "Save a piece of information to the gbrain memory store for future "
                "reference. Use this to remember important facts, user preferences, "
                "or context that should persist across conversations."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "The memory content to save (markdown supported).",
                    },
                    "metadata": {
                        "type": "object",
                        "description": "Optional metadata. Stored as additional frontmatter keys.",
                    },
                },
                "required": ["content"],
            },
        }

    # ── Helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _make_slug() -> str:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return f"dataclaw-memory/{date}/{uuid.uuid4().hex[:12]}"

    @staticmethod
    def _render_page(content: str, metadata: dict[str, Any]) -> str:
        frontmatter_lines = [
            "---",
            "type: note",
            "tags: [dataclaw-memory]",
        ]
        for key, value in sorted(metadata.items()):
            if value is None or key in {"type", "tags"}:
                continue
            frontmatter_lines.append(f"{key}: {_yaml_scalar(value)}")
        frontmatter_lines.append("---")
        frontmatter_lines.append("")
        return "\n".join(frontmatter_lines) + content.strip() + "\n"


def _yaml_scalar(value: Any) -> str:
    """Render a simple value as a YAML scalar. Falls back to JSON for non-trivial types."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        # Quote anything that looks risky to YAML
        if any(ch in value for ch in ":#\n\"'") or value != value.strip():
            return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
        return value
    import json
    return json.dumps(value)


def _ensure_brain_initialized(brain_home: Path, gbrain_bin: str) -> None:
    """Run `gbrain init --pglite` in `brain_home` if no `.gbrain` dir exists yet."""
    brain_dir = brain_home / ".gbrain"
    if brain_dir.exists():
        return
    brain_home.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["GBRAIN_HOME"] = str(brain_home)
    path = env.get("PATH", "")
    if _BUN_BIN not in path.split(os.pathsep):
        env["PATH"] = f"{_BUN_BIN}{os.pathsep}{path}" if path else _BUN_BIN

    logger.info("Initializing gbrain brain at %s", brain_home)
    try:
        result = subprocess.run(
            [gbrain_bin, "init", "--pglite"],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"gbrain binary not found at {gbrain_bin!r}. "
            "Install gbrain (`bun install -g gbrain`) or set memory.gbrain.gbrain_bin."
        ) from exc

    if result.returncode != 0:
        raise RuntimeError(
            f"gbrain init failed (exit {result.returncode}): "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
