"""Tests for context research planning hooks."""

from __future__ import annotations

import pytest

from dataclaw_context_research.hooks import (
    EXTERNAL_RESEARCH_FIRST_PROMPT,
    external_research_first_plan_hook,
    external_research_first_prompt_hook,
    prioritize_external_research_step,
)


@pytest.mark.asyncio
async def test_prompt_hook_adds_external_research_policy_once():
    state = {"system_prompt": "Base prompt"}

    updated = await external_research_first_prompt_hook(state)
    updated_again = await external_research_first_prompt_hook(updated)

    assert "External Context Research" in updated["system_prompt"]
    assert "research-methodology-guided experiments" in updated["system_prompt"]
    assert "use validation feedback" in updated["system_prompt"]
    assert "Research-step validation lifecycle" in updated["system_prompt"]
    assert "request_analysis_review" in updated["system_prompt"]
    assert "Do not mark the overall plan completed" in updated["system_prompt"]
    assert "ready_for_validation" in updated["system_prompt"]
    assert "accept_gate_risk" in updated["system_prompt"]
    assert updated_again["system_prompt"].count(EXTERNAL_RESEARCH_FIRST_PROMPT.strip()) == 1


def test_prioritize_external_research_inserts_first_step_for_analytical_plan():
    tool_input = {
        "name": "Churn modeling experiment",
        "description": "Train and validate a prediction model.",
        "steps": [
            {
                "name": "EDA validation",
                "description": "Profile the dataset and validate target leakage.",
                "status": "not_started",
            },
            {
                "name": "Baseline model",
                "description": "Train a provided-data-only baseline.",
                "status": "not_started",
            },
        ],
    }

    revised = prioritize_external_research_step(tool_input)

    assert revised is not tool_input
    assert revised["steps"][0]["name"] == "External context and data discovery"
    assert "ablations against a provided-data-only baseline" in revised["steps"][0]["description"]
    assert "promote, tune, combine, or reject" in revised["steps"][0]["description"]
    assert "request analysis review" in revised["steps"][0]["description"]
    assert revised["steps"][0]["ready_for_validation"] is False
    assert revised["steps"][1]["name"] == "EDA validation"


def test_prioritize_external_research_moves_existing_step_to_front():
    tool_input = {
        "name": "Forecasting analysis",
        "description": "Run model experiments on time series data.",
        "steps": [
            {
                "name": "Baseline model",
                "description": "Train the first model.",
                "status": "not_started",
            },
            {
                "name": "External research",
                "description": "Gather external data and context.",
                "status": "not_started",
            },
        ],
    }

    revised = prioritize_external_research_step(tool_input)

    assert revised["steps"][0]["name"] == "External research"
    assert revised["steps"][1]["name"] == "Baseline model"


def test_prioritize_external_research_leaves_non_analytical_plan_unchanged():
    tool_input = {
        "name": "Write a short note",
        "description": "Summarize the latest user message.",
        "steps": [{"name": "Draft", "description": "Write text", "status": "not_started"}],
    }

    assert prioritize_external_research_step(tool_input) is tool_input


@pytest.mark.asyncio
async def test_plan_hook_rewrites_pending_propose_plan_call():
    state = {
        "pending_tool_calls": [
            {
                "tool_name": "propose_plan",
                "tool_input": {
                    "name": "Experiment plan",
                    "description": "Build and validate a model.",
                    "steps": [
                        {
                            "name": "Train model",
                            "description": "Fit a baseline model.",
                            "status": "not_started",
                        }
                    ],
                },
            },
            {
                "tool_name": "context_research_list_findings",
                "tool_input": {},
            },
        ]
    }

    updated = await external_research_first_plan_hook(state)

    steps = updated["pending_tool_calls"][0]["tool_input"]["steps"]
    assert steps[0]["name"] == "External context and data discovery"
    assert updated["pending_tool_calls"][1] == state["pending_tool_calls"][1]
