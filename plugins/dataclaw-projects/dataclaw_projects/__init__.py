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
from dataclaw_projects.tools import (
    list_subagents_tool,
    make_delegate_to_subagent,
    set_allowed_subagent_ids,
)


class ProjectsPlugin:
    name = "dataclaw-projects"
    depends_on: list[str] = ["dataclaw-workspace"]

    def register(self, ctx: PluginContext) -> None:
        # Register routers
        ctx.include_api_router(projects_router, prefix="/projects", tags=["projects"])
        ctx.include_api_router(subagents_router, prefix="/subagents", tags=["subagents"])

        # Hook: apply session-level subagent filter before each tool call so
        # `list_subagents` and `delegate_to_subagent` only see what the
        # session is configured to expose. Mirrors the dataset filter in
        # dataclaw-data; the same `preToolCallHook` chain runs for every
        # backend (openclaw, native CLI, etc.), so this is backend-agnostic.
        async def _apply_subagent_filter(state):
            session_id = state.get("session_id", "")
            if not session_id:
                set_allowed_subagent_ids(None)
                return state
            try:
                from dataclaw.storage.sessions import get_session
                session_data = await get_session(session_id)
            except Exception:
                set_allowed_subagent_ids(None)
                return state
            if session_data:
                set_allowed_subagent_ids(session_data.get("subagentIds"))
            else:
                set_allowed_subagent_ids(None)
            return state

        ctx.hooks.register("preToolCallHook", _apply_subagent_filter)

        # Register tools
        ctx.tool_registry.register_tool(PythonTool(
            name="list_subagents",
            description="List available subagent definitions",
            fn=list_subagents_tool,
            parameters={"type": "object", "properties": {}},
        ))
        delegate_fn = make_delegate_to_subagent(ctx.providers, ctx.tool_registry)
        ctx.tool_registry.register_tool(PythonTool(
            name="delegate_to_subagent",
            description="Delegate a task to a named subagent. Omit conversation_id to start a fresh conversation. Pass a conversation_id from a previous result to continue that conversation with full context.",
            fn=delegate_fn,
            parameters={
                "type": "object",
                "properties": {
                    "subagent_name": {"type": "string", "description": "Name or ID of the subagent to delegate to"},
                    "task": {"type": "string", "description": "The task or follow-up message for the subagent"},
                    "conversation_id": {"type": "string", "description": "Optional. Pass the conversation_id from a previous delegation result to continue that conversation. The subagent will have full context of prior exchanges. Omit to start a new conversation."},
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
