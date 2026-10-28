"""Research programs: hypotheses, enrichment candidates, and experiment branches."""

from __future__ import annotations

from collections import Counter
from typing import Any

from dataclaw_data.registry import find_dataset


def build_research_program(
    *,
    dataset_id: str = "",
    problem_statement: str = "",
    findings: list[dict[str, Any]] | None = None,
    max_hypotheses: int = 8,
) -> dict[str, Any]:
    findings = findings or []
    dataset = find_dataset(dataset_id) if dataset_id else {}
    schema_terms = _schema_terms(dataset)
    domain_terms = _domain_terms(problem_statement, findings, schema_terms)
    target = _target_guess(problem_statement, schema_terms)

    hypotheses = _hypotheses(
        problem_statement=problem_statement,
        findings=findings,
        schema_terms=schema_terms,
        target=target,
        limit=max_hypotheses,
    )
    external_data = _external_data_candidates(problem_statement, findings, domain_terms)
    methodology_translations = _methodology_translations(hypotheses)
    ablation_plan = _ablation_plan(methodology_translations)
    feedback_loop = _feedback_loop(ablation_plan)
    experiment_branches = _experiment_branches(
        hypotheses,
        external_data,
        dataset_id=dataset_id,
        ablation_plan=ablation_plan,
    )
    return {
        "dataset_id": dataset_id,
        "problem_statement": problem_statement,
        "domain_terms": domain_terms,
        "target_guess": target,
        "source_summary": _source_summary(findings),
        "hypotheses": hypotheses,
        "methodology_translations": methodology_translations,
        "ablation_plan": ablation_plan,
        "external_data_candidates": external_data,
        "experiment_branches": experiment_branches,
        "subagent_tasks": _subagent_tasks(experiment_branches),
        "feedback_loop": feedback_loop,
        "caveats": [
            "External data must be license-compatible and time-aligned with the prediction/analysis target.",
            "Community/forum findings are weak signals; use them for hypotheses, not final claims.",
            "External research can improve methodology even when no external rows or joins are used.",
            "Every promoted methodology should have an ablation result against the baseline.",
            "Later modeling steps should be changed by validation feedback; weak research ideas should be rejected, tuned, or narrowed.",
        ],
    }


def program_markdown(program: dict[str, Any]) -> str:
    return f"""---
title: "Research Program"
kind: "research_program"
tags:
  - "context-research"
  - "hypotheses"
  - "experiments"
---

# Research Program

## Objective

{program.get("problem_statement") or "No explicit problem statement was provided."}

## Source Summary

{_dict_lines(program.get("source_summary", {}))}

## Hypotheses

{_hypothesis_lines(program.get("hypotheses", []))}

## Methodology Translations

{_methodology_lines(program.get("methodology_translations", []))}

## Ablation Plan

{_ablation_lines(program.get("ablation_plan", []))}

## External Data Candidates

{_external_lines(program.get("external_data_candidates", []))}

## Experiment Branches

{_branch_lines(program.get("experiment_branches", []))}

## Subagent Tasks

{_task_lines(program.get("subagent_tasks", []))}

## Feedback Loop

{_dict_lines(program.get("feedback_loop", {}))}

## Caveats

{chr(10).join(f"- {c}" for c in program.get("caveats", []))}
"""


def _schema_terms(dataset: dict[str, Any]) -> list[str]:
    terms = []
    for table in dataset.get("tables") or []:
        terms.append(str(table.get("name", "")))
        for column in table.get("column_details") or []:
            terms.append(str(column.get("name", "")))
    return [t for t in terms if t]


def _domain_terms(problem_statement: str, findings: list[dict[str, Any]], schema_terms: list[str]) -> list[str]:
    tokens = Counter()
    for text in [problem_statement, *schema_terms, *(f.get("title", "") for f in findings), *(f.get("snippet", "") for f in findings)]:
        for token in _tokens(str(text)):
            tokens[token] += 1
    return [term for term, _ in tokens.most_common(20)]


def _target_guess(problem_statement: str, schema_terms: list[str]) -> str:
    joined = " ".join([problem_statement, *schema_terms]).lower()
    for candidate in ("saleprice", "churn", "default", "fraud", "readmission", "score", "rating", "performance", "distress", "risk"):
        if candidate in joined:
            return candidate
    return ""


