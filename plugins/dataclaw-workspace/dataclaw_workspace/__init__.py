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

from dataclaw.config.paths import workspaces_dir
from dataclaw_workspace.tools import (
    ws_list_files,
    ws_read_file,
    ws_write_file,
    ws_update_file,
    ws_exec,
    display_image,
    report_design_report,
    report_review_visuals,
    report_publish,
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
                # An independent chat owns a session workspace; it is not a
                # synthetic project and must never share the default workspace.
                session_id = state.get("session_id", "")
                set_project_dir(workspaces_dir() / session_id if session_id else None)
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
            name="report_design_report",
            description=(
                "Author a cohesive analytical HTML report from completed notebook insights and analysis assets. "
                "Use after EDA/modeling has produced findings. Every report is written end to end by the ledger-backed "
                "creative author: it builds an evidence-and-requirements dossier from the supplied findings and assets, "
                "then the configured LLM writes the complete single-file HTML — original prose, story, layout, CSS, and "
                "bespoke SVG/Canvas visuals — and the host validates source coverage, evidence fidelity, and artifact "
                "safety. A non-empty evidence ledger is required; there is no deterministic or bounded mode."
            ),
            fn=lambda **kw: report_design_report(cfg=cfg, llm=ctx.providers.llm, **kw),
            parameters={
                "type": "object",
                "properties": {
                    "report_goal": {"type": "string", "description": "Decision question or objective the report must answer"},
                    "insights": {"type": "array", "description": "Completed findings/insights with title, summary/detail, evidence, caveat, metrics, ids", "items": {"type": "object"}},
                    "analyses": {"type": "array", "description": "Analysis assets such as Plotly figures, aggregate records, chart specs, tables, cards, metrics, findings, hypotheses, process steps, methods, or evidence. The author may choose the best report treatment. Set required_visual=true only when this exact asset must appear as a reader-facing figure; then supply its existing Plotly figure, a familiar chart mapping (bar/line/scatter/heatmap), or a supported aggregate visual mapping. semantic_role can declare kpi/scorecard, conclusions, hypotheses, process/mechanism, comparison/tradeoffs, lookup/catalog, methodology, data_quality, uncertainty, provenance, timeline, or status. For editorial control, an asset may declare editorial_role='hero', story_priority (lower is earlier), and diagnostic_group/comparison_group for a deliberate paired comparison.", "items": {"type": "object"}, "default": []},
                    "audience": {"type": "string", "description": "Target reader/audience", "default": ""},
                    "requirements": {"type": "object", "description": "Optional report requirements: metrics, filters, methodology, hypotheses, checks, titles, evidence_registry, analysis_review, editorial_archetype, and story_arcs. Explicit story_arcs control the narrative; otherwise the handcrafted compiler groups existing analyses around the supplied report goal without inventing findings. Use editorial_archetype='taxonomy_explorer' for category cards → evidence → explorer, or 'guided_explorer' for the same paced evidence/explorer flow without taxonomy cards. For forecasts, analysis_review can declare mode, baseline, uncertainty, sensitivity, decision_path, outcome_distribution, assumptions, and export_runtime; critique returns durable findings for anything missing.", "default": {}},
                    "report_path": {"type": "string", "description": "Output report HTML path", "default": "report.html"},
                    "storyboard_path": {"type": "string", "description": "Output storyboard JSON path", "default": "report_storyboard.json"},
                    "title": {"type": "string", "description": "Report title", "default": "Analysis Report"},
                    "quality_gate": {"type": "string", "description": "Report-quality behavior: warn and write, fail on required quality regressions, or off", "enum": ["warn", "fail", "off"], "default": "fail"},
                    "visual_author": {"type": "object", "description": "Optional creative-author tuning. Every report is authored by the ledger-backed creative author from a persisted dossier of completed findings, caveats, ledger entries, and bounded aggregate values; source coverage, evidence review, one repair pass, CSP, and artifact safety are enforced, and a non-empty evidence ledger is required. This object only tunes timeout_seconds (default 240, max 900), max_output_chars (default/max 600000), max_dossier_chars (default 300000, max 600000), and max_repair_prompt_chars (default 700000; lower it to match a smaller provider context window). There is no deterministic or bounded mode."},
                },
                "required": ["report_goal", "insights"],
            },
        ))

        ctx.tool_registry.register_tool(PythonTool(
            name="report_review_visuals",
            description=(
                "Optionally capture desktop full-page and key-section browser screenshots for a structured report, then record a named human or vision-review decision "
                "bound to the exact HTML hash. Use only when a report explicitly requires visual approval."
            ),
            fn=lambda **kw: report_review_visuals(cfg=cfg, **kw),
            parameters={
                "type": "object",
                "properties": {
                    "report_path": {"type": "string", "description": "Structured report HTML path"},
                    "storyboard_path": {"type": "string", "description": "Storyboard JSON created for the report"},
                    "reviewer": {"type": "string", "description": "Named human reviewer or declared vision-review system"},
                    "decision": {"type": "string", "enum": ["approved", "rework_required"], "description": "Reviewer decision after inspecting the screenshots"},
                    "notes": {"type": "string", "description": "Concise review rationale, including any resolved visual concerns"},
                },
                "required": ["report_path", "storyboard_path", "reviewer", "decision", "notes"],
            },
        ))

        ctx.tool_registry.register_tool(PythonTool(
            name="report_publish",
            description=(
                "Publish a storyboard-backed report after re-running the current report rubric at "
                "fail severity. Writes a durable publish receipt; DOCX export is optional. "
                "The receipt binds the exact rendered HTML and analytical-review contract for artifact publication. "
                "When visual review is required, an approved report_review_visuals record for the exact HTML is also required. "
                "Use after report_design_report."
            ),
            fn=lambda **kw: report_publish(cfg=cfg, **kw),
            parameters={
                "type": "object",
                "properties": {
                    "report_path": {"type": "string", "description": "Structured report HTML path"},
                    "storyboard_path": {"type": "string", "description": "Storyboard JSON created for the report"},
                    "receipt_path": {"type": "string", "description": "Publish receipt JSON path (defaults beside the report)"},
                    "export_docx": {"type": "boolean", "description": "Attempt DOCX export and record its outcome. Disabled by default; reports with advanced visuals return unsupported until validated static snapshots exist because DOCX conversion cannot execute inline SVG JavaScript.", "default": False},
                    "require_visual_review": {"type": "boolean", "description": "Optional explicit opt-in to a named approved report_review_visuals record, bound to passed Playwright desktop full-page and key-section screenshot artifacts. When omitted, uses requirements.publication.require_visual_review, which also defaults off."},
                },
                "required": ["report_path", "storyboard_path"],
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
