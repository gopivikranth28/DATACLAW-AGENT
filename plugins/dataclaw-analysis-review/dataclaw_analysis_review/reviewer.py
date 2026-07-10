"""Reviewer sub-agent execution — P6 (FR-28/FR-29, D12).

The reviewer runs through the sub-agent provider registry directly (D12), never
through the chat-facing ``delegate_to_subagent`` tool — that keeps per-session
allowlists and conversation persistence out of the loop while sub-agent hooks
and events still fire. It receives a structured context manifest (FR-26) —
never raw artifact HTML — plus a read-only metadata toolset, so it audits
coherence between claims, ledger state, and evidence anchors; it cannot
recompute results (D7). It returns findings as fenced JSON and never mutates
analysis state (FR-29).
"""

from __future__ import annotations

import json
import re
from typing import Any

REVIEWER_DEFINITION_ID = "analysis-reviewer"
REVIEWER_MAX_TURNS = 6
REVIEWER_ALLOWED_TOOLS = [
    "list_eda_hypotheses",
    "list_eda_findings",
    "read_eda_finding",
    "get_plan",
    "list_review_findings",
    "list_artifacts",
]
MANIFEST_MAX_BYTES = 50 * 1024

_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*(\[.*?\])\s*```", re.DOTALL)

# The rubric skill body is rendered in at request time (FR-28); this contract
# is appended so the output shape survives rubric edits.
OUTPUT_CONTRACT = """

## Output contract (mandatory)

Return your findings as a single fenced JSON array and nothing after it:

```json
[
  {
    "category": "unsupported_claim | data_quality_caveat | denominator_grain | reproducibility_gap | misleading_visualization | broken_link | security_export_risk | hypothesis_hygiene",
    "severity": "info | warning | required",
    "claim": "one-sentence statement of the problem",
    "evidence": ["finding/hypothesis/section ids the problem is anchored to"],
    "recommendation": "the concrete fix"
  }
]
```

Return `[]` if nothing is wrong. You are an auditor: never call tools that
mutate state, never propose hypotheses directly (report them as findings — the
main agent records them), and never invent ids that are not in the manifest or
tool results.
"""

# Bound once at plugin registration; the reviewer degrades to checklist-only
# when unbound (tests and headless runs without an app context).
_runtime: dict[str, Any] = {"providers": None, "tool_registry": None}


def bind_runtime(providers: Any, tool_registry: Any) -> None:
    _runtime["providers"] = providers
    _runtime["tool_registry"] = tool_registry


def _provider() -> Any | None:
    providers = _runtime.get("providers")
    registry = getattr(providers, "sub_agent_registry", None)
    if registry is None:
        return None
    return registry.get("llm")


def reviewer_available() -> bool:
    return _provider() is not None


def ensure_reviewer_definition() -> dict[str, Any]:
    """Register (or refresh) the analysis-reviewer definition in dataclaw-projects.

    The system prompt is deliberately NOT stored on the definition — it is
    rendered from the analysis_review skill at request time so rubric edits
    take effect without re-registration (FR-28).
    """
    from dataclaw_projects.subagents import (
        create_subagent_definition,
        get_subagent_definition,
        update_subagent_definition,
    )

    desired = {
        "description": "Read-only analysis reviewer: audits claims vs ledger state and evidence anchors",
        "agent_type": "llm",
        "allowed_tools": REVIEWER_ALLOWED_TOOLS,
        "config": {"max_turns": REVIEWER_MAX_TURNS},
    }
    try:
        definition = get_subagent_definition(REVIEWER_DEFINITION_ID)
    except KeyError:
        return create_subagent_definition(name=REVIEWER_DEFINITION_ID, **desired)
    drifted = (
        definition.get("allowed_tools") != REVIEWER_ALLOWED_TOOLS
        or (definition.get("config") or {}).get("max_turns") != REVIEWER_MAX_TURNS
        or definition.get("agent_type") != "llm"
    )
    if drifted:
        return update_subagent_definition(REVIEWER_DEFINITION_ID, desired)
    return definition


def render_reviewer_system_prompt() -> str:
    """Rubric skill body (installed first, bundled fallback) + output contract."""
    body = ""
    try:
        from dataclaw.storage.skills import read_skill

        installed = read_skill("analysis_review")
        if installed:
            body = str(installed.get("body") or "")
    except Exception:
        body = ""
    if not body.strip():
        try:
            from dataclaw.storage.skill_library import read_library_skill

            library = read_library_skill("analysis_review")
            body = str((library or {}).get("body") or "")
        except Exception:
            body = ""
    if not body.strip():
        body = (
            "You are the analysis reviewer. Audit hypothesis-ledger coverage first, "
            "then claims against evidence anchors, denominators and grain as represented "
            "in the evidence, reproducibility fields, visualization honesty, caveat "
            "completeness, and both validation axes."
        )
    return body.rstrip() + OUTPUT_CONTRACT


def build_reviewer_task(context: dict[str, Any]) -> str:
    """Structured extraction only (FR-26): ledger records + section metadata, capped."""
    manifest = {
        "scope": context.get("scope"),
        "target_id": context.get("target_id"),
        "plan_step": context.get("plan_step"),
        "eda_hypotheses": context.get("eda_hypotheses") or [],
        "eda_findings": context.get("eda_findings") or [],
        "artifact_sections": context.get("artifact_sections") or [],
    }
    encoded = json.dumps(manifest, indent=2, default=str)
    if len(encoded.encode("utf-8")) > MANIFEST_MAX_BYTES:
        truncated = encoded.encode("utf-8")[:MANIFEST_MAX_BYTES].decode("utf-8", errors="ignore")
        encoded = truncated + "\n… (manifest truncated at 50 KiB — use the read-only tools for the rest)"
    return (
        "Review the following analysis state for the scope below. The manifest is "
        "structured extraction from the ledgers and artifact section metadata — raw "
        "artifact content is deliberately withheld. Use your read-only tools to pull "
        "any record you need in full.\n\n"
        f"```json\n{encoded}\n```"
    )


def parse_reviewer_findings(text: str) -> list[dict[str, Any]] | None:
    """Parse the fenced JSON findings array. Returns None on any parse failure."""
    raw = None
    match = _FENCED_JSON_RE.search(text or "")
    if match:
        raw = match.group(1)
    else:
        stripped = (text or "").strip()
        if stripped.startswith("["):
            raw = stripped
    if raw is None:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, list):
        return None
    findings = []
    for item in parsed:
        if not isinstance(item, dict):
            return None
        claim = str(item.get("claim") or "").strip()
        if not claim:
            continue
        findings.append(
            {
                "category": str(item.get("category") or ""),
                "severity": str(item.get("severity") or "warning"),
                "claim": claim,
                "evidence": [str(e) for e in item.get("evidence") or [] if str(e).strip()],
                "recommendation": str(item.get("recommendation") or ""),
            }
        )
    return findings


async def run_reviewer(task: str) -> dict[str, Any]:
    """Run the reviewer via the provider registry. Raises RuntimeError when unavailable."""
    from dataclaw.providers.sub_agent.provider import SubAgentContext

    provider = _provider()
    if provider is None:
        raise RuntimeError("no sub-agent provider registered for agent_type='llm'")
    definition = ensure_reviewer_definition()

    tool_registry = _runtime.get("tool_registry")
    allowed = set(definition.get("allowed_tools") or REVIEWER_ALLOWED_TOOLS)
    tools: list[dict[str, Any]] = []
    tool_callables: dict[str, Any] = {}
    for name, tool in getattr(tool_registry, "_tools", {}).items():
        if name not in allowed:
            continue
        tools.append(tool.definition)
        tool_callables[name] = tool.execute

    config = dict(definition.get("config") or {})
    config["max_turns"] = int(config.get("max_turns") or REVIEWER_MAX_TURNS)
    config["system_prompt"] = render_reviewer_system_prompt()

    context = SubAgentContext(
        definition=definition,
        tools=tools,
        tool_callables=tool_callables,
        config=config,
        sub_agent_hooks=getattr(_runtime.get("providers"), "sub_agent_hooks", None),
    )
    result = await provider.run(task, context=context)
    return {
        "status": result.status,
        "result": result.result,
        "turns_used": result.turns_used,
    }
