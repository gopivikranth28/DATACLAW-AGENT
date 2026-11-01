"""Tests for open-world context research plugin."""

from __future__ import annotations

from pathlib import Path

import pytest

import dataclaw.config.paths as paths
from dataclaw_data.registry import create_dataset
from dataclaw_context_research.academic import parse_arxiv
from dataclaw_context_research.github import parse_github_issues, parse_github_repositories
from dataclaw_context_research.query import generate_queries, generate_queries_with_llm
from dataclaw.providers.llm.provider import TextDeltaEvent, TurnCompleteEvent
from dataclaw_context_research.registry import filter_findings, find_program, read_findings
from dataclaw_context_research.tools import (
    context_research_build_program,
    context_research_list_findings,
    context_research_run_parallel_experiments,
    context_research_save_program_to_okf,
    context_research_save_to_okf,
    context_research_search_sources,
    context_research_summarize_findings,
    set_delegate_to_subagent,
)
from dataclaw_okf.generator import generate_bundle


@pytest.fixture(autouse=True)
def tmp_home(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DATACLAW_HOME", tmp_path)
    return tmp_path


@pytest.fixture
def survey_dataset(tmp_path):
    csv_path = tmp_path / "customer_survey.csv"
    csv_path.write_text(
        "respondent_id,nps_score,satisfaction_rating,churn_flag,comment_text\n"
        "1,10,5,0,love it\n"
        "2,2,1,1,too expensive\n",
        encoding="utf-8",
    )
    return create_dataset(
        name="Customer Survey",
        ds_type="csv",
        connection=str(csv_path),
        description="Customer feedback and retention survey",
    )


def test_generate_queries_uses_schema_as_concept_signal(survey_dataset):
    result = generate_queries(
        dataset_id=survey_dataset["id"],
        problem_statement="Understand why customers churn after poor satisfaction scores",
    )

    assert result["queries"]
    assert result["inferred_domain"] in {"survey", "saas", "data analysis"}
    joined = " ".join(result["queries"]).lower()
    assert "common pitfalls" in joined
    assert "missing data" in joined
    assert "churn" in joined or "satisfaction" in joined


def test_generate_queries_expands_problem_understanding_beyond_literal_keywords():
    problem = "Predict which users will stop paying after a bad onboarding experience"
    result = generate_queries(problem_statement=problem, limit=8)

    joined = " ".join(result["queries"]).lower()
    assert result["inferred_domain"] == "saas"
    assert result["inferred_objective"] == "prediction"
    assert result["problem_understanding"]["target"] == "churn"
    assert "customer retention" in joined
    assert "subscription churn" in joined
    assert "cancellation propensity" in joined or "retention risk" in joined
    assert "literature review" in joined
    assert "benchmark dataset" in joined
    assert problem.lower() not in [q.lower() for q in result["queries"]]


def test_generate_queries_uses_domain_research_language_for_real_estate():
    result = generate_queries(
        problem_statement="Predict house sale price from property attributes",
        limit=8,
    )

    joined = " ".join(result["queries"]).lower()
    assert result["inferred_domain"] == "real estate"
    assert result["problem_understanding"]["target"] == "saleprice"
    assert "residential property valuation" in joined
    assert "hedonic pricing" in joined
    assert "neighborhood amenities" in joined


def test_generate_queries_understands_educational_game_event_logs():
    problem = (
        "Predict student performance from educational game play event logs. "
        "Before modeling, perform deep external research, identify external data/enrichment "
        "candidates, create hypotheses, dispatch parallel experiment branches to subagents, "
        "and compare all enriched branches against a provided-data-only baseline."
    )

    result = generate_queries(problem_statement=problem, limit=10)

    joined = " ".join(result["queries"]).lower()
    concepts = result["concepts"]
    understanding = result["problem_understanding"]
    assert result["inferred_domain"] == "education / learning analytics"
    assert result["inferred_objective"] == "sequence prediction"
    assert understanding["target"] == "student performance"
    assert "learning analytics" in joined
    assert "educational data mining" in joined
    assert "student performance prediction" in joined
    assert "game based learning analytics" in joined
    assert "knowledge tracing benchmarks" in joined
    assert "student level leakage" in joined or "session temporal leakage" in joined
    assert "subagents" not in concepts
    assert "branches" not in concepts


@pytest.mark.asyncio
async def test_generate_queries_uses_llm_understanding_when_provider_available():
    class FakeResearchLLM:
        async def stream_turn(self, messages, *, system, tools):
            assert not tools
            assert "Do not merely reuse keywords" in system
            text = """{
              "problem_understanding": {
                "real_world_domain": "educational game-based learning",
                "analytical_objective": "sequence-based student performance prediction",
                "unit_of_analysis": "student game session",
                "outcome_or_target": "assessment performance",
                "data_modality": "gameplay event logs",
                "source_context": "educational data mining and learning analytics",
                "research_angles": ["knowledge tracing", "student modeling"],
                "external_enrichment_angles": ["curriculum metadata", "item difficulty"],
                "validation_risks": ["student-level leakage", "temporal leakage"]
              },
              "queries": [
                "educational data mining gameplay event logs student performance prediction",
                "game based learning analytics knowledge tracing assessment performance benchmark",
                "student modeling event sequence features temporal validation leakage"
              ]
            }"""
            yield TextDeltaEvent(text=text)
            yield TurnCompleteEvent()

        def build_tool_result_message(self, tool_calls, results, errors):
            return []

    result = await generate_queries_with_llm(
        llm=FakeResearchLLM(),
        problem_statement="Predict student performance from educational game play event logs",
        limit=3,
    )

    joined = " ".join(result["queries"]).lower()
    assert result["generation_mode"] == "llm"
    assert result["inferred_domain"] == "educational game-based learning"
    assert "knowledge tracing" in joined
    assert "temporal validation" in joined


def test_parse_arxiv_normalizes_preprints_as_medium_evidence():
    feed = """<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <id>http://arxiv.org/abs/2501.00001v1</id>
        <updated>2025-01-01T00:00:00Z</updated>
        <published>2025-01-01T00:00:00Z</published>
        <title>Time series forecasting for operations</title>
        <summary>Forecasting methods for operational datasets.</summary>
        <author><name>Grace Researcher</name></author>
      </entry>
    </feed>
    """

    findings = parse_arxiv(feed, query="operations forecasting")

    assert len(findings) == 1
    assert findings[0]["source"] == "arxiv"
    assert findings[0]["source_type"] == "paper"
    assert findings[0]["evidence_level"] == "medium"
    assert findings[0]["authors"] == ["Grace Researcher"]


def test_parse_github_repositories_normalizes_repos_as_medium_evidence():
    payload = {
        "items": [
            {
                "full_name": "example/churn-model",
                "html_url": "https://github.com/example/churn-model",
                "description": "Maintained churn modeling examples",
                "stargazers_count": 100,
                "forks_count": 20,
                "language": "Python",
                "updated_at": "2026-01-01T00:00:00Z",
            }
        ]
    }

    findings = parse_github_repositories(payload, query="churn model")

    assert len(findings) == 1
    finding = findings[0]
    assert finding["source"] == "github"
    assert finding["source_type"] == "code_repository"
    assert finding["evidence_level"] == "medium"
    assert finding["stars"] == 100


def test_parse_github_issues_normalizes_issues_as_medium_evidence():
    payload = {
        "items": [
            {
                "title": "Leakage in churn benchmark",
                "html_url": "https://github.com/example/churn-model/issues/12",
                "body": "The benchmark includes labels leaked into feature columns.",
                "state": "open",
                "comments": 4,
                "updated_at": "2026-01-02T00:00:00Z",
            }
        ]
    }

    findings = parse_github_issues(payload, query="churn leakage")

    assert len(findings) == 1
    finding = findings[0]
    assert finding["source"] == "github"
    assert finding["source_type"] == "code_repository"
    assert finding["evidence_level"] == "medium"
    assert finding["comments"] == 4
    assert "issue" in finding["tags"]


@pytest.mark.asyncio
async def test_search_sources_persists_mixed_provider_findings(monkeypatch, survey_dataset):
    async def fake_search_one_source(source, *, query, limit, timeout):
        return [
            {
                "query": query,
                "source": source,
                "source_type": "paper" if source == "arxiv" else "code_repository",
                "evidence_level": "medium",
                "title": f"{source} result",
                "url": f"https://example.com/{source}",
                "snippet": "Useful external context.",
                "tags": ["mocked"],
                "accepted_for_okf": False,
            }
        ]

    monkeypatch.setattr("dataclaw_context_research.tools._search_one_source", fake_search_one_source)

    result = await context_research_search_sources(
        query="customer churn data quality",
        sources=["arxiv", "github_repositories", "github_issues"],
        dataset_id=survey_dataset["id"],
    )

    assert result["status"] == "saved"
    assert result["saved_count"] == 3
    assert not result["errors"]
    findings = filter_findings(dataset_id=survey_dataset["id"])
    assert {f["source"] for f in findings} == {"arxiv", "github_repositories", "github_issues"}
    assert {f["evidence_level"] for f in findings} == {"medium"}


@pytest.mark.asyncio
async def test_summarize_and_save_findings_to_okf(monkeypatch, survey_dataset):
    async def fake_search_one_source(source, *, query, limit, timeout):
        return [
            {
                "query": query,
                "source": "github",
                "source_type": "code_repository",
                "evidence_level": "medium",
                "title": "Churn leakage warning",
                "url": "https://github.com/example/churn-model/issues/2",
                "snippet": "Watch for leakage from fields created after cancellation.",
                "tags": ["code_repository", "issue"],
                "accepted_for_okf": False,
            }
        ]

    monkeypatch.setattr("dataclaw_context_research.tools._search_one_source", fake_search_one_source)
    await context_research_search_sources(
        query="churn leakage pitfalls",
        sources=["github_issues"],
        dataset_id=survey_dataset["id"],
    )

    summary = await context_research_summarize_findings(dataset_id=survey_dataset["id"])
    assert summary["count"] == 1
    assert summary["evidence_levels"]["medium"] == 1

    bundle = generate_bundle(survey_dataset["id"])
    saved = await context_research_save_to_okf(bundle_id=bundle["id"], dataset_id=survey_dataset["id"])
    assert saved["saved_findings"] == 1
    assert "Request analysis review" in " ".join(saved["validation_guidance"]["required_sequence"])
    assert "ready for validation" in saved["validation_guidance"]["plan_completion"]

    external_context = Path(bundle["path"]) / "notes" / "external_context.md"
    text = external_context.read_text(encoding="utf-8")
    assert "External Context" in text
    assert "medium" in text
    assert "Churn leakage warning" in text
    assert read_findings()[0]["accepted_for_okf"] is True


@pytest.mark.asyncio
async def test_build_research_program_creates_hypotheses_and_experiment_tasks(monkeypatch, survey_dataset):
    async def fake_search_one_source(source, *, query, limit, timeout):
        return [
            {
                "query": query,
                "source": "arxiv",
                "source_type": "paper",
                "evidence_level": "medium",
                "title": "Feature engineering for churn prediction",
                "url": "https://arxiv.org/abs/2501.00001",
                "snippet": "Feature engineering and temporal validation improve churn prediction.",
                "tags": ["academic", "preprint"],
                "accepted_for_okf": False,
            }
        ]

    monkeypatch.setattr("dataclaw_context_research.tools._search_one_source", fake_search_one_source)
    await context_research_search_sources(
        query="churn feature engineering",
        sources=["arxiv"],
        dataset_id=survey_dataset["id"],
    )

    program = await context_research_build_program(
        dataset_id=survey_dataset["id"],
        problem_statement="Improve churn prediction with external context and better experiments.",
    )

    assert program["id"].startswith("program-")
    assert program["hypotheses"]
    first_hypothesis = program["hypotheses"][0]
    assert first_hypothesis["source_attribution"]["title"] == "Feature engineering for churn prediction"
    assert first_hypothesis["source_attribution"]["url"] == "https://arxiv.org/abs/2501.00001"
    assert first_hypothesis["source_attribution"]["evidence_level"] == "medium"
    assert "Matched because" in first_hypothesis["problem_match"]
    assert "churn" in first_hypothesis["problem_match"].lower()
    assert "https://arxiv.org/abs/2501.00001" in str(first_hypothesis)
    assert program["methodology_translations"]
    assert program["methodology_translations"][0]["source_attribution"]["url"] == "https://arxiv.org/abs/2501.00001"
    assert "Matched because" in program["methodology_translations"][0]["problem_match"]
    assert program["ablation_plan"]
    assert program["external_data_candidates"]
    assert program["experiment_branches"]
    assert program["subagent_tasks"]
    assert program["feedback_loop"]["baseline_required"] is True
    assert program["feedback_loop"]["ablation_required"] is True
    assert "next_model_adjustment" in program["feedback_loop"]["required_result_fields"]
    assert {"promote", "tune", "combine", "reject"} == set(program["feedback_loop"]["decision_values"])
    assert any(item["variant"] == "single_methodology_ablation" for item in program["ablation_plan"])
    assert program["experiment_branches"][0]["methodology_id"].startswith("m-")
    assert program["experiment_branches"][0]["ablation_id"].startswith("abl-m-")
    assert "next_model_adjustment" in program["subagent_tasks"][0]["task"]
    assert find_program(program["id"])["dataset_id"] == survey_dataset["id"]


@pytest.mark.asyncio
async def test_save_research_program_to_okf(monkeypatch, survey_dataset):
    async def fake_search_one_source(source, *, query, limit, timeout):
        return [
            {
                "query": query,
                "source": "github",
                "source_type": "code_repository",
                "evidence_level": "medium",
                "title": "Survey churn feature engineering",
                "url": "https://github.com/example/churn-model",
                "snippet": "Churn analysis benefits from survey satisfaction features and leakage-safe validation.",
                "tags": ["code_repository", "implementation"],
                "accepted_for_okf": False,
            }
        ]

    monkeypatch.setattr("dataclaw_context_research.tools._search_one_source", fake_search_one_source)
    await context_research_search_sources(
        query="survey churn feature engineering",
        sources=["github_repositories"],
        dataset_id=survey_dataset["id"],
    )

    program = await context_research_build_program(
        dataset_id=survey_dataset["id"],
        problem_statement="Improve survey churn analysis.",
    )
    bundle = generate_bundle(survey_dataset["id"])

    result = await context_research_save_program_to_okf(
        bundle_id=bundle["id"],
        program_id=program["id"],
    )

    assert result["path"] == "notes/research_program.md"
    assert "Request analysis review" in " ".join(result["validation_guidance"]["required_sequence"])
    assert "ready for validation" in result["validation_guidance"]["plan_completion"]
    text = (Path(bundle["path"]) / "notes" / "research_program.md").read_text(encoding="utf-8")
    assert "Research Program" in text
    assert "https://github.com/example/churn-model" in text
    assert "Problem match" in text
    assert "Matched because" in text
    assert "Methodology Translations" in text
    assert "Ablation Plan" in text
    assert "Experiment Branches" in text
    assert "Feedback Loop" in text


@pytest.mark.asyncio
async def test_parallel_experiment_runner_uses_delegate_mock(survey_dataset):
    program = await context_research_build_program(
        dataset_id=survey_dataset["id"],
        problem_statement="Improve survey churn analysis.",
    )
    calls = []

    async def fake_delegate_to_subagent(**kwargs):
        calls.append(kwargs)
        return {"status": "completed", "result": "mocked experiment result"}

    set_delegate_to_subagent(fake_delegate_to_subagent)

    result = await context_research_run_parallel_experiments(
        program_id=program["id"],
        subagent_names=["experimenter-a", "experimenter-b"],
        max_tasks=2,
    )

    assert result["status"] == "completed"
    assert result["tasks_dispatched"] == 2
    assert len(calls) == 2
    assert {c["subagent_name"] for c in calls} == {"experimenter-a", "experimenter-b"}
    assert "delta_vs_baseline" in calls[0]["task"]
    assert "promote/tune/combine/reject" in calls[0]["task"]


@pytest.mark.asyncio
async def test_list_findings_empty():
    result = await context_research_list_findings()
    assert result == {"findings": [], "count": 0}
