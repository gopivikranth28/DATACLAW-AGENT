"""Dataclaw Kaggle plugin — competitions, datasets, and submissions."""

from __future__ import annotations

from dataclaw.plugins.base import (
    DataclawPlugin,
    PluginConfigField,
    PluginContext,
    PluginPage,
    PluginUIManifest,
)
from dataclaw.providers.tool.implementations.python_tool import PythonTool

from dataclaw_kaggle.tools import (
    kaggle_list_competitions,
    kaggle_competition_details,
    kaggle_leaderboard,
    kaggle_download_competition,
    kaggle_search_datasets,
    kaggle_download_dataset,
    kaggle_submit,
    kaggle_submissions,
    set_plugin_cfg,
)
from dataclaw_kaggle.router import router as kaggle_router
from dataclaw_kaggle.router import set_plugin_cfg as set_router_cfg


class KagglePlugin:
    name = "dataclaw-kaggle"
    depends_on: list[str] = ["dataclaw-data"]

    def register(self, ctx: PluginContext) -> None:
        # Pass plugin config to tools and router
        plugin_cfg = ctx.config.plugins.get("kaggle", {})
        set_plugin_cfg(plugin_cfg)
        set_router_cfg(plugin_cfg)

        # Register API router
        ctx.include_api_router(kaggle_router, prefix="/kaggle", tags=["kaggle"])

        # Register tools
        ctx.tool_registry.register_tool(PythonTool(
            name="kaggle_list_competitions",
            description="List or search Kaggle competitions. Returns competition name, URL, deadline, reward, and team count.",
            fn=kaggle_list_competitions,
            parameters={
                "type": "object",
                "properties": {
                    "search": {"type": "string", "description": "Search term to filter competitions"},
                    "category": {
                        "type": "string",
                        "description": "Competition category",
                        "enum": ["all", "featured", "research", "gettingStarted", "playground", "analytics"],
                    },
                    "sort_by": {
                        "type": "string",
                        "description": "Sort order",
                        "enum": ["latestDeadline", "recentlyCreated", "numberOfTeams", "prize"],
                        "default": "latestDeadline",
                    },
                    "page": {"type": "integer", "description": "Page number", "default": 1},
                },
            },
        ))

        ctx.tool_registry.register_tool(PythonTool(
            name="kaggle_competition_details",
            description="Get detailed information about a specific Kaggle competition including data files, evaluation metric, and deadlines.",
            fn=kaggle_competition_details,
            parameters={
                "type": "object",
                "properties": {
                    "competition": {"type": "string", "description": "Competition slug (e.g. 'titanic')"},
                },
                "required": ["competition"],
            },
        ))

        ctx.tool_registry.register_tool(PythonTool(
            name="kaggle_leaderboard",
            description="View the leaderboard for a Kaggle competition. Returns top entries with team name, score, and rank.",
            fn=kaggle_leaderboard,
            parameters={
                "type": "object",
                "properties": {
                    "competition": {"type": "string", "description": "Competition slug"},
                    "page": {"type": "integer", "description": "Page number", "default": 1},
                },
                "required": ["competition"],
            },
        ))

        ctx.tool_registry.register_tool(PythonTool(
            name="kaggle_download_competition",
            description="Download data files for a Kaggle competition. Files are saved locally and registered as a dataclaw dataset. You must accept competition rules on kaggle.com before downloading.",
            fn=kaggle_download_competition,
            parameters={
                "type": "object",
                "properties": {
                    "competition": {"type": "string", "description": "Competition slug"},
                    "file_name": {"type": "string", "description": "Download a specific file instead of all files"},
                    "force": {"type": "boolean", "description": "Re-download even if already present", "default": False},
                },
                "required": ["competition"],
            },
        ))

        ctx.tool_registry.register_tool(PythonTool(
            name="kaggle_search_datasets",
            description="Search Kaggle datasets by keyword. Returns dataset ref, title, size, download count, and last updated date.",
            fn=kaggle_search_datasets,
            parameters={
                "type": "object",
                "properties": {
                    "search": {"type": "string", "description": "Search keyword"},
                    "sort_by": {
                        "type": "string",
                        "description": "Sort order",
                        "enum": ["hottest", "votes", "updated", "active", "published"],
                        "default": "hottest",
                    },
                    "file_type": {
                        "type": "string",
                        "description": "Filter by file type",
                        "enum": ["all", "csv", "sqlite", "json", "bigQuery"],
                    },
                    "page": {"type": "integer", "description": "Page number", "default": 1},
                },
                "required": ["search"],
            },
        ))

        ctx.tool_registry.register_tool(PythonTool(
            name="kaggle_download_dataset",
            description="Download a Kaggle dataset by its ref (owner/dataset-name). Files are saved locally and registered as a dataclaw dataset.",
            fn=kaggle_download_dataset,
            parameters={
                "type": "object",
                "properties": {
                    "dataset": {"type": "string", "description": "Dataset ref in owner/dataset-name format"},
                    "force": {"type": "boolean", "description": "Re-download even if already present", "default": False},
                },
                "required": ["dataset"],
            },
        ))

        ctx.tool_registry.register_tool(PythonTool(
            name="kaggle_submit",
            description="Submit a prediction file to a Kaggle competition. The file must exist locally.",
            fn=kaggle_submit,
            parameters={
                "type": "object",
                "properties": {
                    "competition": {"type": "string", "description": "Competition slug"},
                    "file_path": {"type": "string", "description": "Path to the submission file"},
                    "message": {"type": "string", "description": "Submission description message"},
                },
                "required": ["competition", "file_path", "message"],
            },
        ))

        ctx.tool_registry.register_tool(PythonTool(
            name="kaggle_submissions",
            description="List your submissions for a Kaggle competition with public/private scores, status, and ranking.",
            fn=kaggle_submissions,
            parameters={
                "type": "object",
                "properties": {
                    "competition": {"type": "string", "description": "Competition slug"},
                },
                "required": ["competition"],
            },
        ))

        # Default-disabled. Kaggle tools talk to a third-party API and
        # download large competition archives — opt-in is the safer
        # default. The user can toggle them on from the Tools page; the
        # seeded_plugins flag makes this a one-shot, so re-enables stick.
        ctx.tool_registry.seed_plugin_defaults(
            self.name,
            default_disabled=[
                "kaggle_list_competitions",
                "kaggle_competition_details",
                "kaggle_leaderboard",
                "kaggle_download_competition",
                "kaggle_search_datasets",
                "kaggle_download_dataset",
                "kaggle_submit",
                "kaggle_submissions",
            ],
        )

    def ui_manifest(self) -> PluginUIManifest:
        return PluginUIManifest(
            id="kaggle",
            label="Kaggle",
            icon="trophy",
            pages=[PluginPage(path="/kaggle", label="Kaggle")],
            config_title="Kaggle Integration",
            config_fields=[
                PluginConfigField(
                    name="kaggle_username",
                    field_type="string",
                    label="Kaggle Username",
                    description="Your Kaggle username (or set KAGGLE_USERNAME env var)",
                    default="",
                ),
                PluginConfigField(
                    name="kaggle_key",
                    field_type="string",
                    label="Kaggle API Key",
                    description="Your Kaggle API key (or set KAGGLE_KEY env var)",
                    default="",
                ),
                PluginConfigField(
                    name="download_dir",
                    field_type="string",
                    label="Download Directory",
                    description="Directory for downloaded Kaggle files (default: plugin data dir)",
                    default="",
                ),
                PluginConfigField(
                    name="auto_register_datasets",
                    field_type="bool",
                    label="Auto-Register Downloads",
                    description="Automatically register downloaded Kaggle data as dataclaw datasets",
                    default=True,
                ),
            ],
        )
