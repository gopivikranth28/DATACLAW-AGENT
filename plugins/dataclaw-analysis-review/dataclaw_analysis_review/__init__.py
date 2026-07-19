"""dataclaw-analysis-review - deterministic review lifecycle plugin."""

from __future__ import annotations

from dataclaw.plugins.base import PluginContext, PluginUIManifest
from dataclaw.providers.tool.implementations.python_tool import PythonTool

from dataclaw_analysis_review import tools
from dataclaw_analysis_review.hooks import (
    auto_review_completed_steps_hook,
    review_context_hook,
    surface_unreviewed_publish_hook,
)
from dataclaw_analysis_review.router import router as review_router


class AnalysisReviewPlugin:
    name = "dataclaw-analysis-review"
    depends_on = ["dataclaw-plans", "dataclaw-eda", "dataclaw-artifacts", "dataclaw-projects"]

    def register(self, ctx: PluginContext) -> None:
        ctx.include_api_router(review_router, prefix="/analysis-review", tags=["analysis-review"])
        ctx.hooks.register("preToolCallHook", review_context_hook)
        ctx.hooks.register("postToolCallHook", auto_review_completed_steps_hook)
        ctx.hooks.register("postToolCallHook", surface_unreviewed_publish_hook)

        try:
            from dataclaw_plans.gates import register_gate_resolver

            register_gate_resolver("analysis_review", tools.review_gate_resolver)
        except Exception:
            pass

        # P6: bind the sub-agent runtime (D12 — direct provider use) and make
        # sure the reviewer definition exists. Definition registration is
        # idempotent; the rubric prompt is rendered at request time (FR-28).
        try:
            from dataclaw_analysis_review.reviewer import bind_runtime, ensure_reviewer_definition

            bind_runtime(getattr(ctx, "providers", None), ctx.tool_registry)
            ensure_reviewer_definition()
        except Exception:
            pass
        if ctx.guardrail_registry is not None:
            ctx.guardrail_registry.register(tools.ReviewFindingAcceptanceGuardrail())

        for name, description, fn, parameters in _tool_defs():
            ctx.tool_registry.register_tool(
                PythonTool(name=name, description=description, fn=fn, parameters=parameters)
            )

    def ui_manifest(self) -> PluginUIManifest:
        return PluginUIManifest(id="analysis-review", label="Review", icon="", pages=[])


def _tool_defs():
    scope_schema = {
        "type": "string",
        "enum": ["plan_step", "artifact", "living_report", "session"],
    }
    severity_schema = {
        "type": "string",
        "enum": ["info", "warning", "required"],
        "default": "warning",
    }
    status_schema = {
        "type": "string",
        "enum": ["open", "resolved", "accepted_with_rationale", "dismissed_as_not_applicable"],
    }
    category_schema = {
        "type": "string",
        "enum": [
            "unsupported_claim",
            "data_quality_caveat",
            "denominator_grain",
            "query_risk",
            "modeling_comparability",
            "reproducibility_gap",
            "misleading_visualization",
            "broken_link",
            "security_export_risk",
            "hypothesis_hygiene",
        ],
    }
    context_props = {
        "proposal_id": {"type": "string", "description": "Plan proposal id; injected from active plan when omitted"},
        "session_id": {"type": "string", "description": "Session id; injected when omitted", "default": "default"},
    }
    return [
        (
            "request_analysis_review",
            "Run deterministic analysis review checks for a plan step, artifact, living report, or session",
            tools.request_analysis_review,
            {
                "type": "object",
                "properties": {
                    "scope": scope_schema,
                    "target_id": {"type": "string", "description": "Reviewed object id; for plan_step this is plan_step_id"},
                    "plan_step_id": {"type": "string", "description": "Stable plan step id alias for plan_step scope"},
                    "severity_floor": severity_schema,
                    "require_subagent": {
                        "type": "boolean",
                        "description": "Keep the gate unknown if only checklist review runs for this scope",
                        "default": False,
                    },
                    **context_props,
                },
                "required": ["scope"],
            },
        ),
        (
            "list_review_findings",
            "List analysis review findings by scope, target, status, severity, or category",
            tools.list_review_findings,
            {
                "type": "object",
                "properties": {
                    "scope": scope_schema,
                    "target_id": {"type": "string"},
                    "status": status_schema,
                    "severity": severity_schema,
                    "category": category_schema,
                    "session_id": context_props["session_id"],
                },
            },
        ),
        (
            "resolve_review_finding",
            "Resolve, accept, or dismiss a review finding with an append-only audit event",
            tools.resolve_review_finding,
            {
                "type": "object",
                "properties": {
                    "finding_id": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": ["resolved", "accepted_with_rationale", "dismissed_as_not_applicable"],
                    },
                    "rationale": {"type": "string", "default": ""},
                    "evidence_link": {"type": "string"},
                    "session_id": context_props["session_id"],
                },
                "required": ["finding_id", "status"],
            },
        ),
        (
            "get_review_gate",
            "Return the current analysis-review gate for a reviewed scope",
            tools.get_review_gate,
            {
                "type": "object",
                "properties": {
                    "scope": scope_schema,
                    "target_id": {"type": "string"},
                    "plan_step_id": {"type": "string"},
                    "session_id": context_props["session_id"],
                },
                "required": ["scope"],
            },
        ),
        (
            "list_review_runs",
            "List analysis review runs for the current session",
            tools.list_review_runs,
            {
                "type": "object",
                "properties": {
                    "scope": scope_schema,
                    "target_id": {"type": "string"},
                    "status": {"type": "string"},
                    "limit": {"type": "integer", "default": 50},
                    "session_id": context_props["session_id"],
                },
            },
        ),
    ]
