"""Hooks that make external context research part of Dataclaw planning."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from dataclaw.state import AgentState


EXTERNAL_RESEARCH_FIRST_PROMPT = """

## External Context Research
For open-ended data science work, treat external context gathering as the first analytical step, before committing to modeling, validation, or experiment design. Use the context research tools to:
- generate concept-level queries from the user's problem, dataset descriptions, table names, and schema signals;
- search high-signal technical sources such as arXiv, maintained GitHub repositories, and GitHub issues;
- identify useful external data sources, benchmark methods, domain constraints, leakage risks, evaluation protocols, and feature-engineering hypotheses;
- save durable findings or research programs into OKF when an OKF bundle is available;
- compare any external-enriched or research-methodology-guided experiments against a provided-data-only baseline;
- run ablations that isolate each research-derived methodology, recording baseline metric, candidate metric, delta, diagnostics, and keep/tune/combine/reject decisions;
- use validation feedback from each ablation to adjust later modeling branches instead of treating research as static decoration.

Plans for experiments should place this external research and enrichment phase before EDA validation, baseline modeling, or parallel subagent experiments. Final modeling reports should include a methodology attribution table showing which research ideas were implemented, how they were translated into dataset-safe modeling choices, whether they improved metrics, and how the result changed the next model iteration. If relevant research already exists for the dataset or project, summarize and reuse it instead of repeating the same search.

### Research-step validation lifecycle
External research, OKF research notes, research programs, ablations, EDA, and modeling work can require an `analysis_review` gate. For each affected plan step, use this sequence:
1. Record the concrete summary, citations, caveats, bundle paths, program IDs, and other outputs, then call `update_plan` to mark only that step `completed`. Do not mark the overall plan completed or set `ready_for_validation` in the same call.
2. Call `request_analysis_review` with `scope="plan_step"` and the completed step's `plan_step_id`.
3. Inspect and resolve required review findings, then rerun the review when the evidence changes. Use `accept_gate_risk` only when the user explicitly approves proceeding with a documented rationale.
4. After the review gate passes or the risk has an audited acceptance, call `update_plan` to set that step's `ready_for_validation` to `true`.
5. Mark the overall plan `completed` only after every required step is ready for validation.

A successful context-research or OKF tool call is evidence for the review, not a review pass by itself. Never skip directly from saving research outputs to finalizing the plan.
"""

RESEARCH_STEP_NAME = "External context and data discovery"
RESEARCH_STEP_DESCRIPTION = (
    "Before modeling or validation, inspect the available dataset context and run "
    "external research. Generate concept-level queries from the problem and schema, "
    "search arXiv, GitHub repository, and GitHub issue sources as available, identify useful "
    "external data candidates and domain constraints, save durable findings to OKF "
    "when possible, translate research methodologies into dataset-safe modeling "
    "choices, require ablations against a provided-data-only baseline, and use "
    "validation feedback to promote, tune, combine, or reject each branch. Record "
    "citations, caveats, bundle paths, and program IDs before completing this step; "
    "then request analysis review and mark it ready for validation only after the "
    "gate passes or the user explicitly accepts the documented risk."
)

_RESEARCH_TERMS = (
    "external context",
    "external research",
    "context research",
    "research program",
    "source discovery",
    "external data",
    "enrichment",
)

_ANALYTICAL_PLAN_TERMS = (
    "analysis",
    "analyze",
    "dataset",
    "data",
    "eda",
    "experiment",
    "feature",
    "forecast",
    "hypothesis",
    "mlflow",
    "model",
    "notebook",
    "predict",
    "regression",
    "train",
    "validate",
    "validation",
)


async def external_research_first_prompt_hook(state: AgentState) -> AgentState:
    """postSystemPromptHook: add first-step research guidance to the prompt."""
    prompt = state.get("system_prompt", "")
    if not prompt or EXTERNAL_RESEARCH_FIRST_PROMPT.strip() in prompt:
        return state

    return {
        **state,
        "system_prompt": prompt.rstrip() + EXTERNAL_RESEARCH_FIRST_PROMPT,
    }


async def external_research_first_plan_hook(state: AgentState) -> AgentState:
    """preToolCallHook: keep external research first in proposed experiment plans."""
    pending = state.get("pending_tool_calls", [])
    if not pending:
        return state

    updated = []
    changed = False
    for tool_call in pending:
        if tool_call.get("tool_name") != "propose_plan":
            updated.append(tool_call)
            continue

        tool_input = tool_call.get("tool_input", {})
        revised = prioritize_external_research_step(tool_input)
        if revised is tool_input:
            updated.append(tool_call)
            continue

        updated.append({**tool_call, "tool_input": revised})
        changed = True

    if not changed:
        return state
    return {**state, "pending_tool_calls": updated}


def prioritize_external_research_step(tool_input: dict[str, Any]) -> dict[str, Any]:
    """Return tool input with external research as the first plan step when relevant."""
    steps = tool_input.get("steps")
    if not isinstance(steps, list) or not steps:
        return tool_input
    if not _looks_like_analytical_plan(tool_input):
        return tool_input

    if not any(isinstance(step, dict) for step in steps):
        return tool_input

    existing_index = next(
        (
            idx
            for idx, step in enumerate(steps)
            if isinstance(step, dict) and _is_external_research_step(step)
        ),
        None,
    )
    if existing_index == 0:
        return tool_input

    new_steps = deepcopy(steps)
    if existing_index is None:
        new_steps.insert(0, _new_research_step())
    else:
        step = new_steps.pop(existing_index)
        new_steps.insert(0, step)

    return {**tool_input, "steps": new_steps}


def _new_research_step() -> dict[str, Any]:
    return {
        "name": RESEARCH_STEP_NAME,
        "description": RESEARCH_STEP_DESCRIPTION,
        "status": "not_started",
        "ready_for_validation": False,
        "summary": "",
        "outputs": [],
    }


def _is_external_research_step(step: dict[str, Any]) -> bool:
    text = _combined_text(step)
    return any(term in text for term in _RESEARCH_TERMS)


def _looks_like_analytical_plan(tool_input: dict[str, Any]) -> bool:
    text = _combined_text(tool_input)
    return any(term in text for term in _ANALYTICAL_PLAN_TERMS)


def _combined_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(_combined_text(v) for v in value.values()).lower()
    if isinstance(value, list):
        return " ".join(_combined_text(v) for v in value).lower()
    if isinstance(value, str):
        return value.lower()
    return ""
