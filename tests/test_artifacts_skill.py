import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SKILL_LIBRARY = ROOT / "skill-library"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _has(text: str, phrase: str) -> bool:
    return " ".join(phrase.split()) in " ".join(text.split())


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


def test_report_design_skill_is_bundled_and_parseable():
    text = _read(SKILL_LIBRARY / "report_design.md")

    assert text.startswith("---")
    _, frontmatter, body = text.split("---", 2)
    meta = yaml.safe_load(frontmatter)

    assert meta["name"] == "report_design"
    assert "Design polished analytical reports" in meta["description"]
    assert "report_design_report" in body
    assert "quality_gate=\"fail\"" in body
    assert "storyboard JSON" in body
    assert "Upgrade an existing HTML report" in body
    assert "build_report" in body
    assert "preserved_low_confidence" in body
    assert "requirements.evidence_registry.targets" in body
    assert "export_docx=False" in body
    assert "`report_add_section` is a compatibility and draft helper" in body
    assert "`plain_chart_overuse`" in body
    assert "`chart_table_explorer`" in body
    assert "`filterable_chart`" in body
    assert "`interactive_table`" in body
    assert "`selector_panel`" in body
    assert "`entity_card_grid`" in body
    assert _has(body, "A report with several plain charts and no explorer is a failed report shape.")


def test_visual_output_skills_route_publish_to_artifacts_skill():
    dataclaw = _read(SKILL_LIBRARY / "dataclaw.md")
    report_design = _read(SKILL_LIBRARY / "report_design.md")
    visualization = _read(SKILL_LIBRARY / "visualization.md")
    dashboarding = _read(SKILL_LIBRARY / "dashboarding.md")
    artifacts = _read(SKILL_LIBRARY / "artifacts.md")

    assert "fetch the `artifacts` skill before publishing or revising" in dataclaw
    assert "Fetch the `dashboarding` and `report_design` skills before the reporting step" in dataclaw
    assert _has(visualization, "fetch and follow `dashboarding` and `report_design` too")
    assert _has(dashboarding, "fetch the `report_design` skill before final report generation")
    assert "`report_design` for final report storyboards" in artifacts
    assert "fetch and follow the `artifacts` skill" in visualization
    assert "fetch and follow the `artifacts` skill" in dashboarding
    assert "Report tool contract" in report_design
    assert "Step attribution travels by stable plan step id" in visualization
    assert "report_design_report" in visualization
    assert "report_publish" in visualization
    assert "requirements.evidence_registry.targets" in visualization
    assert "storyboard JSON" in visualization
    assert "do not rely on appended report cells" in visualization
    assert "dataclaw_report_add_section" in visualization
    assert "`insight_grid`" in visualization
    assert "`narrative_band`" in visualization
    assert "`methodology_block`" in visualization
    assert "`chart_interpretation`" in visualization
    assert "`evidence_rail`" in visualization
    assert "`ledger_timeline`" in visualization
    assert "`hypothesis_ledger`" in visualization
    assert "`evidence_trace`" in visualization
    assert "`finding_id`" in visualization
    assert "`hypothesis_id`" in visualization
    assert "`chart_table_explorer`" in visualization
    assert "`interactive_table`" in visualization
    assert "`selector_panel`" in visualization
    assert "`entity_card_grid`" in visualization
    assert '"plan_step_id": "step-a1b2c3d4"' in visualization
    assert "artifact publication is unavailable" in visualization
    assert "Attribute sections and notes by stable plan step id" in dashboarding
    assert "report_design_report" in dashboarding
    assert "report_publish" in dashboarding
    assert _has(dashboarding, "appended report cells as the final dashboard/report architecture")
    assert "EDA findings ledger" in dashboarding
    assert "structured EDA readiness verdict" in dashboarding
    assert "publication is unavailable" in dashboarding
    assert "`/app/:sessionId` is only a compatibility scratch view" in dashboarding
    assert "`/app/:sessionId` route is compatibility only" in visualization
    assert "`chart_interpretation` and `evidence_rail`" in dashboarding
    assert "`methodology_block`" in dashboarding
    assert "`ledger_timeline`" in dashboarding
    assert "one shared DataClaw token system" in dashboarding
    assert "shared DataClaw artifact token system" in visualization
    assert _has(dashboarding, "when browser tooling is available")


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


def test_openclaw_bundles_report_design_skill():
    canonical_report_design = _read(SKILL_LIBRARY / "report_design.md")
    bundled_report_design = _read(
        ROOT
        / "openclaw-plugins"
        / "dataclaw"
        / "skills"
        / "report_design"
        / "SKILL.md"
    )

    assert bundled_report_design == canonical_report_design


def test_openclaw_plugin_contract_includes_report_designer_tool():
    manifest = json.loads(_read(ROOT / "openclaw-plugins" / "dataclaw" / "openclaw.plugin.json"))

    assert "dataclaw_report_design_report" in manifest["contracts"]["tools"]


def test_openclaw_data_science_routes_final_reports_to_artifacts():
    bundled_data_science = _read(
        ROOT
        / "openclaw-plugins"
        / "dataclaw"
        / "skills"
        / "dataclaw"
        / "SKILL.md"
    )

    assert "fetch the `artifacts` skill before publishing or revising" in bundled_data_science
    assert "Fetch the `dashboarding` and `report_design` skills before the reporting step" in bundled_data_science
    assert "published artifact or living report" in bundled_data_science
    assert "embedded in the App panel" not in bundled_data_science
