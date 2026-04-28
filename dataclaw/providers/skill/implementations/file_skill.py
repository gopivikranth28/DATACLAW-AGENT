"""File-based skill provider.

Reads skill files from a directory (default ~/.dataclaw/skills/).
Each skill is a markdown file with YAML frontmatter:

    ---
    name: data_profiling
    description: Guides the agent through dataset profiling
    tags: [data, analysis]
    ---

    When asked to profile a dataset, follow these steps:
    1. Load the dataset
    2. Run statistical summaries
    ...
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from dataclaw.config.paths import skills_dir
from dataclaw.state import AgentState

logger = logging.getLogger(__name__)


def _parse_skill_file(path: Path) -> dict[str, Any] | None:
    """Parse a skill markdown file with YAML frontmatter."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None

    parts = text.split("---", 2)
    if len(parts) < 3:
        return None

    try:
        meta = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        logger.warning("Invalid YAML frontmatter in %s", path)
        return None

    body = parts[2].strip()
    return {
        "id": path.stem,
        "name": meta.get("name", path.stem),
        "description": meta.get("description", ""),
        "tags": meta.get("tags", []),
        "body": body,
        "path": str(path),
    }


class FileSkillProvider:
    """Reads skills from markdown files in a directory."""

    def __init__(self, directory: Path | None = None) -> None:
        self._dir = directory or skills_dir()

    def _load_all(self) -> list[dict[str, Any]]:
        if not self._dir.exists():
            return []
        skills = []
        for path in sorted(self._dir.glob("*.md")):
            skill = _parse_skill_file(path)
            if skill:
                skills.append(skill)
        return skills

    async def resolve_skills(self, state: AgentState) -> list[dict[str, Any]]:
        return self._load_all()

    async def format_for_prompt(self, skills: list[dict[str, Any]]) -> list[str]:
        fragments = []
        for skill in skills:
            fragments.append(
                f"### {skill['name']}\n{skill.get('description', '')}\n{skill.get('body', '')}"
            )
        return fragments

    async def fetch_skill(self, skill_id: str) -> dict[str, Any] | None:
        for skill in self._load_all():
            if skill["id"] == skill_id:
                return skill
        return None