def _hypotheses(
    *,
    problem_statement: str,
    findings: list[dict[str, Any]],
    schema_terms: list[str],
    target: str,
    limit: int,
) -> list[dict[str, Any]]:
    base = []
    if findings:
        for finding in findings[: max(1, limit)]:
            title = finding.get("title", "external finding")
            source = finding.get("source", "external")
            evidence = finding.get("evidence_level", "unverified")
            source_attribution = _source_attribution(finding)
            problem_match = _problem_match_description(
                finding=finding,
                problem_statement=problem_statement,
                schema_terms=schema_terms,
                target=target,
            )
            base.append({
                "id": f"h{len(base) + 1}",
                "statement": f"Insights from '{title}' may improve the solution if adapted to this dataset.",
                "rationale": f"Source: {source}, evidence: {evidence}. Use as a testable hypothesis, not an assumption.",
                "source_attribution": source_attribution,
                "problem_match": problem_match,
                "chat_summary": (
                    f"{source_attribution['label']} suggests a testable direction for this problem. "
                    f"{problem_match}"
                ),
                "signals_to_test": _signals_from_text(f"{title} {finding.get('snippet', '')}", schema_terms),
                "expected_effect": "Potential lift over provided-data-only baseline if the idea captures missing domain structure.",
                "risk": "May not transfer; validate with ablation and leakage checks.",
                "source_ids": [finding.get("id", "")],
            })
            if len(base) >= limit:
                break
    if len(base) < limit:
        base.extend([
            {
                "id": f"h{len(base) + 1}",
                "statement": "Temporal/order-aware features may improve performance if observations have sequence or recency structure.",
                "rationale": "Many real-world problems encode behavior over time even when raw rows look static.",
                "problem_match": "This is a general fallback hypothesis derived from the problem shape and schema, not a specific external source.",
                "source_attribution": {},
                "signals_to_test": ["lag/rolling aggregates", "session order", "recency"],
                "expected_effect": "Better generalization for behavior or forecasting tasks.",
                "risk": "High leakage risk if future information is included.",
                "source_ids": [],
            },
            {
                "id": f"h{len(base) + 2}",
                "statement": "External domain covariates may explain variance missing from the provided dataset.",
                "rationale": "Provided data is often an incomplete view of the real-world system.",
                "problem_match": "This is a general fallback hypothesis derived from the problem shape and schema, not a specific external source.",
                "source_attribution": {},
                "signals_to_test": ["public statistics", "calendar effects", "geographic or market context"],
                "expected_effect": "Improved robustness on scenarios underrepresented in training data.",
                "risk": "External joins can introduce coverage bias or stale context.",
                "source_ids": [],
            },
        ])
    if target:
        base[0]["target_context"] = target
    return base[:limit]


def _external_data_candidates(problem_statement: str, findings: list[dict[str, Any]], domain_terms: list[str]) -> list[dict[str, Any]]:
    candidates = [
        {
            "name": "Official/public domain statistics",
            "search_query": f"{' '.join(domain_terms[:5])} public dataset statistics",
            "use_case": "Add macro/domain context not present in the uploaded dataset.",
            "validation": "Join coverage, temporal alignment, license, and ablation lift.",
            "risk": "Mismatch between public aggregates and row-level entities.",
        },
        {
            "name": "Calendar and event context",
            "search_query": f"{' '.join(domain_terms[:5])} calendar events holidays seasonality",
            "use_case": "Capture seasonality, interventions, events, or policy shifts.",
            "validation": "Time-split validation and leakage audit.",
            "risk": "Can leak future events if not cut by prediction date.",
        },
    ]
    for finding in findings[:4]:
        candidates.append({
            "name": f"Source-linked enrichment: {finding.get('title', 'external source')}",
            "search_query": f"{finding.get('title', '')} dataset code features",
            "use_case": "Investigate whether this cited source exposes datasets, benchmarks, or feature recipes.",
            "validation": "Source license, reproducibility, feature ablation, and train/test coverage.",
            "risk": "Paper/repo may not provide reusable data or may be domain-mismatched.",
            "source_id": finding.get("id", ""),
            "url": finding.get("url", ""),
        })
    return candidates


