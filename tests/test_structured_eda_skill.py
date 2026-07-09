from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SKILL_LIBRARY = ROOT / "skill-library"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


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
    assert "Fetch the `visualization` skill" in body
    assert "report_design_report" in body
    assert "Do not treat appended report cells as the final EDA report" in body
    assert "`hypothesis_ledger`" in body
    assert "`ledger_timeline`" in body
    assert "`evidence_trace`" in body
    assert "`evidence_rail`" in body
    assert "`chart_interpretation`" in body
    assert "`methodology_block`" in body
    assert "`narrative_band`" in body
    assert "`insight_grid`" in body
    assert "`methodology`" in body
    assert "new layer of\nunderstanding" in body
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
        / "dataclaw-data-science"
        / "SKILL.md"
    )

    assert "fetch the `structured_eda` skill" in bundled_skill
    assert "Use `data_profiling` only for a compact quick profile" in bundled_skill
    assert "dataclaw_request_analysis_review" in bundled_skill


def test_openclaw_bundles_structured_eda_skill():
    canonical_structured_eda = _read(SKILL_LIBRARY / "structured_eda.md")
    bundled_structured_eda = _read(
        ROOT
        / "openclaw-plugins"
        / "dataclaw"
        / "skills"
        / "structured-eda"
        / "SKILL.md"
    )

    assert bundled_structured_eda == canonical_structured_eda
