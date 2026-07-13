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
    build_report,
    report_design_report,
    report_publish,
    report_add_section,
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

        # Register workspace tools.
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

        ctx.tool_registry.register_tool(PythonTool(
            name="build_report",
            description="Normalize raw HTML into a typed, storyboard-backed report while preserving the source HTML beside it. The output includes a storyboard, critique record, and quality result; provide either raw HTML or a workspace HTML path.",
            fn=lambda **kw: build_report(cfg=cfg, **kw),
            parameters={
                "type": "object",
                "properties": {
                    "html": {"type": "string", "description": "Raw HTML string for the report"},
                    "html_path": {"type": "string", "description": "Path to an HTML file in workspace"},
                    "output_path": {"type": "string", "description": "Output filename (relative to workspace)", "default": "report.html"},
                    "storyboard_path": {"type": "string", "description": "Output storyboard JSON path (defaults beside the report)"},
                    "report_goal": {"type": "string", "description": "Decision question to preserve while rebuilding the source"},
                    "title": {"type": "string", "description": "Optional report title override"},
                    "audience": {"type": "string", "description": "Target reader/audience"},
                    "quality_gate": {"type": "string", "description": "Report-quality behavior after normalization", "enum": ["warn", "fail", "off"], "default": "warn"},
                },
            },
        ))

        ctx.tool_registry.register_tool(PythonTool(
            name="report_design_report",
            description=(
                "Design a cohesive analytical HTML report from completed notebook insights and analysis assets. "
                "Use after EDA/modeling has produced findings: this tool storyboards the report, chooses section "
                "layouts and interactive controls, writes a storyboard JSON, and renders the final HTML in one pass."
            ),
            fn=lambda **kw: report_design_report(cfg=cfg, **kw),
            parameters={
                "type": "object",
                "properties": {
                    "report_goal": {"type": "string", "description": "Decision question or objective the report must answer"},
                    "insights": {"type": "array", "description": "Completed findings/insights with title, summary/detail, evidence, caveat, metrics, ids", "items": {"type": "object"}},
                    "analyses": {"type": "array", "description": "Analysis assets such as Plotly figures, aggregate records+chart specs, tables, cards, methods, or evidence", "items": {"type": "object"}, "default": []},
                    "audience": {"type": "string", "description": "Target reader/audience", "default": ""},
                    "requirements": {"type": "object", "description": "Optional report requirements: metrics, filters, methodology, hypotheses, checks, titles", "default": {}},
                    "report_path": {"type": "string", "description": "Output report HTML path", "default": "report.html"},
                    "storyboard_path": {"type": "string", "description": "Output storyboard JSON path", "default": "report_storyboard.json"},
                    "title": {"type": "string", "description": "Report title", "default": "Analysis Report"},
                    "quality_gate": {"type": "string", "description": "Report-quality behavior: warn and write, fail on required quality regressions, or off", "enum": ["warn", "fail", "off"], "default": "fail"},
                },
                "required": ["report_goal", "insights"],
            },
        ))

        ctx.tool_registry.register_tool(PythonTool(
            name="report_publish",
            description=(
                "Publish a storyboard-backed report after re-running the current report rubric at "
                "fail severity. Writes a durable publish receipt and records the DOCX export result. "
                "Use after report_design_report or a structured build_report result; "
                "low-confidence preserved source must be redesigned before publishing."
            ),
            fn=lambda **kw: report_publish(cfg=cfg, **kw),
            parameters={
                "type": "object",
                "properties": {
                    "report_path": {"type": "string", "description": "Structured report HTML path"},
                    "storyboard_path": {"type": "string", "description": "Storyboard JSON created for the report"},
                    "receipt_path": {"type": "string", "description": "Publish receipt JSON path (defaults beside the report)"},
                    "export_docx": {"type": "boolean", "description": "Attempt DOCX export and record its outcome", "default": True},
                },
                "required": ["report_path", "storyboard_path"],
            },
        ))

        ctx.tool_registry.register_tool(PythonTool(
            name="report_add_section",
            description=(
                "Append a low-level designed section to a live HTML report. Prefer report_design_report "
                "for final cohesive reports after insights are complete. Supported sections: header, "
                "metric_row, insight_grid, "
                "explanation, comparison, checklist, narrative_band, methodology_block, "
                "evidence_rail, ledger_timeline, chart_interpretation, hypothesis_ledger, "
                "evidence_trace, filterable_chart, interactive_table, selector_panel, "
                "chart_table_explorer, entity_card_grid, chart, table, findings, callout, or text."
            ),
            fn=lambda **kw: report_add_section(cfg=cfg, **kw),
            parameters={
                "type": "object",
                "properties": {
                    "section_type": {
                        "type": "string",
                        "description": "Section type",
                        "enum": [
                            "header",
                            "metric_row",
                            "insight_grid",
                            "explanation",
                            "comparison",
                            "checklist",
                            "narrative_band",
                            "methodology_block",
                            "evidence_rail",
                            "ledger_timeline",
                            "chart_interpretation",
                            "hypothesis_ledger",
                            "evidence_trace",
                            "filterable_chart",
                            "interactive_table",
                            "selector_panel",
                            "chart_table_explorer",
                            "entity_card_grid",
                            "chart",
                            "findings",
                            "callout",
                            "text",
                            "table",
                        ],
                    },
                    "data": {"type": "object", "description": "Section data payload"},
                    "report_path": {"type": "string", "description": "Output report path", "default": "report.html"},
                    "title": {"type": "string", "description": "Report title, used when creating a new report", "default": "Analysis Report"},
                    "quality_gate": {"type": "string", "description": "Report-quality behavior: warn and write, fail on required quality regressions, or off", "enum": ["warn", "fail", "off"], "default": "warn"},
                },
                "required": ["section_type", "data"],
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
