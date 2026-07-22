from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SKILL_LIBRARY = ROOT / "skill-library"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _without_openclaw_directory_marker(text: str) -> str:
    lines = [
        line for line in text.splitlines()
        if not line.startswith("<!-- Canonical OpenClaw skill directory:")
    ]
    return "\n".join(lines).replace("---\n\n\n", "---\n\n").rstrip() + "\n"


def test_structured_eda_skill_is_bundled_and_parseable():
    text = _read(SKILL_LIBRARY / "structured_eda.md")

    assert text.startswith("---")
    _, frontmatter, body = text.split("---", 2)
    meta = yaml.safe_load(frontmatter)

    assert meta["name"] == "structured_eda"
    assert "goal-directed exploratory data analysis" in meta["description"]
    assert "Hypothesis ledger" in body
    assert "propose_eda_hypotheses" in body
    assert "record_eda_finding" in body
    assert "summarize_eda_readiness" in body
    assert "deferred: loop budget" in body
    assert "Insight loop behavior" in body
    assert "Default to at most 3 insight loops" in body
    assert "Fetch `visualization` when non-trivial notebook charting" in body
    assert "Fetch `report_design` before producing a polished EDA report" in body
    assert "report_design_report" in body
    assert "report_publish" in body
    assert "requirements.evidence_registry.targets" in body
    assert "preserved_low_confidence" in body
    assert "Do not treat appended report cells as the final EDA report" in body
    assert "grain, population, units, denominator" in body
    assert "Do not prescribe chart types, KPI counts, components" in body
    assert "Pass the author the new layer of understanding" in body
    assert "Skill freshness is advisory" in body
    assert "`loop_index`" in body
    assert "`selection` with `screened_n`, `selection_rule`, and `correction`" in body


def test_core_library_skills_route_nontrivial_eda_to_structured_eda():
    dataclaw = _read(SKILL_LIBRARY / "dataclaw.md")
    profiling = _read(SKILL_LIBRARY / "data_profiling.md")
    analysis_review = _read(SKILL_LIBRARY / "analysis_review.md")

    assert "fetch the `structured_eda` skill" in dataclaw
    assert "dataclaw_propose_eda_hypotheses" in dataclaw
    assert "dataclaw_summarize_eda_readiness" in dataclaw
    assert "dataclaw_request_analysis_review" in dataclaw
    assert "automatic checklist review" in dataclaw
    assert "request_analysis_review(scope=\"plan_step\"" in analysis_review
    assert "sub-agent-required" in analysis_review
    assert "Use `data_profiling` only for a compact quick profile" in dataclaw
    assert "fetch and follow `structured_eda` instead" in profiling
    assert "Stop condition" in profiling


def test_openclaw_dataclaw_skill_routes_eda_to_structured_eda():
    bundled_skill = _read(
        ROOT
        / "openclaw-plugins"
        / "dataclaw"
        / "skills"
        / "dataclaw"
        / "SKILL.md"
    )

    assert "fetch the `structured_eda` skill" in bundled_skill
    assert "fetch `report_design`" in bundled_skill
    assert "`dashboarding`" not in bundled_skill
    assert "Use `data_profiling` only for a compact quick profile" in bundled_skill
    assert "dataclaw_request_analysis_review" in bundled_skill
    assert "report_publish" in bundled_skill
    assert _without_openclaw_directory_marker(bundled_skill) == _read(SKILL_LIBRARY / "dataclaw.md")


def test_openclaw_bundles_structured_eda_skill():
    canonical_structured_eda = _read(SKILL_LIBRARY / "structured_eda.md")
    bundled_structured_eda = _read(
        ROOT
        / "openclaw-plugins"
        / "dataclaw"
        / "skills"
        / "structured_eda"
        / "SKILL.md"
    )

    assert _without_openclaw_directory_marker(bundled_structured_eda) == canonical_structured_eda