def _methodology_translations(hypotheses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    translations = []
    for hypothesis in hypotheses[:6]:
        signals = hypothesis.get("signals_to_test", [])
        translations.append({
            "id": f"m-{hypothesis['id']}",
            "hypothesis_id": hypothesis["id"],
            "research_idea": hypothesis["statement"],
            "source_attribution": hypothesis.get("source_attribution", {}),
            "problem_match": hypothesis.get("problem_match", ""),
            "dataset_safe_translation": (
                "Translate the research idea into features, preprocessing, validation choices, "
                "or model constraints that can be derived from the provided dataset before trying external joins."
            ),
            "candidate_methods": signals or ["domain-inspired feature engineering"],
            "baseline_comparison": "Compare with the same model family on raw/provided-data-only features where feasible.",
            "feedback_action": (
                "Keep, tune, combine, or reject this methodology based on its ablation delta, "
                "leakage checks, and robustness diagnostics."
            ),
        })
    return translations


def _ablation_plan(methodologies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    plan = [
        {
            "id": "abl-baseline",
            "name": "Provided-data-only baseline",
            "methodology_id": "",
            "variant": "baseline",
            "purpose": "Establish the metric before any research-guided methodology is added.",
            "required_metrics": ["validation_metric", "fold_metrics", "prediction_distribution"],
            "decision_use": "Reference point for every methodology delta.",
        }
    ]
    for methodology in methodologies:
        plan.append({
            "id": f"abl-{methodology['id']}",
            "name": f"Add methodology from {methodology['hypothesis_id']}",
            "methodology_id": methodology["id"],
            "variant": "single_methodology_ablation",
            "purpose": "Isolate whether this research-derived method improves the baseline.",
            "required_metrics": [
                "baseline_validation_metric",
                "candidate_validation_metric",
                "delta_vs_baseline",
                "leakage_check",
                "robustness_check",
            ],
            "decision_use": "Promote only if the metric improves and diagnostics do not deteriorate.",
        })
    plan.append({
        "id": "abl-final-selected",
        "name": "Final selected research-guided model",
        "methodology_id": "",
        "variant": "selected_combination",
        "purpose": "Combine only methodologies that survived single-methodology ablations or have a documented tuning rationale.",
        "required_metrics": [
            "baseline_validation_metric",
            "final_validation_metric",
            "delta_vs_baseline",
            "included_methodologies",
            "rejected_methodologies",
        ],
        "decision_use": "Document how earlier validation feedback changed the final model.",
    })
    return plan


def _feedback_loop(ablation_plan: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "baseline_required": True,
        "compare_against": "provided-data-only baseline",
        "ablation_required": True,
        "ablation_plan_ids": [item["id"] for item in ablation_plan],
        "metrics_to_track": [
            "validation metric improvement",
            "delta versus provided-data-only baseline",
            "generalization gap",
            "data leakage risk",
            "external-data coverage when external joins are attempted",
            "feature stability",
            "prediction distribution shift",
            "fairness/bias diagnostics where applicable",
        ],
        "required_result_fields": [
            "research_methodology",
            "dataset_safe_translation",
            "baseline_metric",
            "candidate_metric",
            "delta_vs_baseline",
            "diagnostics",
            "decision",
            "next_model_adjustment",
        ],
        "decision_values": ["promote", "tune", "combine", "reject"],
        "iteration_rule": (
            "After each ablation, update the next model branch from the result: promote methods with validated lift, "
            "tune methods with mixed diagnostics, combine complementary winners, and reject methods that fail metric, leakage, "
            "or robustness checks."
        ),
        "reporting_rule": (
            "Final reporting must include a table that links each research methodology to its implementation, metric delta, "
            "feedback decision, and the concrete adjustment made to later modeling."
        ),
    }


def _experiment_branches(
    hypotheses: list[dict[str, Any]],
    external_data: list[dict[str, Any]],
    *,
    dataset_id: str,
    ablation_plan: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    branches = []
    ablation_by_methodology = {
        item.get("methodology_id"): item
        for item in ablation_plan
        if item.get("methodology_id")
    }
    for hypothesis in hypotheses[:6]:
        methodology_id = f"m-{hypothesis['id']}"
        ablation = ablation_by_methodology.get(methodology_id, {})
        branches.append({
            "id": f"exp-{hypothesis['id']}",
            "name": hypothesis["statement"][:80],
            "dataset_id": dataset_id,
            "hypothesis_id": hypothesis["id"],
            "methodology_id": methodology_id,
            "ablation_id": ablation.get("id", ""),
            "steps": [
                "Reproduce provided-data-only baseline and record metric.",
                "Translate the research methodology into provided-data-safe features, preprocessing, validation, or model constraints.",
                "Run validation with leakage-safe split.",
                "Compare against baseline with a single-methodology ablation.",
                "Use the result to choose the next adjustment: promote, tune, combine, or reject.",
                "Report methodology, implementation, baseline metric, candidate metric, delta, diagnostics, decision, and next model adjustment.",
            ],
            "success_criteria": "Improves validation metric while passing leakage and robustness checks.",
        })
    if external_data:
        branches.append({
            "id": "exp-external-data-audit",
            "name": "External data discovery and join feasibility audit",
            "dataset_id": dataset_id,
            "hypothesis_id": "",
            "methodology_id": "external-data-audit",
            "ablation_id": "",
            "steps": [
                "Inspect candidate external sources for accessible datasets or reproducible feature recipes.",
                "Check licenses, coverage, join keys, and time alignment.",
                "Prototype one safe join/enrichment only if feasibility is high.",
                "Run ablation against baseline if a safe join is feasible.",
                "If joins are infeasible, convert source ideas into provided-data-safe methodologies and record the rejection reason.",
            ],
            "success_criteria": "Finds at least one license-compatible enrichment with measurable lift or useful negative evidence.",
        })
    return branches


def _subagent_tasks(branches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "task_id": f"task-{branch['id']}",
            "branch_id": branch["id"],
            "title": branch["name"],
            "recommended_subagent": "analysis-experimenter",
            "task": (
                f"Run experiment branch {branch['id']}: {branch['name']}. "
                f"Steps: {'; '.join(branch['steps'])}. "
                "Return a structured feedback row with research_methodology, dataset_safe_translation, baseline_metric, "
                "candidate_metric, delta_vs_baseline, diagnostics, decision (promote/tune/combine/reject), "
                "next_model_adjustment, artifacts, and leakage risks."
            ),
        }
        for branch in branches
    ]


def _source_summary(findings: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "findings": len(findings),
        "by_source_type": dict(Counter(f.get("source_type", "unknown") for f in findings)),
        "by_evidence": dict(Counter(f.get("evidence_level", "unverified") for f in findings)),
    }


def _source_attribution(finding: dict[str, Any]) -> dict[str, Any]:
    title = str(finding.get("title") or "External finding").strip()
    source = str(finding.get("source") or "external").strip()
    evidence = str(finding.get("evidence_level") or "unverified").strip()
    source_type = str(finding.get("source_type") or "source").strip()
    year = finding.get("year")
    label_parts = [title, f"{source}/{source_type}", f"evidence: {evidence}"]
    if year:
        label_parts.insert(1, str(year))
    return {
        "finding_id": finding.get("id", ""),
        "title": title,
        "url": finding.get("url", ""),
        "source": source,
        "source_type": source_type,
        "evidence_level": evidence,
        "label": " | ".join(label_parts),
        "short_description": _compact_sentence(str(finding.get("snippet") or ""), limit=220),
    }


def _problem_match_description(
    *,
    finding: dict[str, Any],
    problem_statement: str,
    schema_terms: list[str],
    target: str,
) -> str:
    text = f"{finding.get('title', '')} {finding.get('snippet', '')}".lower()
    problem_terms = _tokens(problem_statement)
    matched_problem_terms = [term for term in problem_terms if term in text][:5]
    matched_schema_terms = [term for term in schema_terms if term and term.lower() in text][:5]
    parts = []
    if target and target.lower() in text:
        parts.append(f"it references the target/context `{target}`")
    if matched_problem_terms:
        parts.append(f"it overlaps with problem terms `{matched_problem_terms}`")
    if matched_schema_terms:
        parts.append(f"it maps to dataset/schema signals `{matched_schema_terms}`")
    if not parts:
        source_type = finding.get("source_type", "source")
        evidence = finding.get("evidence_level", "unverified")
        parts.append(f"it is a {evidence} {source_type} result from the external context search for this problem")
    return "Matched because " + "; ".join(parts) + "."


def _signals_from_text(text: str, schema_terms: list[str]) -> list[str]:
    lower = text.lower()
    hits = [term for term in schema_terms if term and term.lower() in lower]
    generic = [t for t in ("feature engineering", "sequence", "fairness", "missing data", "tree model", "external data") if t in lower]
    return (hits + generic)[:8] or ["domain-inspired feature set", "baseline comparison"]


def _tokens(text: str) -> list[str]:
    import re

    stop = {"with", "from", "this", "that", "data", "model", "using", "based", "and", "the", "for"}
    return [t for t in re.split(r"[^a-zA-Z0-9]+", text.lower()) if len(t) > 3 and t not in stop]


def _compact_sentence(text: str, *, limit: int = 220) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: max(0, limit - 3)].rstrip() + "..."


def _dict_lines(values: dict[str, Any]) -> str:
    return "\n".join(f"- {k}: `{v}`" for k, v in values.items()) or "- None"


def _hypothesis_lines(items: list[dict[str, Any]]) -> str:
    lines = []
    for item in items:
        lines.append(f"### {item.get('id')}: {item.get('statement')}")
        lines.append(f"- Rationale: {item.get('rationale')}")
        source = item.get("source_attribution") or {}
        if source:
            url = source.get("url") or ""
            title = source.get("title") or "External source"
            source_label = f"[{title}]({url})" if url else title
            lines.append(
                f"- Source: {source_label} ({source.get('source')}/{source.get('source_type')}, "
                f"evidence: {source.get('evidence_level')})"
            )
            if source.get("short_description"):
                lines.append(f"- Source context: {source.get('short_description')}")
        if item.get("problem_match"):
            lines.append(f"- Problem match: {item.get('problem_match')}")
        lines.append(f"- Signals to test: `{item.get('signals_to_test', [])}`")
        lines.append(f"- Expected effect: {item.get('expected_effect')}")
        lines.append(f"- Risk: {item.get('risk')}\n")
    return "\n".join(lines) or "- No hypotheses generated."


def _external_lines(items: list[dict[str, Any]]) -> str:
    return "\n".join(
        f"- **{item.get('name')}**: {item.get('use_case')} Query: `{item.get('search_query')}` Risk: {item.get('risk')}"
        for item in items
    ) or "- No external data candidates generated."


def _methodology_lines(items: list[dict[str, Any]]) -> str:
    lines = []
    for item in items:
        lines.append(f"### {item.get('id')}: {item.get('research_idea')}")
        source = item.get("source_attribution") or {}
        if source:
            lines.append(f"- Source: {source.get('label')}")
        if item.get("problem_match"):
            lines.append(f"- Problem match: {item.get('problem_match')}")
        lines.append(f"- Dataset-safe translation: {item.get('dataset_safe_translation')}")
        lines.append(f"- Candidate methods: `{item.get('candidate_methods', [])}`")
        lines.append(f"- Baseline comparison: {item.get('baseline_comparison')}")
        lines.append(f"- Feedback action: {item.get('feedback_action')}\n")
    return "\n".join(lines) or "- No methodology translations generated."


def _ablation_lines(items: list[dict[str, Any]]) -> str:
    lines = []
    for item in items:
        lines.append(f"### {item.get('id')}: {item.get('name')}")
        lines.append(f"- Variant: {item.get('variant')}")
        lines.append(f"- Purpose: {item.get('purpose')}")
        lines.append(f"- Required metrics: `{item.get('required_metrics', [])}`")
        lines.append(f"- Decision use: {item.get('decision_use')}\n")
    return "\n".join(lines) or "- No ablation plan generated."


def _branch_lines(items: list[dict[str, Any]]) -> str:
    return "\n".join(
        f"- **{item.get('id')}**: {item.get('name')} Ablation: `{item.get('ablation_id', '')}` Success: {item.get('success_criteria')}"
        for item in items
    ) or "- No experiment branches generated."


def _task_lines(items: list[dict[str, Any]]) -> str:
    return "\n".join(f"- **{item.get('task_id')}**: {item.get('task')}" for item in items) or "- No subagent tasks generated."
