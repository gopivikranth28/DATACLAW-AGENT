import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"

# Tracked in git — must always exist and pass.
TRACKED_PRDS = [
    "eda-findings-prd.md",
    "structured-eda-prd.md",
]

# Local-only planning material (gitignored); assertions run when present.
LOCAL_PRDS = [
    "artifacts-prd.md",
    "data-intake-prd.md",
    "query-lab-prd.md",
    "modeling-evaluation-prd.md",
    "analysis-review-prd.md",
]

COMPONENT_PRDS = TRACKED_PRDS + LOCAL_PRDS


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _read_doc(filename: str) -> str:
    path = DOCS / filename
    if not path.exists():
        pytest.skip(f"{filename} is local-only planning material and not present")
    return _read(path)


def test_portfolio_defines_shared_contracts():
    portfolio = _read_doc("prd-portfolio.md")

    assert "Registers canonical unprefixed PythonTool names" in portfolio
    assert "OpenClaw may expose `dataclaw_...` aliases" in portfolio
    assert "Persisted objects, hooks, events, and tool parameters use `plan_step_id`" in portfolio
    assert "do not let it satisfy plan completion, artifact evidence, review, export" in portfolio
    assert "DATACLAW_PREVIEW_MAX_ROWS = 20" in portfolio
    assert "DATACLAW_PREVIEW_MAX_BYTES = 50 KiB" in portfolio
    assert "Build Order & Blocking Dependencies" in portfolio
    assert "Artifacts P0 security hardening" in portfolio
    assert "Shared Acceptance Fixtures" in portfolio
    assert "assert_openclaw_tool_aliases" in portfolio
    assert "[Plans Contract Note](plans-contract-prd.md)" in portfolio
    assert "| Publish/report | [DataClaw Artifacts PRD](artifacts-prd.md)" in portfolio
    assert "Working portfolio, build-ready PRDs in progress" in portfolio
    assert "| Build prerequisite |" in portfolio
    assert "| Drafted |" in portfolio


@pytest.mark.parametrize("filename", COMPONENT_PRDS)
def test_component_prds_include_openclaw_manifest_checks(filename):
    text = _read_doc(filename)

    assert "OpenClaw alias/manifest check" in text, filename
    assert "generated OpenClaw manifest/allowlist exposes" in text, filename


@pytest.mark.parametrize("filename", COMPONENT_PRDS)
def test_component_prds_do_not_persist_generic_step_id(filename):
    text = _read_doc(filename)

    assert re.search(r"(?<!plan_)\bstep_id\b", text) is None, filename


def test_artifacts_report_notes_use_plan_step_id():
    artifacts_prd = _read_doc("artifacts-prd.md")
    artifacts_skill = _read(ROOT / "skill-library" / "artifacts.md")

    assert "report_note(page, markdown, plan_step_id?)" in artifacts_prd
    assert "report_note(page, markdown, plan_step_id?)" in artifacts_skill
    assert "report_note(page, markdown, step?)" not in artifacts_prd
    assert "report_note(page, markdown, step?)" not in artifacts_skill


def test_model_card_publish_routes_through_artifacts():
    modeling = _read_doc("modeling-evaluation-prd.md")

    assert "`publish_model_card(spec_id, comparison_id?, artifact_id?, base_version?)`" in modeling
    assert "then calls `publish_artifact`" in modeling
    assert "same `artifact_id`/`base_version` semantics" in modeling
    assert "cannot satisfy model-card artifact gates" in modeling


def test_artifacts_prd_splits_security_hardening_from_spine():
    artifacts = _read_doc("artifacts-prd.md")

    assert "**P0 — Preview security hardening**" in artifacts
    assert "Standalone PR before plugin work" in artifacts
    assert "**P1 — The spine**" in artifacts
    assert "using P0 fixes" in artifacts


def test_top_level_tool_rows_are_concrete():
    expected_tools = {
        "eda-findings-prd.md": [
            "`record_eda_finding`",
            "`list_eda_findings`",
            "`read_eda_finding`",
            "`supersede_eda_finding`",
            "`summarize_eda_readiness`",
        ],
        "structured-eda-prd.md": [
            "`propose_eda_hypotheses`",
            "`update_eda_hypothesis`",
            "`list_eda_hypotheses`",
            "`record_eda_finding`",
            "`supersede_eda_finding`",
            "`list_eda_findings`",
            "`read_eda_finding`",
            "`summarize_eda_readiness`",
            "`request_analysis_review`",
            "`list_review_findings`",
            "`resolve_review_finding`",
            "`get_review_gate`",
            "`accept_gate_risk`",
        ],
        "query-lab-prd.md": [
            "`create_query_card`",
            "`run_query_card`",
            "`revise_query_card`",
            "`validate_query_card`",
            "`read_query_card`",
            "`list_query_cards`",
        ],
        "modeling-evaluation-prd.md": [
            "`create_modeling_spec`",
            "`log_model_run_summary`",
            "`validate_model_run`",
            "`compare_model_runs`",
            "`record_model_decision`",
            "`publish_model_card`",
        ],
        "analysis-review-prd.md": [
            "`request_analysis_review`",
            "`list_review_findings`",
            "`resolve_review_finding`",
            "`get_review_gate`",
        ],
    }

    for filename, tools in expected_tools.items():
        path = DOCS / filename
        if not path.exists():
            continue  # local-only planning material
        text = _read(path)
        checklist = text.split("## Convergence checklist", 1)[1].split("# Part 1", 1)[0]
        for tool in tools:
            assert tool in checklist, (filename, tool)


def test_plans_contract_note_defines_blocking_dependency():
    plans = _read_doc("plans-contract-prd.md")

    assert "Build prerequisite for Artifacts P3, Query Lab, Modeling, and Analysis Review" in plans
    assert "`plan_step_id`" in plans
    assert "`ready_for_validation`" in plans
    assert "name matching is\n  display-only fallback" in plans
    assert "OpenClaw alias/manifest check" in plans


def test_structured_eda_prd_defines_hypothesis_and_gate_contracts():
    text = _read_doc("structured-eda-prd.md")

    # Hypothesis ledger contract
    assert "unresolved_needs_domain_input" in text
    assert "`source ∈ {user_goal, mode_expected_risk, domain_prior, data_signal, prior_finding, reviewer}`" in text
    assert "rejected-and-kept" in text
    # Two-axis validation + honesty floors
    assert "unverified against external evidence" in text
    assert "validation.internal" in text
    assert "validation.external" in text
    # Gate enforcement and escape hatch
    assert "`accept_gate_risk`" in text
    assert "gate_blocked" in text
    assert "checklist-only review can never yield a `pass` gate" in text
    # Degradation and attribution
    assert "unattributed_step" in text
    # Evals
    assert "DATACLAW_LIVE_EVAL" in text
    assert "hypotheses.jsonl" in text


def test_structured_eda_prd_supersedes_eda_findings_slice():
    structured = _read_doc("structured-eda-prd.md")
    eda_findings = _read_doc("eda-findings-prd.md")

    assert "eda-findings-prd.md" in structured  # supersession is explicit
    assert "structured-eda-prd.md" in eda_findings  # back-pointer present
