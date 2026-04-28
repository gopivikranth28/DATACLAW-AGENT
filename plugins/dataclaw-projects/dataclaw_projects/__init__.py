"""dataclaw-projects — project management and subagent CRUD plugin."""

from __future__ import annotations

from dataclaw.plugins.base import (
    DataclawPlugin,
    PluginContext,
    PluginUIManifest,
    PluginPage,
    PluginConfigField,
)
from dataclaw.providers.tool.implementations.python_tool import PythonTool

from dataclaw_projects.router import projects_router, subagents_router
from dataclaw_projects.tools import list_subagents_tool, delegate_to_subagent


class ProjectsPlugin:
    name = "dataclaw-projects"
    depends_on: list[str] = ["dataclaw-workspace"]

    def register(self, ctx: PluginContext) -> None:
        # Register routers
        ctx.include_api_router(projects_router, prefix="/projects", tags=["projects"])
        ctx.include_api_router(subagents_router, prefix="/subagents", tags=["subagents"])

        # Register tools
        ctx.tool_registry.register_tool(PythonTool(
            name="list_subagents",
            description="List available subagent definitions",
            fn=list_subagents_tool,
            parameters={"type": "object", "properties": {}},
        ))
        ctx.tool_registry.register_tool(PythonTool(
            name="delegate_to_subagent",
            description="Delegate a task to a named subagent",
            fn=delegate_to_subagent,
            parameters={
                "type": "object",
                "properties": {
                    "subagent_name": {"type": "string", "description": "Name or ID of the subagent"},
                    "task": {"type": "string", "description": "Task description to delegate"},
                },
                "required": ["subagent_name", "task"],
            },
        ))

    def ui_manifest(self) -> PluginUIManifest:
        return PluginUIManifest(
            id="projects",
            label="Projects",
            icon="folder",
            pages=[
                PluginPage(path="/projects", label="Projects"),
            ],
            config_title="Projects",
            config_fields=[
                PluginConfigField(
                    name="meta_dir_name",
                    field_type="string",
                    label="Metadata Directory Name",
                    description="Hidden directory name inside project directories",
                    default=".dataclaw",
                ),
            ],
        )
