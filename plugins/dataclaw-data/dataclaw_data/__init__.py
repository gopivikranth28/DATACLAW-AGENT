"""dataclaw-data — data registry and DuckDB querying plugin."""

from __future__ import annotations

from dataclaw.plugins.base import (
    DataclawPlugin,
    PluginContext,
    PluginUIManifest,
    PluginPage,
    PluginConfigField,
)
from dataclaw.providers.tool.implementations.python_tool import PythonTool

from dataclaw_data.tools import (
    data_list_datasets,
    data_preview_data,
    data_profile_dataset,
    data_describe_column,
    data_query_data,
    data_get_docs,
    set_allowed_dataset_ids,
)
from dataclaw_data.router import router as data_router


class DataPlugin:
    name = "dataclaw-data"
    depends_on: list[str] = []

    def register(self, ctx: PluginContext) -> None:
        # Register API router
        ctx.include_api_router(data_router, prefix="/data", tags=["data"])

        # Hook: apply session-level dataset filter before tool calls
        async def _apply_dataset_filter(state):
            session_id = state.get("session_id", "")
            if session_id:
                try:
                    from dataclaw.storage.sessions import get_session
                    session_data = await get_session(session_id)
                    if session_data:
                        dataset_ids = session_data.get("datasetIds")
                        set_allowed_dataset_ids(dataset_ids)
                    else:
                        set_allowed_dataset_ids(None)
                except Exception:
                    set_allowed_dataset_ids(None)
            else:
                set_allowed_dataset_ids(None)
            return state

        ctx.hooks.register("preToolCallHook", _apply_dataset_filter)

        # Register tools
        ctx.tool_registry.register_tool(PythonTool(
            name="data_list_datasets",
            description="List all registered datasets with table and column metadata",
            fn=data_list_datasets,
            parameters={"type": "object", "properties": {}},
        ))

        ctx.tool_registry.register_tool(PythonTool(
            name="data_preview_data",
            description="Preview rows from a dataset table",
            fn=data_preview_data,
            parameters={
                "type": "object",
                "properties": {
                    "dataset_id": {"type": "string", "description": "Dataset ID"},
                    "table_name": {"type": "string", "description": "Table name"},
                    "n_rows": {"type": "integer", "description": "Number of rows to preview", "default": 50},
                },
                "required": ["dataset_id", "table_name"],
            },
        ))

        ctx.tool_registry.register_tool(PythonTool(
            name="data_profile_dataset",
            description="Profile a dataset table — row counts, null rates, unique counts, descriptive stats",
            fn=data_profile_dataset,
            parameters={
                "type": "object",
                "properties": {
                    "dataset_id": {"type": "string", "description": "Dataset ID"},
                    "table_name": {"type": "string", "description": "Table name"},
                },
                "required": ["dataset_id", "table_name"],
            },
        ))

        ctx.tool_registry.register_tool(PythonTool(
            name="data_describe_column",
            description="Detailed column analysis — top values, stats, histogram",
            fn=data_describe_column,
            parameters={
                "type": "object",
                "properties": {
                    "dataset_id": {"type": "string", "description": "Dataset ID"},
                    "table_name": {"type": "string", "description": "Table name"},
                    "column_name": {"type": "string", "description": "Column name"},
                },
                "required": ["dataset_id", "table_name", "column_name"],
            },
        ))

        ctx.tool_registry.register_tool(PythonTool(
            name="data_query_data",
            description="Run read-only DuckDB SQL against a dataset",
            fn=data_query_data,
            parameters={
                "type": "object",
                "properties": {
                    "dataset_id": {"type": "string", "description": "Dataset ID"},
                    "sql": {"type": "string", "description": "Read-only SQL query (SELECT, WITH, SHOW, DESCRIBE, SUMMARIZE)"},
                },
                "required": ["dataset_id", "sql"],
            },
        ))

        ctx.tool_registry.register_tool(PythonTool(
            name="data_get_docs",
            description="Get documentation for the dataclaw_data notebook package",
            fn=data_get_docs,
            parameters={"type": "object", "properties": {}},
        ))

    def ui_manifest(self) -> PluginUIManifest:
        return PluginUIManifest(
            id="data",
            label="Data",
            icon="database",
            pages=[PluginPage(path="/data", label="Datasets")],
            config_title="Data Registry",
            config_fields=[
                PluginConfigField(
                    name="max_query_rows",
                    field_type="int",
                    label="Max Query Rows",
                    description="Maximum rows returned by data_query_data",
                    default=500,
                ),
            ],
        )
