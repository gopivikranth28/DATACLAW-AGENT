"""OpenClaw skill sync — copy/remove skills to/from the OpenClaw extensions directory."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from dataclaw.storage.skills import read_skill

router = APIRouter()


def _get_extensions_dir(request: Request) -> Path:
    """Resolve the OpenClaw extensions directory from plugin config.

    Handles both conventions for openclaw_dir:
      - openclaw_dir = /Users/user          → /Users/user/.openclaw/extensions/
      - openclaw_dir = /Users/user/.openclaw → /Users/user/.openclaw/extensions/
    """
    # Read from config file directly (not app.state.config which is stale after saves)
    from dataclaw.config.resolver import resolve
    openclaw_cfg = {
        "openclaw_dir": resolve("plugins.openclaw.openclaw_dir", "DATACLAW_OPENCLAW_DIR", ""),
    }
    openclaw_dir = openclaw_cfg.get("openclaw_dir", "")
    if not openclaw_dir:
        raise HTTPException(status_code=400, detail="openclaw_dir is not configured. Set it in Config → OpenClaw.")
    base = Path(openclaw_dir).expanduser()
    if not base.exists():
        raise HTTPException(status_code=400, detail=f"openclaw_dir does not exist: {base}")
    # If base already IS the .openclaw directory, use it directly
    if base.name == ".openclaw":
        return base / "extensions"
    return base / ".openclaw" / "extensions"


@router.post("/skills/{skill_id}/sync")
async def sync_skill(skill_id: str, request: Request):
    """Copy a skill to the OpenClaw extensions directory."""
    skill = read_skill(skill_id)
    if skill is None:
        raise HTTPException(status_code=404, detail="Skill not found")

    ext_dir = _get_extensions_dir(request)
    target_dir = ext_dir / "dataclaw-tools" / "skills" / skill_id
    target_dir.mkdir(parents=True, exist_ok=True)

    target_path = target_dir / "SKILL.md"
    frontmatter = f"---\nname: {skill.get('name', skill_id)}\ndescription: {skill.get('description', '')}\n---\n"
    target_path.write_text(frontmatter + "\n" + skill.get("body", ""))

    return {"synced_to": str(target_path)}


@router.delete("/skills/{skill_id}/sync", status_code=204)
async def remove_skill_sync(skill_id: str, request: Request):
    """Remove a skill from the OpenClaw extensions directory."""
    ext_dir = _get_extensions_dir(request)
    target_dir = ext_dir / "dataclaw-tools" / "skills" / skill_id
    if target_dir.exists():
        shutil.rmtree(target_dir)
