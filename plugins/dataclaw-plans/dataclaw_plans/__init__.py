"""dataclaw-plans — plan proposal system and MLflow tracking plugin."""

from __future__ import annotations

from dataclaw.plugins.base import (
    DataclawPlugin,
    PluginContext,
    PluginUIManifest,
)
from dataclaw.providers.tool.implementations.python_tool import PythonTool

from dataclaw_plans.tools import propose_plan, update_plan, list_plans, get_plan, accept_gate_risk
from dataclaw_plans.mlflow_tools import query_mlflow_runs
from dataclaw_plans.router import router as plans_router, mlflow_router
from dataclaw_plans.hooks import active_plan_context_hook, planning_reasoning_hook
from dataclaw_plans.gates import GateRiskAcceptanceGuardrail, register_gate_resolver
from dataclaw_plans.decisions import DECISION_GATE, decision_gate_resolver, decision_skill_routing_hook


class PlansPlugin:
    name = "dataclaw-plans"
    depends_on: list[str] = []

    def register(self, ctx: PluginContext) -> None:
        # Register routers
        ctx.include_api_router(plans_router, prefix="/plans", tags=["plans"])
        ctx.include_api_router(mlflow_router, prefix="/mlflow", tags=["mlflow"])

        # Register hooks
        ctx.hooks.register("preToolCallHook", active_plan_context_hook)
        # Runs right before the agent turn: elevates reasoning while drafting a plan.
        ctx.hooks.register("postToolAvailabilityHook", planning_reasoning_hook)
        # Opt-in decision-model routing (decision.routing.*); both are no-ops
        # while their toggle is off.
        ctx.hooks.register("postSkillHook", decision_skill_routing_hook)
        register_gate_resolver(DECISION_GATE, decision_gate_resolver)
        if ctx.guardrail_registry is not None:
            ctx.guardrail_registry.register(GateRiskAcceptanceGuardrail())
        if ctx.session_cleanup_registry is not None:
            from dataclaw_plans.mlflow_tools import delete_session_experiment
            from dataclaw_plans.store import delete_session_records

            def _cleanup_session(session):
                session_id = str(session.get("id") or "")
                return {
                    **delete_session_records(session_id),
                    "mlflow": delete_session_experiment(session_id),
                }

            ctx.session_cleanup_registry.register("plans", _cleanup_session)

        # Register tools
        _tools = [
            ("propose_plan", "Create or revise a plan proposal for user approval", propose_plan, {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Plan name"},
                    "description": {"type": "string", "description": "What the plan will accomplish"},
                    "plan_markdown": {
                        "type": "string",
                        "description": (
                            "Required detailed Markdown review document for plan.md — the substance a lead reviews, "
                            "richer than the compact steps. Do not leave this empty. Write in plain analyst "
                            "prose — no self-praise adjectives, filler transitions, heading-restating bold "
                            "lead-ins, or reflexive three-item lists; every sentence must be checkable or "
                            "actionable. For substantial work, open with a one-line provenance header "
                            "(Provenance: playbooks=<names|none>; hypotheses=<hyp-ids|none recorded>), then cover "
                            "these labeled sections (a quick-answer ask needs only a few lines):\n"
                            "- Objective and what is already known from prior inspection — map each workstream to the "
                            "hypotheses or questions it addresses.\n"
                            "- Method and rationale — the analytical approach chosen for the question type and data "
                            "shape, with the main alternatives considered and rejected (e.g. a causal design vs a "
                            "predictive model).\n"
                            "- Assumptions, data limitations, and threats to validity, with how each is controlled "
                            "(leakage, confounding, selection bias, non-stationarity, multiple comparisons, "
                            "insufficient statistical power).\n"
                            "- Baseline, success threshold, and evaluation protocol appropriate to the data (e.g. "
                            "time-based or group-aware splits to avoid leakage).\n"
                            "- Grouped workstreams, explicit out-of-scope / non-goals, validation and QA checks, "
                            "expected deliverables (a governed HTML report when the analysis is substantial or "
                            "elaborate), risks or open questions, and execution order."
                        ),
                    },
                    "steps": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "plan_step_id": {"type": "string", "description": "Stable plan step id; generated automatically when omitted"},
                                "id": {"type": "string", "description": "Deprecated alias for plan_step_id; accepted for legacy calls"},
                                "name": {"type": "string", "description": "Step name"},
                                "description": {"type": "string", "description": "What this step will do"},
                                "status": {"type": "string", "description": "Step status", "enum": ["not_started", "in_progress", "completed", "error", "blocked"], "default": "not_started"},
                                "summary": {"type": "string", "description": "Step summary", "default": ""},
                                "outputs": {"type": "array", "items": {"type": "string"}, "description": "Output file paths", "default": []},
                                "ready_for_validation": {"type": "boolean", "description": "Whether this step is ready for human validation", "default": False},
                            },
                            "required": ["name", "description"],
                        },
                        "description": "List of steps with name and description",
                    },
                    "context": {"type": "string", "description": "Additional context", "default": ""},
                },
                "required": ["name", "description", "steps", "plan_markdown"],
            }),
            ("update_plan", "Update progress for steps on an existing plan", update_plan, {
                "type": "object",
                "properties": {
                    "proposal_id": {"type": "string", "description": "Plan proposal ID (auto-injected if omitted)"},
                    "step_patches": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "plan_step_id": {"type": "string", "description": "Stable plan step id; when provided, matching is by id only"},
                                "id": {"type": "string", "description": "Deprecated alias for plan_step_id; accepted for legacy calls"},
                                "name": {"type": "string", "description": "Step name to update"},
                                "status": {"type": "string", "description": "New step status", "enum": ["not_started", "in_progress", "completed", "error", "blocked"]},
                                "summary": {"type": "string", "description": "Step summary"},
                                "description": {"type": "string", "description": "Updated description"},
                                "outputs": {"type": "array", "items": {"type": "string"}, "description": "Output file paths"},
                                "note": {"type": "string", "description": "Additional note"},
                                "ready_for_validation": {"type": "boolean", "description": "Set true only after required gates pass or are accepted"},
                            },
                            "anyOf": [
                                {"required": ["plan_step_id"]},
                                {"required": ["id"]},
                                {"required": ["name"]},
                            ],
                        },
                        "description": "Step updates with name and new status/summary",
                    },
                    "status": {"type": "string", "description": "Overall plan status", "enum": ["pending", "approved", "running", "completed", "denied", "changes_requested"]},
                    "summary": {"type": "string", "description": "Progress summary"},
                },
            }),
            ("list_plans", "List plan proposals for the current session", list_plans, {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Max plans to return", "default": 10},
                },
            }),
            ("get_plan", "Get a plan by ID", get_plan, {
                "type": "object",
                "properties": {
                    "proposal_id": {"type": "string", "description": "Plan proposal ID"},
                },
                "required": ["proposal_id"],
            }),
            ("query_mlflow_runs", "Query MLflow experiment runs for the current session", query_mlflow_runs, {
                "type": "object",
                "properties": {},
            }),
            ("accept_gate_risk", "Accept a required validation gate risk with explicit user approval and audit", accept_gate_risk, {
                "type": "object",
                "properties": {
                    "proposal_id": {"type": "string", "description": "Plan proposal ID"},
                    "plan_step_id": {"type": "string", "description": "Stable plan step id"},
                    "gate_name": {"type": "string", "description": "Gate name to accept"},
                    "rationale": {"type": "string", "description": "User-approved rationale for proceeding despite the gate"},
                },
                "required": ["proposal_id", "plan_step_id", "gate_name", "rationale"],
            }),
        ]

        for name, description, fn, parameters in _tools:
            ctx.tool_registry.register_tool(PythonTool(
                name=name, description=description, fn=fn, parameters=parameters,
            ))

    def ui_manifest(self) -> PluginUIManifest:
        return PluginUIManifest(
            id="plans",
            label="Plans",
            icon="",
            pages=[],  # Plans UI is integrated into ChatPage sidebar
        )
