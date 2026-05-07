"""Skill library — read-only access to bundled community skills.

Library skills live in the skill-library/ directory at the repo root.
Installing a library skill copies it into ~/.dataclaw/skills/ with a
``source: library`` marker in the YAML frontmatter.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from dataclaw.config.paths import skill_library_dir, skills_dir
from dataclaw.storage.skills import write_skill

logger = logging.getLogger(__name__)


def _read_frontmatter(path: Path) -> dict[str, Any] | None:
    """Read YAML frontmatter from a library skill file."""
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


def _read_full(path: Path) -> dict[str, Any] | None:
    """Read a library skill file returning metadata and body."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None

    skill_id = path.stem
    if not text.startswith("---"):
        return {"id": skill_id, "body": text}

    parts = text.split("---", 2)
    if len(parts) < 3:
        return {"id": skill_id, "body": text}

    try:
        meta = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        meta = {}

    return {
        "id": skill_id,
        "body": parts[2].strip(),
        **meta,
    }


def list_library_skills() -> list[dict[str, Any]]:
    """List all library skills with metadata and installed status."""
    lib_dir = skill_library_dir()
    if not lib_dir.exists():
        return []

    user_dir = skills_dir()
    skills: list[dict[str, Any]] = []
    for path in sorted(lib_dir.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        meta = _read_frontmatter(path)
        if meta is not None:
            skill_id = path.stem
            skills.append({
                "id": skill_id,
                "installed": (user_dir / f"{skill_id}.md").exists(),
                **meta,
            })
    return skills


def read_library_skill(skill_id: str) -> dict[str, Any] | None:
    """Read a single library skill by ID."""
    path = skill_library_dir() / f"{skill_id}.md"
    if not path.exists():
        return None

    result = _read_full(path)
    if result is None:
        return None

    user_dir = skills_dir()
    result["installed"] = (user_dir / f"{skill_id}.md").exists()
    return result


def install_library_skill(skill_id: str, force: bool = False) -> Path:
    """Install a library skill into the user's skills directory.

    Copies the skill from skill-library/ to ~/.dataclaw/skills/ and
    adds ``source: library`` and ``library_id`` to the frontmatter.

    Raises FileNotFoundError if the library skill doesn't exist.
    Raises FileExistsError if already installed (unless force=True).
    """
    lib_skill = read_library_skill(skill_id)
    if lib_skill is None:
        raise FileNotFoundError(f"Library skill not found: {skill_id}")

    if not force and lib_skill.get("installed"):
        raise FileExistsError(f"Skill already installed: {skill_id}")

    meta = {
        "name": lib_skill.get("name", skill_id),
        "description": lib_skill.get("description", ""),
        "tags": lib_skill.get("tags", []),
        "source": "library",
        "library_id": skill_id,
    }
    body = lib_skill.get("body", "")
    return write_skill(skill_id, meta, body)
