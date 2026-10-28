"""Agent tools for open-world context research."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import asyncio

from dataclaw_context_research.academic import search_arxiv
from dataclaw_context_research.github import search_github_issues, search_github_repositories
from dataclaw_context_research.program import build_research_program, program_markdown
from dataclaw_context_research.query import generate_queries_with_llm
from dataclaw_context_research.registry import (
    filter_findings,
    filter_programs,
    find_program,
    mark_saved_to_okf,
    save_program,
    save_findings,
)
from dataclaw_context_research.summary import external_context_markdown, summarize_findings
from dataclaw_okf.registry import find_bundle, upsert_bundle


_plugin_cfg: dict[str, Any] = {}
_delegate_to_subagent: Any = None
_llm_provider: Any = None


def _research_validation_guidance() -> dict[str, Any]:
    """Describe the plan lifecycle that should follow durable research output."""
    return {
        "required_sequence": [
            "Record the current plan step's summary, citations, caveats, and output paths.",
            "Mark only the current step completed; do not finalize the plan or set ready_for_validation in the same update.",
            "Request analysis review for the completed plan_step_id.",
            "Resolve required findings and rerun review, or accept gate risk only with explicit user approval and rationale.",
            "Set ready_for_validation only after the review passes or the risk has audited acceptance.",
        ],
        "plan_completion": "Finalize the overall plan only after every required step is ready for validation.",
    }


def set_plugin_cfg(cfg: dict[str, Any]) -> None:
    global _plugin_cfg
    _plugin_cfg = cfg or {}


def set_llm_provider(provider: Any) -> None:
    global _llm_provider
    _llm_provider = provider


def set_delegate_to_subagent(fn: Any) -> None:
    global _delegate_to_subagent
    _delegate_to_subagent = fn


async def context_research_generate_queries(
    *,
    dataset_id: str = "",
    problem_statement: str = "",
    limit: int = 8,
    **kwargs: Any,
) -> dict[str, Any]:
    return await generate_queries_with_llm(
        llm=_llm_provider,
        dataset_id=dataset_id,
        problem_statement=problem_statement,
        limit=limit,
    )


async def context_research_search_sources(
    *,
    query: str,
    sources: list[str] | None = None,
    dataset_id: str = "",
    problem_statement: str = "",
    limit: int = 8,
    **kwargs: Any,
) -> dict[str, Any]:
    """Search multiple external source providers and persist normalized findings."""
    selected = sources or ["arxiv", "github_repositories", "github_issues"]
    max_results = int(_plugin_cfg.get("max_results", 15) or 15)
    effective_limit = min(max(1, int(limit)), max_results)
    timeout = int(_plugin_cfg.get("request_timeout", 12) or 12)
    all_findings: list[dict[str, Any]] = []
    errors = []

    for source in selected:
        try:
            findings = await _search_one_source(source, query=query, limit=effective_limit, timeout=timeout)
        except Exception as exc:
            errors.append({"source": source, "error": str(exc)})
            continue
        all_findings.extend({
            **finding,
            "dataset_id": dataset_id,
            "problem_statement": problem_statement,
        } for finding in findings)

    saved = save_findings(all_findings)
    return {
        "status": "saved" if saved else "empty",
        "query": query,
        "sources": selected,
        "saved_count": len(saved),
        "errors": errors,
        "findings": [_summarize_finding(f) for f in saved],
        "note": "Findings are normalized and evidence-labeled. Verify external sources before using them as assumptions.",
    }


async def context_research_list_findings(
    *,
    dataset_id: str = "",
    limit: int = 20,
    **kwargs: Any,
) -> dict[str, Any]:
    findings = filter_findings(dataset_id=dataset_id, limit=int(limit))
    return {"findings": [_summarize_finding(f) for f in findings], "count": len(findings)}


async def context_research_summarize_findings(
    *,
    dataset_id: str = "",
    finding_ids: list[str] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    findings = filter_findings(dataset_id=dataset_id, finding_ids=finding_ids)
    return summarize_findings(findings)


async def context_research_save_to_okf(
    *,
    bundle_id: str,
    dataset_id: str = "",
    finding_ids: list[str] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    bundle = find_bundle(bundle_id)
    findings = filter_findings(dataset_id=dataset_id or str(bundle.get("dataset_id", "")), finding_ids=finding_ids)
    root = Path(str(bundle.get("path", "")))
    if not root.exists():
        raise ValueError(f"OKF bundle path is missing: {root}")
    target = root / "notes" / "external_context.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(external_context_markdown(findings), encoding="utf-8")

    files = set(bundle.get("files", []))
    files.add("notes/external_context.md")
    updated = {
        **bundle,
        "files": sorted(files),
        "file_count": len(files),
    }
    upsert_bundle(updated)
    mark_saved_to_okf([str(f.get("id")) for f in findings], bundle_id)
    return {
        "bundle_id": bundle_id,
        "path": "notes/external_context.md",
        "saved_findings": len(findings),
        "evidence_note": "External context is cited and evidence-labeled; verify technical findings against the dataset before relying on them.",
        "validation_guidance": _research_validation_guidance(),
    }


async def context_research_build_program(
    *,
    dataset_id: str = "",
    problem_statement: str = "",
    finding_ids: list[str] | None = None,
    max_hypotheses: int = 8,
    **kwargs: Any,
) -> dict[str, Any]:
    findings = filter_findings(dataset_id=dataset_id, finding_ids=finding_ids)
    program = build_research_program(
        dataset_id=dataset_id,
        problem_statement=problem_statement,
        findings=findings,
        max_hypotheses=max_hypotheses,
    )
    saved = save_program(program)
    return _summarize_program(saved)


async def context_research_list_programs(
    *,
    dataset_id: str = "",
    limit: int = 20,
    **kwargs: Any,
) -> dict[str, Any]:
    programs = filter_programs(dataset_id=dataset_id, limit=limit)
    return {"programs": [_summarize_program(p) for p in programs], "count": len(programs)}


async def context_research_save_program_to_okf(
    *,
    bundle_id: str,
    program_id: str,
    **kwargs: Any,
) -> dict[str, Any]:
    bundle = find_bundle(bundle_id)
    program = find_program(program_id)
    root = Path(str(bundle.get("path", "")))
    if not root.exists():
        raise ValueError(f"OKF bundle path is missing: {root}")
    target = root / "notes" / "research_program.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(program_markdown(program), encoding="utf-8")
    files = set(bundle.get("files", []))
    files.add("notes/research_program.md")
    updated = {**bundle, "files": sorted(files), "file_count": len(files)}
    upsert_bundle(updated)
    return {
        "bundle_id": bundle_id,
        "program_id": program_id,
        "path": "notes/research_program.md",
        "hypotheses": len(program.get("hypotheses", [])),
        "experiment_branches": len(program.get("experiment_branches", [])),
        "validation_guidance": _research_validation_guidance(),
    }


async def context_research_run_parallel_experiments(
    *,
    program_id: str,
    subagent_names: list[str],
    max_tasks: int = 4,
    **kwargs: Any,
) -> dict[str, Any]:
    if _delegate_to_subagent is None:
        return {
            "status": "error",
            "error": "delegate_to_subagent is not available. Enable the projects/subagents plugin and configure experiment subagents.",
        }
    program = find_program(program_id)
    tasks = program.get("subagent_tasks", [])[: max(1, int(max_tasks))]
    if not tasks:
        return {"status": "empty", "results": [], "message": "No subagent tasks are available for this program."}
    if not subagent_names:
        return {"status": "error", "error": "Provide at least one subagent name."}

    async def run_one(idx: int, task: dict[str, Any]) -> dict[str, Any]:
        subagent = subagent_names[idx % len(subagent_names)]
        result = await _delegate_to_subagent(subagent_name=subagent, task=task["task"])
        return {"task_id": task.get("task_id"), "subagent": subagent, "result": result}

    results = await asyncio.gather(*(run_one(i, task) for i, task in enumerate(tasks)))
    return {
        "status": "completed",
        "program_id": program_id,
        "tasks_dispatched": len(results),
        "results": results,
        "next_step": "Compare subagent recommendations, promote only branches with validated lift and acceptable leakage risk.",
        "validation_guidance": _research_validation_guidance(),
    }


def _summarize_finding(finding: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": finding.get("id"),
        "dataset_id": finding.get("dataset_id", ""),
        "source": finding.get("source"),
        "source_type": finding.get("source_type"),
        "evidence_level": finding.get("evidence_level"),
        "title": finding.get("title"),
        "url": finding.get("url"),
        "snippet": finding.get("snippet", ""),
        "score": finding.get("score", 0),
        "comment_count": finding.get("comment_count", 0),
        "authors": finding.get("authors", []),
        "venue": finding.get("venue", ""),
        "year": finding.get("year"),
        "citation_count": finding.get("citation_count", 0),
        "stars": finding.get("stars", 0),
        "language": finding.get("language", ""),
        "retrieved_at": finding.get("retrieved_at", ""),
        "accepted_for_okf": finding.get("accepted_for_okf", False),
    }


def _summarize_program(program: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": program.get("id"),
        "dataset_id": program.get("dataset_id", ""),
        "problem_statement": program.get("problem_statement", ""),
        "target_guess": program.get("target_guess", ""),
        "source_summary": program.get("source_summary", {}),
        "hypotheses": program.get("hypotheses", []),
        "methodology_translations": program.get("methodology_translations", []),
        "ablation_plan": program.get("ablation_plan", []),
        "external_data_candidates": program.get("external_data_candidates", []),
        "experiment_branches": program.get("experiment_branches", []),
        "subagent_tasks": program.get("subagent_tasks", []),
        "feedback_loop": program.get("feedback_loop", {}),
        "created_at": program.get("created_at", ""),
        "updated_at": program.get("updated_at", ""),
    }


async def _search_one_source(
    source: str,
    *,
    query: str,
    limit: int,
    timeout: int,
) -> list[dict[str, Any]]:
    source_key = source.strip().lower().replace("-", "_")
    if source_key in {"arxiv", "preprints"}:
        return await search_arxiv(query=query, limit=limit, timeout=timeout)
    if source_key in {"github", "github_repositories", "repos", "repositories"}:
        return await search_github_repositories(
            query=query,
            limit=limit,
            timeout=timeout,
            token=str(_plugin_cfg.get("github_token") or ""),
        )
    if source_key in {"github_issues", "issues"}:
        return await search_github_issues(
            query=query,
            limit=limit,
            timeout=timeout,
            token=str(_plugin_cfg.get("github_token") or ""),
        )
    raise ValueError(f"Unsupported context research source: {source}")
