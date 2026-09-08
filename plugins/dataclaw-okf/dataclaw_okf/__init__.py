"""dataclaw-okf - Open Knowledge Format bundles for dataset context."""

from __future__ import annotations

from dataclaw.plugins.base import (
    PluginContext,
    PluginPage,
    PluginUIManifest,
)
from dataclaw.providers.tool.implementations.python_tool import PythonTool

from dataclaw_okf.router import router as okf_router
from dataclaw_okf.tools import (
    okf_export_bundle,
    okf_generate_bundle,
    okf_list_bundles,
    okf_read_bundle,
    okf_search_bundle,
)


class OKFPlugin:
    name = "dataclaw-okf"
    depends_on = ["dataclaw-data"]

    def register(self, ctx: PluginContext) -> None:
        ctx.include_api_router(okf_router, prefix="/okf", tags=["okf"])

        _tools = [
            (
                "okf_generate_bundle",
                "Generate an Open Knowledge Format markdown bundle for a registered dataset",
                okf_generate_bundle,
                {
                    "type": "object",
                    "properties": {
                        "dataset_id": {"type": "string", "description": "Dataset ID"},
                        "force": {
                            "type": "boolean",
                            "description": "Regenerate even when a bundle already exists",
                            "default": False,
                        },
                    },
                    "required": ["dataset_id"],
                },
            ),
            (
                "okf_list_bundles",
                "List generated Open Knowledge Format bundles",
                okf_list_bundles,
                {"type": "object", "properties": {}},
            ),
            (
                "okf_read_bundle",
                "Read one file or a compact index from an Open Knowledge Format bundle",
                okf_read_bundle,
                {
                    "type": "object",
                    "properties": {
                        "bundle_id": {"type": "string", "description": "OKF bundle ID"},
                        "path": {
                            "type": "string",
                            "description": "Optional bundle-relative markdown file path",
                            "default": "",
                        },
                    },
                    "required": ["bundle_id"],
                },
            ),
            (
                "okf_search_bundle",
                "Keyword search markdown files in an Open Knowledge Format bundle",
                okf_search_bundle,
                {
                    "type": "object",
                    "properties": {
                        "bundle_id": {"type": "string", "description": "OKF bundle ID"},
                        "query": {"type": "string", "description": "Keyword search query"},
                        "limit": {
                            "type": "integer",
                            "description": "Maximum matching files to return",
                            "default": 10,
                        },
                    },
                    "required": ["bundle_id", "query"],
                },
            ),
            (
                "okf_export_bundle",
                "Create a portable zip archive for an Open Knowledge Format bundle",
                okf_export_bundle,
                {
                    "type": "object",
                    "properties": {
                        "bundle_id": {"type": "string", "description": "OKF bundle ID"},
                    },
                    "required": ["bundle_id"],
                },
            ),
        ]

        for name, description, fn, parameters in _tools:
            ctx.tool_registry.register_tool(PythonTool(
                name=name,
                description=description,
                fn=fn,
                parameters=parameters,
            ))

    def ui_manifest(self) -> PluginUIManifest:
        return PluginUIManifest(
            id="okf",
            label="OKF",
            icon="file-text",
            pages=[PluginPage(path="/okf", label="OKF")],
        )
