"""OpenClaw skill sync — copy/remove Dataclaw skills to/from OpenClaw's managed skills dir.

Synced skills go to ``<openclaw state dir>/skills/<skill_id>/SKILL.md`` (the
"managed / local" skills root, shared by every agent and watched by the
gateway). They used to be written into the installed plugin directory
(``extensions/dataclaw/skills/``), but every ``openclaw plugins install
--force`` replaces that directory — and the bundled image reinstalls the
plugin on each start — so synced skills silently disappeared.

A ``.dataclaw-sync`` marker in each synced directory keeps sync from
overwriting, and unsync from deleting, a skill the user installed in the
managed root by other means.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from dataclaw.storage.skills import read_skill

router = APIRouter()

SYNC_MARKER = ".dataclaw-sync"


def _get_openclaw_home(request: Request) -> Path:
    """Resolve the OpenClaw state directory (``.openclaw``) from plugin config.

    Handles both conventions for openclaw_dir:
      - openclaw_dir = /Users/user          → /Users/user/.openclaw/
      - openclaw_dir = /Users/user/.openclaw → /Users/user/.openclaw/
    """
    # Read from config file directly (not app.state.config which is stale after saves)
    from dataclaw.config.resolver import resolve
    # "~" matches the openclaw_dir field default in the plugin's config schema.
    openclaw_dir = resolve("plugins.openclaw.openclaw_dir", "DATACLAW_OPENCLAW_DIR", "~")
    if not openclaw_dir:
        raise HTTPException(status_code=400, detail="openclaw_dir is not configured. Set it in Config → OpenClaw.")
    base = Path(openclaw_dir).expanduser()
    if not base.exists():
        raise HTTPException(status_code=400, detail=f"openclaw_dir does not exist: {base}")
    # If base already IS the .openclaw directory, use it directly
    return base if base.name == ".openclaw" else base / ".openclaw"


def _skill_target_dir(request: Request, skill_id: str) -> Path:
    if not skill_id or "/" in skill_id or "\\" in skill_id or skill_id in {".", ".."}:
        raise HTTPException(status_code=400, detail="Invalid skill id")
    return _get_openclaw_home(request) / "skills" / skill_id


@router.post("/skills/{skill_id}/sync")
async def sync_skill(skill_id: str, request: Request):
    """Copy a skill into OpenClaw's managed skills directory."""
    skill = read_skill(skill_id)
    if skill is None:
        raise HTTPException(status_code=404, detail="Skill not found")

    target_dir = _skill_target_dir(request, skill_id)
    if target_dir.exists() and not (target_dir / SYNC_MARKER).exists():
        raise HTTPException(
            status_code=409,
            detail=f"OpenClaw already has a skill at {target_dir} that Dataclaw did not sync; not overwriting it.",
        )
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / SYNC_MARKER).write_text(f"{skill_id}\n", encoding="utf-8")

    target_path = target_dir / "SKILL.md"
    frontmatter = f"---\nname: {skill.get('name', skill_id)}\ndescription: {skill.get('description', '')}\n---\n"
    target_path.write_text(frontmatter + "\n" + skill.get("body", ""), encoding="utf-8")

    return {"synced_to": str(target_path)}


@router.delete("/skills/{skill_id}/sync", status_code=204)
async def remove_skill_sync(skill_id: str, request: Request):
    """Remove a skill that Dataclaw previously synced to OpenClaw."""
    target_dir = _skill_target_dir(request, skill_id)
    if target_dir.exists():
        if not (target_dir / SYNC_MARKER).exists():
            raise HTTPException(
                status_code=409,
                detail=f"{target_dir} was not synced by Dataclaw; not removing it.",
            )
        shutil.rmtree(target_dir)
