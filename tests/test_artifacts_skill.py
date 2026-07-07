from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SKILL_LIBRARY = ROOT / "skill-library"
DOCS = ROOT / "docs"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_artifacts_skill_is_bundled_and_parseable():
    text = _read(SKILL_LIBRARY / "artifacts.md")

    assert text.startswith("---")
    _, frontmatter, body = text.split("---", 2)
    meta = yaml.safe_load(frontmatter)

    assert meta["name"] == "artifacts"
    assert "Publish, revise, inspect, export" in meta["description"]
    assert "publish_artifact" in body
    assert "read_artifact" in body
    assert "same `artifact_id`" in body
    assert "dataclaw_publish_artifact" in body
    assert "artifact publication is unavailable" in body
    assert "Use `publish_artifact` for a standalone report" in body
    assert "Use `report_note` for interpretation" in body
    assert "5 MB cap applies to the published/exported single-file artifact" in body
    assert "Living-report attribution should travel by id, not by name." in body
    assert "Security contract" in body
    assert "Completion checklist" in body


def test_visual_output_skills_route_publish_to_artifacts_skill():
    dataclaw = _read(SKILL_LIBRARY / "dataclaw.md")
    visualization = _read(SKILL_LIBRARY / "visualization.md")
    dashboarding = _read(SKILL_LIBRARY / "dashboarding.md")

    assert "fetch the `artifacts` skill before publishing or revising" in dataclaw
    assert "fetch and follow the `artifacts` skill" in visualization
    assert "fetch and follow the `artifacts` skill" in dashboarding
    assert "Step attribution travels by stable plan step id" in visualization
    assert "dataclaw_report_add_section" in visualization
    assert "artifact publication is unavailable" in visualization
    assert "Attribute sections and notes by stable plan step id" in dashboarding
    assert "publication is unavailable" in dashboarding
    assert "when browser\n  tooling is available" in dashboarding


def test_openclaw_bundles_artifacts_skill():
    canonical_artifacts = _read(SKILL_LIBRARY / "artifacts.md")
    bundled_artifacts = _read(
        ROOT
        / "openclaw-plugins"
        / "dataclaw"
        / "skills"
        / "artifacts"
        / "SKILL.md"
    )

    assert bundled_artifacts == canonical_artifacts


def test_openclaw_data_science_routes_final_reports_to_artifacts():
    bundled_data_science = _read(
        ROOT
        / "openclaw-plugins"
        / "dataclaw"
        / "skills"
        / "dataclaw-data-science"
        / "SKILL.md"
    )

    assert "fetch the `artifacts` skill before publishing or revising" in bundled_data_science
    assert "published artifact or living report" in bundled_data_science
    assert "embedded in the App panel" not in bundled_data_science


def test_artifacts_prd_covers_alignment_contracts():
    prd = _read(DOCS / "artifacts-prd.md")

    assert "artifact publishing unavailable" in prd
    assert "FR-1a Tool namespace contract" in prd
    assert "dataclaw_publish_artifact" in prd
    assert "Skill convergence: `artifacts`, `dashboarding`, and `visualization`" in prd
    assert "report-design" not in prd
    assert "current `report_add_section` implementation must stop falling back" in prd
    assert "Surface choice rule" in prd
    assert "5 MB cap applies to a *published/exported* single file" in prd
    assert "browser tooling is not installed" in prd
