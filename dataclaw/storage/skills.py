"""Skill file I/O — read and write skill markdown files.

Skills are stored as markdown files with YAML frontmatter
under ~/.dataclaw/skills/.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from dataclaw.config.paths import skills_dir

logger = logging.getLogger(__name__)


def list_skill_files() -> list[dict[str, Any]]:
    """List all skill files with their metadata."""
    sdir = skills_dir()
    if not sdir.exists():
        return []

    skills = []
    for path in sorted(sdir.glob("*.md")):
        meta = _read_frontmatter(path)
        if meta is not None:
            skills.append({
                "id": path.stem,
                "path": str(path),
                **meta,
            })
    return skills


def read_skill(skill_id: str) -> dict[str, Any] | None:
    """Read a skill file by ID (filename without extension)."""
    path = skills_dir() / f"{skill_id}.md"
    if not path.exists():
        return None

    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {"id": skill_id, "body": text, "path": str(path)}

    parts = text.split("---", 2)
    if len(parts) < 3:
        return {"id": skill_id, "body": text, "path": str(path)}

    try:
        meta = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        meta = {}

    return {
        "id": skill_id,
        "path": str(path),
        "body": parts[2].strip(),
        **meta,
    }


def write_skill(skill_id: str, meta: dict[str, Any], body: str) -> Path:
    """Write a skill file with YAML frontmatter."""
    sdir = skills_dir()
    sdir.mkdir(parents=True, exist_ok=True)
    path = sdir / f"{skill_id}.md"

    frontmatter = yaml.dump(meta, default_flow_style=False).strip()
    content = f"---\n{frontmatter}\n---\n\n{body}\n"
    path.write_text(content, encoding="utf-8")
    return path


def delete_skill(skill_id: str) -> bool:
    """Delete a skill file."""
    path = skills_dir() / f"{skill_id}.md"
    if not path.exists():
        return False
    path.unlink()
    return True


def _read_frontmatter(path: Path) -> dict[str, Any] | None:
    """Read just the YAML frontmatter from a skill file."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None

    if not text.startswith("---"):
        return {"name": path.stem}

    parts = text.split("---", 2)
    if len(parts) < 3:
        return {"name": path.stem}

    try:
        return yaml.safe_load(parts[1]) or {"name": path.stem}
    except yaml.YAMLError:
        return {"name": path.stem}
