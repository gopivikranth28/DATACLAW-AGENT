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
from dataclaw.storage.skill_library import read_library_skill, skill_freshness_for_installed_skill
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
    skill = {
        "id": path.stem,
        "name": meta.get("name", path.stem),
        "description": meta.get("description", ""),
        "tags": meta.get("tags", []),
        "body": body,
        "path": str(path),
    }
    for key, value in meta.items():
        skill.setdefault(key, value)
    freshness = skill_freshness_for_installed_skill(path.stem, body, meta)
    skill.update(freshness)
    if freshness.get("installed_stale") and freshness.get("stale_reason") != "library_skill_missing":
        library_id = str(freshness.get("library_id") or meta.get("library_id") or path.stem)
        library = read_library_skill(library_id) or {}
        library_body = str(library.get("body") or "")
        if library_body:
            skill["installed_body"] = body
            skill["body"] = library_body
            skill["active_body_source"] = "bundled_library"
            for key in ("name", "description", "tags"):
                value = library.get(key)
                if value not in (None, "", []):
                    skill[key] = value
    return skill


class FileSkillProvider:
    """Reads skills from markdown files in a directory."""

    def __init__(self, directory: Path | None = None) -> None:
        self._dir = directory or skills_dir()
        self._resolved_skills: list[dict[str, Any]] = []
        # Sentinel: distinguishes "resolve_skills() never ran for this
        # request" (use _load_all() — same behavior as old code) from
        # "resolve_skills() ran and the filter is empty" (no skills, don't
        # fall back to all). Set on every resolve_skills() call.
        self._resolved_skills_set: bool = False

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
        all_skills = self._load_all()

        # Check session-level allowlist first, then project-level
        allowed_ids = self._resolve_allowed_ids(state)
        if allowed_ids is not None:
            filtered = [s for s in all_skills if s["id"] in allowed_ids]
        else:
            filtered = all_skills

        # Assign serial IDs for unambiguous LLM tool calls
        for i, skill in enumerate(filtered):
            skill["serial_id"] = f"skill_{i + 1}"

        self._resolved_skills = filtered
        self._resolved_skills_set = True
        return filtered

    def _resolve_allowed_ids(self, state: AgentState) -> list[str] | None:
        """Resolve skill allowlist from session → project → None (all)."""
        import json
        from dataclaw.config.paths import sessions_dir

        session_id = state.get("session_id")
        if session_id:
            try:
                path = sessions_dir() / f"{session_id}.json"
                if path.exists():
                    data = json.loads(path.read_text())
                    if data.get("skillIds") is not None:
                        return data["skillIds"]
            except Exception:
                pass

        project_id = state.get("project_id")
        if project_id:
            try:
                from dataclaw_projects.registry import get_project
                proj = get_project(project_id)
                if proj.get("skill_ids") is not None:
                    return proj["skill_ids"]
            except Exception:
                pass

        return None

    async def format_for_prompt(self, skills: list[dict[str, Any]]) -> list[str]:
        """Format skill summaries for the system prompt.

        Only includes id, name, and description — not the full body.
        The agent uses the ``fetch_skill`` tool to load the full content
        when it decides to apply a skill.
        """
        if not skills:
            return []
        lines = ["Available skills (use the `fetch_skill` tool with the id to load full instructions):"]
        for skill in skills:
            sid = skill.get("serial_id", skill["id"])
            desc = skill.get("description", "")
            line = f"- {skill['name']} (id: {sid})"
            if desc:
                line += f" - {desc}"
            if skill.get("installed_stale"):
                line += " [stale installed library copy]"
            lines.append(line)
        stale_names = [str(skill.get("name") or skill.get("id")) for skill in skills if skill.get("installed_stale")]
        if stale_names:
            lines.append("")
            lines.append(
                "Skill freshness warning: installed library skills are stale versus the bundled skill-library "
                f"({', '.join(stale_names)}). Reinstall or force-update them before relying on report composition guidance."
            )
        return ["\n".join(lines)]

    async def fetch_skill(self, skill_id: str, **kwargs: Any) -> dict[str, Any]:
        """Fetch the full content of a skill by its serial ID. Used as an agent tool."""
        # Look up from the cached resolved list first (has serial_ids).
        for skill in self._resolved_skills:
            if skill.get("serial_id") == skill_id or skill["id"] == skill_id:
                return {
                    "content": _skill_content(skill),
                    "id": skill.get("serial_id", skill["id"]),
                    "name": skill["name"],
                    "description": skill.get("description", ""),
                    "installed_stale": bool(skill.get("installed_stale")),
                    "stale_reason": skill.get("stale_reason", ""),
                }
        # Fallback only when no per-request resolve happened (e.g., a
        # standalone CLI invocation). If the session-aware preToolCallHook
        # ran and the requested id wasn't in the resolved set, the filter
        # excluded it on purpose — don't reach into _load_all() and bypass.
        if not self._resolved_skills_set:
            for skill in self._load_all():
                if skill["id"] == skill_id:
                    return {
                        "content": _skill_content(skill),
                        "id": skill["id"],
                        "name": skill["name"],
                        "description": skill.get("description", ""),
                        "installed_stale": bool(skill.get("installed_stale")),
                        "stale_reason": skill.get("stale_reason", ""),
                    }
        return {"content": f"Skill not found: {skill_id}", "is_error": True}

    async def list_available_skills(self, **kwargs: Any) -> dict[str, Any]:
        """List skills available for the current session. Used as an agent tool."""
        # Trust the resolved cache *only* if resolve_skills() was actually
        # called for this request (set by the preToolCallHook in app.py).
        # The old `_resolved_skills or _load_all()` fallback also fired for
        # explicit empty-list filters (a session with `skillIds: []`), so
        # filtering down to zero silently became "show everything".
        if self._resolved_skills_set:
            skills = self._resolved_skills
        else:
            skills = self._load_all()
        lines = []
        for i, s in enumerate(skills):
            sid = s.get("serial_id", f"skill_{i + 1}")
            stale = " [stale installed library copy]" if s.get("installed_stale") else ""
            lines.append(f"- {s['name']} (id: {sid}): {s.get('description', '')}{stale}")
        return {"content": "\n".join(lines) if lines else "No skills available."}


def _skill_content(skill: dict[str, Any]) -> str:
    warning = ""
    if skill.get("installed_stale"):
        reason = skill.get("stale_reason") or "installed copy differs from bundled skill-library"
        source_note = (
            " Using the bundled skill-library instructions for this turn."
            if skill.get("active_body_source") == "bundled_library"
            else " Reinstall or force-update it before relying on these instructions."
        )
        warning = (
            "Skill freshness warning: this installed library skill is stale versus the bundled "
            f"skill-library ({reason}).{source_note}\n\n"
        )
    return f"{warning}# {skill['name']}\n\n{skill.get('body', '')}"
