"""Workspace tools — file I/O and shell execution.

All tools take a WorkspaceConfig and operate relative to the workspace
base directory (~/.dataclaw/workspaces/ by default). Path traversal
outside the base directory is prevented.
"""

from __future__ import annotations

import asyncio
import difflib
from pathlib import Path
from typing import Any

from dataclaw.config.paths import workspaces_dir

from dataclaw_workspace.config import WorkspaceConfig

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}

# Project directory override — set per-request via hook when a project is active.
_project_dir: Path | None = None


def set_project_dir(d: Path | None) -> None:
    global _project_dir
    _project_dir = d


# ── Path helpers ────────────────────────────────────────────────────────────


def _safe_id(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in value.strip())
    return safe or "default"


def _base_dir(workspace_id: str = "default") -> Path:
    if _project_dir is not None:
        _project_dir.mkdir(parents=True, exist_ok=True)
        return _project_dir
    base = workspaces_dir() / _safe_id(workspace_id)
    base.mkdir(parents=True, exist_ok=True)
    return base


def _resolve_path(workspace_id: str, path: str) -> Path:
    """Resolve a path within the workspace, preventing traversal."""
    base = _base_dir(workspace_id).resolve()
    raw = Path(path).expanduser()
    resolved = raw.resolve() if raw.is_absolute() else (base / raw).resolve()
    try:
        resolved.relative_to(base)
    except ValueError as exc:
        raise ValueError(f"Path must be inside workspace directory: {base}") from exc
    return resolved


# ── Tools ───────────────────────────────────────────────────────────────────


async def ws_list_files(
    *,
    cfg: WorkspaceConfig,
    path: str = ".",
    pattern: str = "*",
    recursive: bool = False,
    workspace_id: str = "default",
) -> dict[str, Any]:
    """List files and directories in the workspace."""
    base = _base_dir(workspace_id).resolve()
    target = _resolve_path(workspace_id, path)
    if not target.is_dir():
        raise ValueError(f"Not a directory: {path}")

    entries: list[dict[str, Any]] = []
    truncated = False
    iterator = target.rglob(pattern) if recursive else target.glob(pattern)

    for item in iterator:
        if len(entries) >= cfg.max_list_entries:
            truncated = True
            break
        try:
            rel = str(item.relative_to(base))
            st = item.stat()
            entries.append({
                "name": rel,
                "type": "dir" if item.is_dir() else "file",
                "size": st.st_size,
            })
        except (OSError, ValueError):
            continue

    return {
        "path": path,
        "entries": entries,
        "truncated": truncated,
    }


async def ws_read_file(
    *,
    cfg: WorkspaceConfig,
    path: str,
    offset: int = 0,
    limit: int | None = None,
    workspace_id: str = "default",
) -> dict[str, Any]:
    """Read the contents of a file in the workspace."""
    resolved = _resolve_path(workspace_id, path)
    if not resolved.is_file():
        raise ValueError(f"File not found: {path}")

    size = resolved.stat().st_size
    if offset == 0 and limit is None and size > cfg.max_read_bytes:
        raise ValueError(
            f"File too large ({size} bytes, max {cfg.max_read_bytes}). "
            "Use offset/limit to read a portion."
        )

    text = resolved.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines(keepends=True)
    total_lines = len(lines)

    if offset or limit is not None:
        end = (offset + limit) if limit is not None else None
        lines = lines[offset:end]

    content = "".join(lines)
    return {
        "path": path,
        "content": content,
        "total_lines": total_lines,
        "lines_returned": len(lines),
        "size": size,
    }


async def ws_write_file(
    *,
    cfg: WorkspaceConfig,
    path: str,
    content: str,
    workspace_id: str = "default",
) -> dict[str, Any]:
    """Write or create a file in the workspace."""
    encoded = content.encode("utf-8")
    if len(encoded) > cfg.max_write_bytes:
        raise ValueError(
            f"Content too large ({len(encoded)} bytes, max {cfg.max_write_bytes})"
        )

    resolved = _resolve_path(workspace_id, path)
    created = not resolved.exists()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_bytes(encoded)

    return {
        "path": path,
        "size": len(encoded),
        "created": created,
    }


async def ws_update_file(
    *,
    cfg: WorkspaceConfig,
    path: str,
    old_string: str,
    new_string: str,
    replace_all: bool = False,
    workspace_id: str = "default",
) -> dict[str, Any]:
    """Find and replace text within a workspace file."""
    resolved = _resolve_path(workspace_id, path)
    if not resolved.is_file():
        raise ValueError(f"File not found: {path}")

    original = resolved.read_text(encoding="utf-8", errors="replace")
    if old_string not in original:
        raise ValueError(f"old_string not found in {path}")

    if replace_all:
        updated = original.replace(old_string, new_string)
        count = original.count(old_string)
    else:
        updated = original.replace(old_string, new_string, 1)
        count = 1

    resolved.write_text(updated, encoding="utf-8")
    diff = "".join(difflib.unified_diff(
        original.splitlines(keepends=True),
        updated.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
    ))
    return {
        "path": path,
        "replacements": count,
        "diff": diff,
    }


async def ws_exec(
    *,
    cfg: WorkspaceConfig,
    command: str,
    timeout: int | None = None,
    workspace_id: str = "default",
) -> dict[str, Any]:
    """Run a shell command in the workspace directory."""
    effective_timeout = min(
        max(timeout or cfg.exec_timeout_default, 1),
        cfg.exec_timeout_max,
    )
    cwd = _base_dir(workspace_id)
    timed_out = False

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=effective_timeout,
        )
    except asyncio.TimeoutError:
        timed_out = True
        proc.kill()  # type: ignore[possibly-undefined]
        stdout_bytes, stderr_bytes = await proc.communicate()  # type: ignore[possibly-undefined]

    max_out = cfg.max_exec_output_bytes
    stdout = stdout_bytes[:max_out].decode("utf-8", errors="replace")
    stderr = stderr_bytes[:max_out].decode("utf-8", errors="replace")

    return {
        "command": command,
        "exit_code": proc.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "timed_out": timed_out,
    }


async def display_image(
    *,
    cfg: WorkspaceConfig,
    path: str,
    caption: str = "",
    title: str = "",
    workspace_id: str = "default",
) -> dict[str, Any]:
    """Display an image file to the user in the chat."""
    base = _base_dir(workspace_id)
    raw = Path(path).expanduser()
    file_path = raw.resolve() if raw.is_absolute() else (base / raw).resolve()

    if not file_path.exists() or not file_path.is_file():
        raise ValueError(f"Image file not found: {path}")
    if file_path.suffix.lower() not in _IMAGE_EXTENSIONS:
        raise ValueError(
            f"Unsupported image format: {file_path.suffix}. "
            f"Supported: {', '.join(sorted(_IMAGE_EXTENSIONS))}"
        )

    return {
        "path": str(file_path),
        "title": title or file_path.name,
        "caption": caption,
        "displayed": True,
    }
