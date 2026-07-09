"""Tests for the skill library — browse and install community skills."""

from pathlib import Path

import pytest

from dataclaw.storage.skill_library import (
    install_library_skill,
    list_library_skills,
    read_library_skill,
    skill_body_hash,
    stale_installed_library_skills,
)


@pytest.fixture
def library_dir(tmp_path, monkeypatch):
    """Point skill_library_dir() at a temp directory."""
    lib = tmp_path / "skill-library"
    lib.mkdir()
    import dataclaw.storage.skill_library as mod
    monkeypatch.setattr(mod, "skill_library_dir", lambda: lib)
    return lib


@pytest.fixture
def user_skills_dir(tmp_dataclaw_home):
    """Ensure the user skills directory exists."""
    sdir = tmp_dataclaw_home / "skills"
    sdir.mkdir(exist_ok=True)
    return sdir


def _write_library_skill(library_dir: Path, name: str, meta_yaml: str, body: str):
    path = library_dir / f"{name}.md"
    path.write_text(f"---\n{meta_yaml}\n---\n\n{body}\n")


# ── list_library_skills ─────────────────────────────────────────────────────


def test_list_empty(library_dir):
    assert list_library_skills() == []


def test_list_skills(library_dir):
    _write_library_skill(library_dir, "profiling", "name: profiling\ndescription: Profile data", "Step 1")
    _write_library_skill(library_dir, "sql", "name: sql\ndescription: SQL queries", "Write SQL")

    result = list_library_skills()
    assert len(result) == 2
    assert result[0]["id"] == "profiling"
    assert result[0]["name"] == "profiling"
    assert result[0]["installed"] is False
    assert result[1]["id"] == "sql"


def test_list_skips_readme(library_dir):
    _write_library_skill(library_dir, "skill1", "name: skill1", "body")
    (library_dir / "README.md").write_text("# Skill Library\n")

    result = list_library_skills()
    assert len(result) == 1
    assert result[0]["id"] == "skill1"


def test_list_shows_installed_status(library_dir, user_skills_dir):
    _write_library_skill(library_dir, "installed_skill", "name: installed_skill", "body")
    # Simulate an already-installed skill
    (user_skills_dir / "installed_skill.md").write_text("---\nname: installed_skill\n---\n\nbody\n")

    result = list_library_skills()
    assert len(result) == 1
    assert result[0]["installed"] is True


def test_list_nonexistent_dir(monkeypatch):
    """Gracefully returns empty when library dir doesn't exist."""
    import dataclaw.storage.skill_library as mod
    monkeypatch.setattr(mod, "skill_library_dir", lambda: Path("/nonexistent"))
    assert list_library_skills() == []


# ── read_library_skill ──────────────────────────────────────────────────────


def test_read_skill(library_dir):
    _write_library_skill(library_dir, "profiling", "name: profiling\ndescription: Profile data\ntags:\n  - data", "Step 1: Load")

    result = read_library_skill("profiling")
    assert result is not None
    assert result["id"] == "profiling"
    assert result["name"] == "profiling"
    assert result["description"] == "Profile data"
    assert result["body"] == "Step 1: Load"
    assert result["installed"] is False


def test_read_nonexistent(library_dir):
    assert read_library_skill("nonexistent") is None


def test_read_no_frontmatter(library_dir):
    (library_dir / "plain.md").write_text("Just plain text content")

    result = read_library_skill("plain")
    assert result is not None
    assert result["id"] == "plain"
    assert result["body"] == "Just plain text content"


# ── install_library_skill ───────────────────────────────────────────────────


def test_install(library_dir, user_skills_dir):
    _write_library_skill(library_dir, "profiling", "name: profiling\ndescription: Profile data\ntags:\n  - data", "Step 1: Load")

    path = install_library_skill("profiling")
    assert path.exists()
    assert path == user_skills_dir / "profiling.md"

    # Verify the installed file has source: library marker
    content = path.read_text()
    assert "source: library" in content
    assert "library_id: profiling" in content
    assert f"library_hash: {skill_body_hash('Step 1: Load')}" in content
    # Verify original content is preserved
    assert "Step 1: Load" in content


def test_install_not_found(library_dir):
    with pytest.raises(FileNotFoundError):
        install_library_skill("nonexistent")


def test_install_already_exists(library_dir, user_skills_dir):
    _write_library_skill(library_dir, "existing", "name: existing", "body")
    (user_skills_dir / "existing.md").write_text("---\nname: existing\n---\n\nold body\n")

    with pytest.raises(FileExistsError):
        install_library_skill("existing")


def test_install_force_overwrite(library_dir, user_skills_dir):
    _write_library_skill(library_dir, "existing", "name: existing\ndescription: Updated", "new body")
    (user_skills_dir / "existing.md").write_text("---\nname: existing\n---\n\nold body\n")

    path = install_library_skill("existing", force=True)
    assert path.exists()
    content = path.read_text()
    assert "new body" in content
    assert "source: library" in content


def test_install_updates_installed_status(library_dir, user_skills_dir):
    _write_library_skill(library_dir, "my_skill", "name: my_skill", "body")

    # Before install
    result = read_library_skill("my_skill")
    assert result["installed"] is False

    install_library_skill("my_skill")

    # After install
    result = read_library_skill("my_skill")
    assert result["installed"] is True


def test_list_marks_stale_installed_library_skill(library_dir, user_skills_dir):
    _write_library_skill(library_dir, "visualization", "name: visualization", "new body")
    (user_skills_dir / "visualization.md").write_text(
        "---\nname: visualization\nsource: library\nlibrary_id: visualization\n---\n\nold body\n",
        encoding="utf-8",
    )

    result = list_library_skills()
    assert result[0]["installed"] is True
    assert result[0]["installed_stale"] is True
    assert result[0]["stale_reason"] == "installed_body_differs_from_library"

    stale = stale_installed_library_skills()
    assert stale[0]["id"] == "visualization"
    assert stale[0]["installed_stale"] is True


def test_read_marks_hash_based_library_change(library_dir, user_skills_dir):
    _write_library_skill(library_dir, "dashboarding", "name: dashboarding", "new body")
    (user_skills_dir / "dashboarding.md").write_text(
        "---\nname: dashboarding\nsource: library\nlibrary_id: dashboarding\nlibrary_hash: oldhash\n---\n\nold body\n",
        encoding="utf-8",
    )

    result = read_library_skill("dashboarding")
    assert result["installed"] is True
    assert result["installed_stale"] is True
    assert result["stale_reason"] == "library_skill_changed"
