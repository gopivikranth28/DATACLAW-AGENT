from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SKILL_LIBRARY = ROOT / "skill-library"


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
    assert "export_artifact" in body
    assert "same `artifact_id`" in body
    assert "dataclaw_publish_artifact" in body
    assert "artifact publication is unavailable" in body
    assert "Use `publish_artifact` for a standalone report" in body
    assert "Use `report_note` for interpretation" in body
    assert "`record_eda_finding` is the living-report entry" in body
    assert "one note per non-EDA finding" in body
    assert "inline published-artifact card plus the right" in body
    assert "Treat `/app/:sessionId` as a legacy" in body
    assert "reports and dashboards should feel like one" in body
    assert ".r-section" in body
    assert "open/source/export/delete operations are session-scoped" in body
    assert "25 MiB cap applies to the published/exported single-file artifact" in body
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
    assert "`insight_grid`" in visualization
    assert "`hypothesis_ledger`" in visualization
    assert "`evidence_trace`" in visualization
    assert "`finding_id`" in visualization
    assert "`hypothesis_id`" in visualization
    assert '"plan_step_id": "step-a1b2c3d4"' in visualization
    assert "artifact publication is unavailable" in visualization
    assert "Attribute sections and notes by stable plan step id" in dashboarding
    assert "EDA findings ledger" in dashboarding
    assert "structured EDA readiness verdict" in dashboarding
    assert "publication is unavailable" in dashboarding
    assert "`/app/:sessionId` is only a compatibility scratch view" in dashboarding
    assert "`/app/:sessionId` route is compatibility only" in visualization
    assert "one shared DataClaw token system" in dashboarding
    assert "shared DataClaw artifact token system" in visualization
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
