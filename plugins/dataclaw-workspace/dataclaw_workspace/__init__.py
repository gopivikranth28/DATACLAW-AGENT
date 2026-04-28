"""dataclaw-workspace — file I/O and shell execution plugin."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

from dataclaw.plugins.base import (
    DataclawPlugin,
    PluginContext,
    PluginUIManifest,
    PluginConfigField,
)
from dataclaw.providers.tool.implementations.python_tool import PythonTool

from dataclaw_workspace.tools import (
    ws_list_files,
    ws_read_file,
    ws_write_file,
    ws_update_file,
    ws_exec,
    display_image,
    set_project_dir,
)
from dataclaw_workspace.config import WorkspaceConfig, load_config


class WorkspacePlugin:
    name = "dataclaw-workspace"
    depends_on: list[str] = []

    def register(self, ctx: PluginContext) -> None:
        cfg = load_config(ctx.config)

        # Hook: set workspace base to project directory when a project is active
        async def _inject_project_dir(state):
            project_id = state.get("project_id", "")
            logger.info("workspace preToolCallHook: project_id=%r", project_id)
            if project_id:
                try:
                    from dataclaw_projects.registry import get_project
                    project = get_project(project_id)
                    project_dir = project.get("directory", "")
                    logger.info("workspace preToolCallHook: resolved dir=%r", project_dir)
                    if project_dir:
                        set_project_dir(Path(project_dir))
                    else:
                        set_project_dir(None)
                except Exception as e:
                    logger.warning("workspace preToolCallHook: failed to resolve project: %s", e)
                    set_project_dir(None)
            else:
                set_project_dir(None)
            return state

        ctx.hooks.register("preToolCallHook", _inject_project_dir)

        # Register 6 tools
        ctx.tool_registry.register_tool(PythonTool(
            name="ws_list_files",
            description="List files and directories in the workspace",
            fn=lambda **kw: ws_list_files(cfg=cfg, **kw),
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path (relative to workspace root)", "default": "."},
                    "pattern": {"type": "string", "description": "Glob pattern to filter", "default": "*"},
                    "recursive": {"type": "boolean", "description": "Recurse into subdirectories", "default": False},
                },
            },
        ))

        ctx.tool_registry.register_tool(PythonTool(
            name="ws_read_file",
            description="Read the contents of a file in the workspace",
            fn=lambda **kw: ws_read_file(cfg=cfg, **kw),
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path (relative to workspace root)"},
                    "offset": {"type": "integer", "description": "Start line (0-based)", "default": 0},
                    "limit": {"type": "integer", "description": "Max lines to return"},
                },
                "required": ["path"],
            },
        ))

        ctx.tool_registry.register_tool(PythonTool(
            name="ws_write_file",
            description="Write or create a file in the workspace",
            fn=lambda **kw: ws_write_file(cfg=cfg, **kw),
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path (relative to workspace root)"},
                    "content": {"type": "string", "description": "File content to write"},
                },
                "required": ["path", "content"],
            },
        ))

        ctx.tool_registry.register_tool(PythonTool(
            name="ws_update_file",
            description="Find and replace text within a workspace file",
            fn=lambda **kw: ws_update_file(cfg=cfg, **kw),
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                    "old_string": {"type": "string", "description": "Text to find"},
                    "new_string": {"type": "string", "description": "Replacement text"},
                    "replace_all": {"type": "boolean", "description": "Replace all occurrences", "default": False},
                },
                "required": ["path", "old_string", "new_string"],
            },
        ))

        ctx.tool_registry.register_tool(PythonTool(
            name="ws_exec",
            description="Run a shell command in the workspace directory",
            fn=lambda **kw: ws_exec(cfg=cfg, **kw),
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to execute"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds"},
                },
                "required": ["command"],
            },
        ))

        ctx.tool_registry.register_tool(PythonTool(
            name="display_image",
            description="Display an image file to the user in the chat",
            fn=lambda **kw: display_image(cfg=cfg, **kw),
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Image file path"},
                    "caption": {"type": "string", "description": "Caption for the image", "default": ""},
                    "title": {"type": "string", "description": "Display title", "default": ""},
                },
                "required": ["path"],
            },
        ))

    def ui_manifest(self) -> PluginUIManifest:
        return PluginUIManifest(
            id="workspace",
            label="Workspace",
            icon="folder",
            pages=[],  # No dedicated page — tools only
            config_title="Workspace Tools",
            config_fields=[
                PluginConfigField(name="max_read_bytes", field_type="int", label="Max Read Size (bytes)", default=1_048_576),
                PluginConfigField(name="max_write_bytes", field_type="int", label="Max Write Size (bytes)", default=2_097_152),
                PluginConfigField(name="max_list_entries", field_type="int", label="Max List Entries", default=1000),
                PluginConfigField(name="max_exec_output_bytes", field_type="int", label="Max Exec Output (bytes)", default=262_144),
                PluginConfigField(name="exec_timeout_default", field_type="int", label="Default Exec Timeout (sec)", default=120),
                PluginConfigField(name="exec_timeout_max", field_type="int", label="Max Exec Timeout (sec)", default=300),
            ],
        )
