"""dataclaw-artifacts — secure, versioned analytical artifact plugin."""

from __future__ import annotations

from dataclaw.plugins.base import DataclawPlugin, PluginContext, PluginUIManifest
from dataclaw.providers.tool.implementations.python_tool import PythonTool

from dataclaw_artifacts.hooks import artifact_capture_hook, artifact_context_hook
from dataclaw_artifacts.router import router as artifacts_router
from dataclaw_artifacts.tools import (
    delete_artifact,
    export_artifact,
    list_artifacts,
    publish_artifact,
    read_artifact,
    report_note,
)


class ArtifactsPlugin:
    name = "dataclaw-artifacts"
    depends_on: list[str] = []

    def register(self, ctx: PluginContext) -> None:
        ctx.include_api_router(artifacts_router, prefix="/artifacts", tags=["artifacts"])
        ctx.hooks.register("preToolCallHook", artifact_context_hook)
        ctx.hooks.register("postToolCallHook", artifact_capture_hook)

        tools = [
            (
                "publish_artifact",
                (
                    "Publish a self-contained HTML artifact. Structured report-builder HTML "
                    "also requires the current report_publish receipt. Pass artifact_id to "
                    "revise an existing artifact as a new version."
                ),
                publish_artifact,
                {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Human-readable artifact title"},
                        "description": {"type": "string", "description": "One-line summary", "default": ""},
                        "source_path": {"type": "string", "description": "Workspace path of the HTML file to publish"},
                        "html": {"type": "string", "description": "Inline HTML for small artifacts"},
                        "report_receipt_path": {"type": "string", "description": "Current report_publish receipt for structured report HTML"},
                        "artifact_id": {"type": "string", "description": "Existing artifact id to revise"},
                        "label": {"type": "string", "description": "Short version label"},
                        "base_version": {"type": "integer", "description": "Version this update was based on"},
                    },
                    "required": ["title"],
                },
            ),
            (
                "read_artifact",
                "Read clean artifact source for revision.",
                read_artifact,
                {
                    "type": "object",
                    "properties": {
                        "artifact_id": {"type": "string"},
                        "version": {"type": "integer", "description": "Defaults to latest"},
                    },
                    "required": ["artifact_id"],
                },
            ),
            (
                "list_artifacts",
                "List artifacts for the current session.",
                list_artifacts,
                {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "description": "Maximum artifacts to return", "default": 100},
                    },
                },
            ),
            (
                "export_artifact",
                "Create a downloadable, self-contained export URL for an artifact version.",
                export_artifact,
                {
                    "type": "object",
                    "properties": {
                        "artifact_id": {"type": "string"},
                        "version": {"type": "integer", "description": "Defaults to latest"},
                    },
                    "required": ["artifact_id"],
                },
            ),
            (
                "delete_artifact",
                "Delete an artifact and its versions.",
                delete_artifact,
                {
                    "type": "object",
                    "properties": {
                        "artifact_id": {"type": "string"},
                    },
                    "required": ["artifact_id"],
                },
            ),
            (
                "report_note",
                "Append a narrative note to the living report event log.",
                report_note,
                {
                    "type": "object",
                    "properties": {
                        "page": {
                            "type": "string",
                            "description": "Living report page",
                            "enum": ["overview", "analyses", "models", "decisions", "log"],
                        },
                        "markdown": {"type": "string", "description": "Short note in Markdown"},
                        "plan_step_id": {"type": "string", "description": "Stable plan step id"},
                    },
                    "required": ["page", "markdown"],
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
            id="artifacts",
            label="Artifacts",
            icon="file-done",
            pages=[],
        )
