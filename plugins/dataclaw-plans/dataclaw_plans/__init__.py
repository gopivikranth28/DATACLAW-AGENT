"""dataclaw-plans — plan proposal system and MLflow tracking plugin."""

from __future__ import annotations

from dataclaw.plugins.base import (
    DataclawPlugin,
    PluginContext,
    PluginUIManifest,
    PluginConfigField,
)
from dataclaw.providers.tool.implementations.python_tool import PythonTool

from dataclaw_plans.tools import propose_plan, update_plan, list_plans, get_plan
from dataclaw_plans.mlflow_tools import query_mlflow_runs
from dataclaw_plans.router import router as plans_router, mlflow_router
from dataclaw_plans.hooks import active_plan_context_hook


class PlansPlugin:
    name = "dataclaw-plans"
    depends_on: list[str] = []

    def register(self, ctx: PluginContext) -> None:
        # Register routers
        ctx.include_api_router(plans_router, prefix="/plans", tags=["plans"])
        ctx.include_api_router(mlflow_router, prefix="/mlflow", tags=["mlflow"])

        # Register hooks
        ctx.hooks.register("preToolCallHook", active_plan_context_hook)

        # Register tools
        _tools = [
            ("propose_plan", "Create or revise a plan proposal for user approval", propose_plan, {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Plan name"},
                    "description": {"type": "string", "description": "What the plan will accomplish"},
                    "steps": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string", "description": "Step name"},
                                "description": {"type": "string", "description": "What this step will do"},
                                "status": {"type": "string", "description": "Step status", "enum": ["not_started", "in_progress", "completed", "error", "blocked"], "default": "not_started"},
                                "summary": {"type": "string", "description": "Step summary", "default": ""},
                                "outputs": {"type": "array", "items": {"type": "string"}, "description": "Output file paths", "default": []},
                            },
                            "required": ["name", "description"],
                        },
                        "description": "List of steps with name and description",
                    },
                    "context": {"type": "string", "description": "Additional context", "default": ""},
                },
                "required": ["name", "description", "steps"],
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
                                "name": {"type": "string", "description": "Step name to update"},
                                "status": {"type": "string", "description": "New step status", "enum": ["not_started", "in_progress", "completed", "error", "blocked"]},
                                "summary": {"type": "string", "description": "Step summary"},
                                "description": {"type": "string", "description": "Updated description"},
                                "outputs": {"type": "array", "items": {"type": "string"}, "description": "Output file paths"},
                                "note": {"type": "string", "description": "Additional note"},
                            },
                            "required": ["name"],
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
            config_title="Plans & MLflow",
            config_fields=[
                PluginConfigField(
                    name="auto_approve_single_step",
                    field_type="bool",
                    label="Auto-approve single-step plans",
                    default=False,
                ),
            ],
        )
