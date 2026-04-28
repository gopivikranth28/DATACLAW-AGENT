"""dataclaw-notebooks — Jupyter notebook management plugin."""

from __future__ import annotations

from pathlib import Path

from dataclaw.config.paths import plugin_data_dir, workspaces_dir
from dataclaw.plugins.base import (
    DataclawPlugin,
    PluginContext,
    PluginUIManifest,
    PluginPage,
    PluginConfigField,
)
from dataclaw.providers.tool.implementations.python_tool import PythonTool

from dataclaw_notebooks.manager import NotebookManager
from dataclaw_notebooks.router import router as notebooks_router
from dataclaw_notebooks import tools


class NotebooksPlugin:
    name = "dataclaw-notebooks"
    depends_on: list[str] = ["dataclaw-workspace"]

    def register(self, ctx: PluginContext) -> None:
        plugin_cfg = ctx.config.plugins.get("notebooks", {})
        notebooks_dir = workspaces_dir()
        notebooks_dir.mkdir(parents=True, exist_ok=True)
        kernel_python = plugin_cfg.get("kernel_python")

        mgr = NotebookManager(notebooks_dir=notebooks_dir, kernel_python=kernel_python)
        tools.set_manager(mgr)

        # Store on app state for lifespan cleanup
        ctx.app.state.notebook_manager = mgr

        # Hook: inject session and project context into notebook manager before tool calls
        async def _inject_session_context(state):
            session_id = state.get("session_id", "")
            if session_id:
                mgr.set_session_context(session_id)

            # Set project directory so notebooks are created in the project folder
            project_id = state.get("project_id", "")
            if project_id:
                try:
                    from dataclaw_projects.registry import get_project
                    project = get_project(project_id)
                    project_dir = project.get("directory", "")
                    if project_dir:
                        mgr.project_dir = Path(project_dir)
                        mgr.project_id = project_id
                    else:
                        mgr.project_dir = None
                except Exception:
                    mgr.project_dir = None
            else:
                mgr.project_dir = None

            return state

        ctx.hooks.register("preToolCallHook", _inject_session_context)

        # Register router
        ctx.include_api_router(notebooks_router, prefix="/notebooks", tags=["notebooks"])

        # Register tools
        _tool_defs = [
            ("open_notebook", "Open or create a notebook and start its kernel", tools.open_notebook, {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Notebook file path (.ipynb)"},
                    "name": {"type": "string", "description": "Display name (defaults to filename)"},
                    "create": {"type": "boolean", "description": "Create if it doesn't exist", "default": False},
                },
                "required": ["path"],
            }),
            ("close_notebook", "Save and close a notebook, shutting down its kernel", tools.close_notebook, {
                "type": "object",
                "properties": {"name": {"type": "string", "description": "Notebook name"}},
                "required": ["name"],
            }),
            ("list_notebooks", "List all open notebooks", tools.list_notebooks, {
                "type": "object", "properties": {},
            }),
            ("read_notebook", "Read a paginated list of cells from the current notebook", tools.read_notebook, {
                "type": "object",
                "properties": {
                    "start": {"type": "integer", "description": "Start cell index", "default": 0},
                    "limit": {"type": "integer", "description": "Max cells to return", "default": 20},
                },
            }),
            ("read_cell", "Read a single cell with full source and outputs", tools.read_cell, {
                "type": "object",
                "properties": {"cell_index": {"type": "integer", "description": "Cell index"}},
                "required": ["cell_index"],
            }),
            ("insert_cell", "Insert a new cell at the given index", tools.insert_cell, {
                "type": "object",
                "properties": {
                    "index": {"type": "integer", "description": "Insert position (-1 to append)", "default": -1},
                    "cell_type": {"type": "string", "description": "code or markdown", "default": "code"},
                    "source": {"type": "string", "description": "Cell source code", "default": ""},
                },
            }),
            ("edit_cell", "Replace the entire source of a cell", tools.edit_cell, {
                "type": "object",
                "properties": {
                    "cell_index": {"type": "integer", "description": "Cell index"},
                    "new_source": {"type": "string", "description": "New cell source"},
                },
                "required": ["cell_index", "new_source"],
            }),
            ("edit_cell_source", "Find and replace within a cell's source", tools.edit_cell_source, {
                "type": "object",
                "properties": {
                    "cell_index": {"type": "integer", "description": "Cell index"},
                    "old_string": {"type": "string", "description": "Text to find"},
                    "new_string": {"type": "string", "description": "Replacement text"},
                    "replace_all": {"type": "boolean", "description": "Replace all occurrences", "default": False},
                },
                "required": ["cell_index", "old_string", "new_string"],
            }),
            ("move_cell", "Move a cell from one position to another", tools.move_cell, {
                "type": "object",
                "properties": {
                    "source_index": {"type": "integer", "description": "Source cell index"},
                    "target_index": {"type": "integer", "description": "Target cell index"},
                },
                "required": ["source_index", "target_index"],
            }),
            ("delete_cells", "Delete one or more cells by index", tools.delete_cells, {
                "type": "object",
                "properties": {
                    "cell_indices": {"type": "array", "items": {"type": "integer"}, "description": "Cell indices to delete"},
                },
                "required": ["cell_indices"],
            }),
            ("execute_cell", "Execute a code cell in the current notebook's kernel", tools.execute_cell, {
                "type": "object",
                "properties": {
                    "cell_index": {"type": "integer", "description": "Cell index to execute"},
                    "timeout": {"type": "integer", "description": "Execution timeout in seconds", "default": 120},
                },
                "required": ["cell_index"],
            }),
            ("execute_code", "Execute arbitrary code in the current notebook's kernel (not saved)", tools.execute_code, {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Python code to execute"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 120},
                },
                "required": ["code"],
            }),
            ("display_cell_output", "Display a cell's output", tools.display_cell_output, {
                "type": "object",
                "properties": {
                    "cell_index": {"type": "integer", "description": "Cell index"},
                    "caption": {"type": "string", "description": "Caption", "default": ""},
                },
                "required": ["cell_index"],
            }),
        ]

        for name, description, fn, parameters in _tool_defs:
            ctx.tool_registry.register_tool(PythonTool(
                name=name, description=description, fn=fn, parameters=parameters,
            ))

    def ui_manifest(self) -> PluginUIManifest:
        return PluginUIManifest(
            id="notebooks",
            label="Notebooks",
            icon="book",
            pages=[PluginPage(path="/notebooks", label="Notebooks")],
            config_title="Notebooks",
            config_fields=[
                PluginConfigField(
                    name="kernel_python",
                    field_type="string",
                    label="Kernel Python Path",
                    description="Path to Python binary for notebook kernels (leave empty for default)",
                ),
            ],
        )
