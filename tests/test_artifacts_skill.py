import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SKILL_LIBRARY = ROOT / "skill-library"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _has(text: str, phrase: str) -> bool:
    return " ".join(phrase.split()) in " ".join(text.split())


def _without_openclaw_directory_marker(text: str) -> str:
    lines = [
        line for line in text.splitlines()
        if not line.startswith("<!-- Canonical OpenClaw skill directory:")
    ]
    return "\n".join(lines).replace("---\n\n\n", "---\n\n").rstrip() + "\n"


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
    assert "`report_design` authors" in body
    assert "report-specific visual system" in body
    assert "open/source/export/delete operations are session-scoped" in body
    assert "25 MiB cap applies to the published/exported single-file artifact" in body
    assert "Living-report attribution should travel by id, not by name." in body
    assert "Security contract" in body
    assert "Completion checklist" in body
    assert "`dashboarding`" not in body


def test_report_design_skill_is_bundled_and_parseable():
    text = _read(SKILL_LIBRARY / "report_design.md")

    assert text.startswith("---")
    _, frontmatter, body = text.split("---", 2)
    meta = yaml.safe_load(frontmatter)

    assert meta["name"] == "report_design"
    assert "Author and publish bespoke analytical reports" in meta["description"]
    assert "report_design_report" in body
    assert "quality_gate=\"fail\"" in body
    assert "sole final-report composition layer" in body
    assert "Existing reports and revisions" in body
    assert "build_report" in body
    assert "preserved_low_confidence" in body
    assert "requirements.evidence_registry.targets" in body
    assert "export_docx=False" in body
    assert "`report_add_section` is a compatibility and draft helper" in body
    assert "presentation_mode=\"handcrafted\"" in body
    assert "`advanced_visual`" in body
    assert "requirements.story_arcs" in body
    assert "fallback tools, not quotas" in body
    assert "*.author-dossier.md" in body
    assert "data-dc-author-script" in body
    assert "independent evidence pass" in body
    assert "claim_source_id" in body
    assert "publication.require_visual_review=true" in body
    assert "build_report(presentation_mode=\"handcrafted\")" in body
    assert "Skill freshness warnings are advisory context" in body
    assert "Do not pre-compose a final page from component names" in body
    assert "Do not fetch a separate dashboard-layout skill" in body


def test_visual_output_skills_have_one_final_report_owner():
    dataclaw = _read(SKILL_LIBRARY / "dataclaw.md")
    report_design = _read(SKILL_LIBRARY / "report_design.md")
    visualization = _read(SKILL_LIBRARY / "visualization.md")
    artifacts = _read(SKILL_LIBRARY / "artifacts.md")

    assert not (SKILL_LIBRARY / "dashboarding.md").exists()
    assert "fetch `report_design`" in dataclaw
    assert "the creative author owns all unspecified prose" in dataclaw
    assert "`report_design` for final report authorship" in artifacts
    assert "fetch `artifacts`" in visualization
    assert "Required handoff" in report_design
    assert "report_design_report" in visualization
    assert "requirements.evidence_registry.targets" in visualization
    assert "grain, population/scope, units, denominator" in visualization
    assert "Do not pre-compose the report" in visualization
    assert "do not add a `chart` or `visual` mapping merely" in visualization
    assert _has(visualization, "Do not use `report_add_section` to assemble a polished report")
    assert "`dashboarding`" not in visualization
    assert "`dashboarding`" not in report_design
    assert "`dashboarding`" not in dataclaw


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

    assert _without_openclaw_directory_marker(bundled_report_design) == canonical_report_design


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

    assert "fetch the `artifacts` skill for publication or revision" in bundled_data_science
    assert "fetch `report_design`" in bundled_data_science
    assert "`dashboarding`" not in bundled_data_science
    assert "published artifact or living report" in bundled_data_science
    assert "embedded in the App panel" not in bundled_data_science
