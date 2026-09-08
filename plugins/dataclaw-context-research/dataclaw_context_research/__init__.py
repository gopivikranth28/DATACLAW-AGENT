"""dataclaw-context-research - cited external context for open-world problems."""

from __future__ import annotations

from dataclaw.plugins.base import (
    PluginConfigField,
    PluginContext,
    PluginUIManifest,
)
from dataclaw.providers.tool.implementations.python_tool import PythonTool

from dataclaw_context_research.hooks import (
    external_research_first_plan_hook,
    external_research_first_prompt_hook,
)
from dataclaw_context_research.router import router as context_router
from dataclaw_context_research.tools import (
    context_research_build_program,
    context_research_generate_queries,
    context_research_list_findings,
    context_research_list_programs,
    context_research_run_parallel_experiments,
    context_research_save_program_to_okf,
    context_research_save_to_okf,
    context_research_search_sources,
    context_research_summarize_findings,
    set_delegate_to_subagent,
    set_llm_provider,
    set_plugin_cfg,
)


class ContextResearchPlugin:
    name = "dataclaw-context-research"
    depends_on = ["dataclaw-data", "dataclaw-okf", "dataclaw-projects"]

    def register(self, ctx: PluginContext) -> None:
        set_plugin_cfg(ctx.config.plugins.get("context-research", {}))
        set_llm_provider(getattr(ctx.providers, "llm", None))
        delegate_tool = getattr(ctx.tool_registry, "_tools", {}).get("delegate_to_subagent")
        if delegate_tool is not None:
            set_delegate_to_subagent(delegate_tool.execute)
        ctx.include_api_router(context_router, prefix="/context-research", tags=["context-research"])
        ctx.hooks.register("postSystemPromptHook", external_research_first_prompt_hook)
        ctx.hooks.register("preToolCallHook", external_research_first_plan_hook)

        tools = [
            (
                "context_research_generate_queries",
                "Generate open-world research queries from a dataset schema and/or problem statement",
                context_research_generate_queries,
                {
                    "type": "object",
                    "properties": {
                        "dataset_id": {"type": "string", "description": "Optional Dataclaw dataset ID", "default": ""},
                        "problem_statement": {"type": "string", "description": "Optional problem statement or analysis goal", "default": ""},
                        "limit": {"type": "integer", "description": "Maximum queries to return", "default": 8},
                    },
                },
            ),
            (
                "context_research_search_sources",
                "Search arXiv, GitHub repositories, and GitHub issues for cited technical context",
                context_research_search_sources,
                {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                        "sources": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": ["arxiv", "github_repositories", "github_issues"],
                            },
                            "description": "Sources to search",
                            "default": ["arxiv", "github_repositories", "github_issues"],
                        },
                        "dataset_id": {"type": "string", "description": "Optional dataset ID to attach findings to", "default": ""},
                        "problem_statement": {"type": "string", "description": "Optional problem statement", "default": ""},
                        "limit": {"type": "integer", "description": "Maximum results per source", "default": 8},
                    },
                    "required": ["query"],
                },
            ),
            (
                "context_research_list_findings",
                "List saved external context findings with evidence labels and citations",
                context_research_list_findings,
                {
                    "type": "object",
                    "properties": {
                        "dataset_id": {"type": "string", "description": "Optional dataset filter", "default": ""},
                        "limit": {"type": "integer", "description": "Maximum findings to return", "default": 20},
                    },
                },
            ),
            (
                "context_research_summarize_findings",
                "Summarize saved external context findings by theme and evidence level",
                context_research_summarize_findings,
                {
                    "type": "object",
                    "properties": {
                        "dataset_id": {"type": "string", "description": "Optional dataset filter", "default": ""},
                        "finding_ids": {"type": "array", "items": {"type": "string"}, "description": "Optional finding IDs"},
                    },
                },
            ),
            (
                "context_research_save_to_okf",
                "Save curated external context findings into an OKF bundle as notes/external_context.md",
                context_research_save_to_okf,
                {
                    "type": "object",
                    "properties": {
                        "bundle_id": {"type": "string", "description": "OKF bundle ID"},
                        "dataset_id": {"type": "string", "description": "Optional dataset filter", "default": ""},
                        "finding_ids": {"type": "array", "items": {"type": "string"}, "description": "Optional finding IDs"},
                    },
                    "required": ["bundle_id"],
                },
            ),
            (
                "context_research_build_program",
                "Build a deep research program with methodology translations, ablation plans, feedback loops, experiment branches, and subagent tasks",
                context_research_build_program,
                {
                    "type": "object",
                    "properties": {
                        "dataset_id": {"type": "string", "description": "Optional dataset ID", "default": ""},
                        "problem_statement": {"type": "string", "description": "Problem statement or analysis objective", "default": ""},
                        "finding_ids": {"type": "array", "items": {"type": "string"}, "description": "Optional finding IDs"},
                        "max_hypotheses": {"type": "integer", "description": "Maximum hypotheses to generate", "default": 8},
                    },
                },
            ),
            (
                "context_research_list_programs",
                "List saved deep research programs",
                context_research_list_programs,
                {
                    "type": "object",
                    "properties": {
                        "dataset_id": {"type": "string", "description": "Optional dataset filter", "default": ""},
                        "limit": {"type": "integer", "description": "Maximum programs to return", "default": 20},
                    },
                },
            ),
            (
                "context_research_save_program_to_okf",
                "Save a deep research program into an OKF bundle as notes/research_program.md",
                context_research_save_program_to_okf,
                {
                    "type": "object",
                    "properties": {
                        "bundle_id": {"type": "string", "description": "OKF bundle ID"},
                        "program_id": {"type": "string", "description": "Research program ID"},
                    },
                    "required": ["bundle_id", "program_id"],
                },
            ),
            (
                "context_research_run_parallel_experiments",
                "Dispatch research-program methodology ablation branches to configured Dataclaw subagents in parallel",
                context_research_run_parallel_experiments,
                {
                    "type": "object",
                    "properties": {
                        "program_id": {"type": "string", "description": "Research program ID"},
                        "subagent_names": {"type": "array", "items": {"type": "string"}, "description": "Subagent IDs/names to dispatch tasks to"},
                        "max_tasks": {"type": "integer", "description": "Maximum experiment tasks to dispatch", "default": 4},
                    },
                    "required": ["program_id", "subagent_names"],
                },
            ),
        ]

        for name, description, fn, parameters in tools:
            ctx.tool_registry.register_tool(PythonTool(
                name=name,
                description=description,
                fn=fn,
                parameters=parameters,
            ))

    def ui_manifest(self) -> PluginUIManifest:
        return PluginUIManifest(
            id="context-research",
            label="Context Research",
            icon="search",
            pages=[],
            config_title="Context Research",
            config_fields=[
                PluginConfigField(
                    name="request_timeout",
                    field_type="int",
                    label="Request Timeout",
                    description="External request timeout in seconds",
                    default=12,
                ),
                PluginConfigField(
                    name="max_results",
                    field_type="int",
                    label="Max Results",
                    description="Maximum external results per search",
                    default=15,
                ),
                PluginConfigField(
                    name="github_token",
                    field_type="string",
                    label="GitHub Token",
                    description="Optional token for GitHub search rate limits",
                    default="",
                ),
            ],
        )
