"""Skill library — read-only access to bundled community skills.

Library skills live in the skill-library/ directory at the repo root.
Installing a library skill copies it into ~/.dataclaw/skills/ with a
``source: library`` marker in the YAML frontmatter.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any, Iterable

import yaml

from dataclaw.config.paths import skill_library_dir, skills_dir
from dataclaw.storage.skills import read_skill, write_skill

logger = logging.getLogger(__name__)


def skill_body_hash(body: str) -> str:
    """Stable hash for skill instruction body content."""
    return hashlib.sha256(body.strip().encode("utf-8")).hexdigest()


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

    skills: list[dict[str, Any]] = []
    for path in sorted(lib_dir.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        meta = _read_frontmatter(path)
        if meta is not None:
            skill_id = path.stem
            body = (_read_full(path) or {}).get("body", "")
            installed_state = _installed_library_state(skill_id, body)
            skills.append({
                "id": skill_id,
                **meta,
                **installed_state,
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

    result.update(_installed_library_state(skill_id, result.get("body", "")))
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

    body = lib_skill.get("body", "")
    meta = {
        "name": lib_skill.get("name", skill_id),
        "description": lib_skill.get("description", ""),
        "tags": lib_skill.get("tags", []),
        "source": "library",
        "library_id": skill_id,
        "library_hash": skill_body_hash(body),
    }
    return write_skill(skill_id, meta, body)


def skill_freshness_for_installed_skill(
    skill_id: str,
    body: str,
    meta: dict[str, Any],
) -> dict[str, Any]:
    """Return freshness metadata for an installed skill.

    Library installs created before hashes existed are still checked by
    comparing the installed body with the current bundled library body.
    """
    source = meta.get("source")
    library_id = str(meta.get("library_id") or skill_id)
    if source != "library" and not meta.get("library_id"):
        return {}

    library = _read_full(skill_library_dir() / f"{library_id}.md")
    if library is None:
        return {
            "source": source,
            "library_id": library_id,
            "installed_stale": True,
            "stale_reason": "library_skill_missing",
        }

    library_body = str(library.get("body", ""))
    library_hash = skill_body_hash(library_body)
    installed_hash = skill_body_hash(body)
    recorded_hash = clean_optional_text(meta.get("library_hash") or meta.get("installed_from_library_hash"))
    installed_stale = installed_hash != library_hash
    stale_reason = ""
    if installed_stale and recorded_hash and recorded_hash != library_hash:
        stale_reason = "library_skill_changed"
    elif installed_stale:
        stale_reason = "installed_body_differs_from_library"

    return {
        "source": "library",
        "library_id": library_id,
        "library_hash": library_hash,
        "installed_hash": installed_hash,
        "installed_library_hash": recorded_hash,
        "installed_stale": installed_stale,
        "stale_reason": stale_reason,
    }


def stale_installed_library_skills(skill_ids: Iterable[str] | None = None) -> list[dict[str, Any]]:
    """List installed library skills whose active body differs from the bundled copy."""
    allowed = set(skill_ids) if skill_ids is not None else None
    stale: list[dict[str, Any]] = []
    for path in sorted(skills_dir().glob("*.md")):
        skill_id = path.stem
        if allowed is not None and skill_id not in allowed:
            continue
        installed = read_skill(skill_id)
        if not installed:
            continue
        state = skill_freshness_for_installed_skill(skill_id, str(installed.get("body", "")), installed)
        if state.get("installed_stale"):
            stale.append({
                "id": skill_id,
                "name": installed.get("name", skill_id),
                **state,
            })
    return stale


def clean_optional_text(value: Any) -> str:
    return "" if value in (None, "") else str(value)


def _installed_library_state(skill_id: str, library_body: str) -> dict[str, Any]:
    installed = read_skill(skill_id)
    if not installed:
        return {
            "installed": False,
            "installed_stale": False,
            "library_hash": skill_body_hash(library_body),
        }
    state = skill_freshness_for_installed_skill(skill_id, str(installed.get("body", "")), installed)
    state.setdefault("installed_stale", False)
    state.setdefault("library_hash", skill_body_hash(library_body))
    return {
        "installed": True,
        **state,
    }
