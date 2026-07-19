"""Tests for openclaw_install_service.

Covers the pure helpers directly and the install_plugin_atomic orchestrator
with mocked subprocess + httpx so no real CLI/gateway is needed.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

import dataclaw.config.paths as paths
import dataclaw_openclaw.openclaw_install_service as install_service
from dataclaw_openclaw.openclaw_install_service import (
    PLUGIN_MANIFEST_FILENAME,
    build_batch_entries,
    install_plugin_atomic,
    read_plugin_manifest,
    resolve_channel_section_values,
    resolve_plugin_entry_config_values,
    validate_report_tool_manifest,
    write_plugin_manifest_contracts_tools,
)


def _write_manifest(tmp_path: Path, manifest: dict) -> Path:
    """Helper: write a manifest into tmp_path/<plugin-id>/openclaw.plugin.json."""
    plugin_dir = tmp_path / manifest["id"]
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / PLUGIN_MANIFEST_FILENAME).write_text(json.dumps(manifest))
    return plugin_dir


@pytest.fixture(autouse=True)
def isolate_openclaw_install_state(tmp_path: Path, monkeypatch):
    """Never let installer tests overwrite the user's real sync snapshot."""
    monkeypatch.setattr(paths, "DATACLAW_HOME", tmp_path / "dataclaw-home")


async def _empty_async_events(*_args, **_kwargs):
    if False:  # pragma: no cover - keeps this an async generator
        yield {}


# ── Pure helpers ────────────────────────────────────────────────────────────


def test_read_plugin_manifest_happy_path(tmp_path: Path) -> None:
    plugin_dir = _write_manifest(tmp_path, {"id": "dataclaw", "envVars": ["FOO"]})

    manifest = read_plugin_manifest(plugin_dir)

    assert manifest["id"] == "dataclaw"
    assert manifest["envVars"] == ["FOO"]


def test_read_plugin_manifest_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="not found"):
        read_plugin_manifest(tmp_path / "nonexistent")


def test_resolve_channel_section_values_uses_defaults_when_config_missing() -> None:
    resolved = resolve_channel_section_values(openclaw_cfg={})

    # Channel section now only carries the auth/transport pair. token has no
    # default → skipped; dataclawApiUrl has a default → lands.
    assert resolved == {"dataclawApiUrl": "http://localhost:8000"}


def test_resolve_channel_section_values_picks_up_dataclaw_cfg() -> None:
    resolved = resolve_channel_section_values(openclaw_cfg={"token": "abc"})

    assert resolved == {"token": "abc", "dataclawApiUrl": "http://localhost:8000"}


def test_resolve_plugin_entry_config_values_uses_defaults_when_config_missing() -> None:
    resolved = resolve_plugin_entry_config_values(openclaw_cfg={})

    # Tools-only knobs live under plugins.entries.<id>.config — both have
    # defaults so both land (toolsOptional default False is written explicitly).
    assert resolved == {"toolsPrefix": "dataclaw_", "toolsOptional": False}


def test_resolve_plugin_entry_config_values_picks_up_dataclaw_cfg() -> None:
    resolved = resolve_plugin_entry_config_values(
        openclaw_cfg={"tools_prefix": "dc_", "tools_optional": True},
    )

    assert resolved == {"toolsPrefix": "dc_", "toolsOptional": True}


def test_report_tool_manifest_requires_the_governed_publish_parameters() -> None:
    issues = validate_report_tool_manifest([
        {"name": "report_design_report", "parameters": {"type": "object", "properties": {}}},
        {"name": "report_publish", "parameters": {"type": "object", "properties": {}}},
        {"name": "publish_artifact", "parameters": {"type": "object", "properties": {}}},
    ])

    assert "report_design_report missing properties: design_passes, visual_author" in issues
    assert "report_publish missing properties: require_visual_review" in issues
    assert "publish_artifact missing properties: report_receipt_path" in issues
    assert "report_publish is present but report_review_visuals is unavailable" in issues


def test_report_tool_manifest_accepts_a_complete_governed_publish_flow() -> None:
    tools = [
        {"name": "report_design_report", "parameters": {"properties": {"design_passes": {}, "visual_author": {}}}},
        {"name": "report_review_visuals", "parameters": {"properties": {}}},
        {"name": "report_publish", "parameters": {"properties": {"require_visual_review": {}}}},
        {"name": "publish_artifact", "parameters": {"properties": {"report_receipt_path": {}}}},
    ]

    assert validate_report_tool_manifest(tools) == []


def test_report_tool_manifest_requires_a_live_registry_snapshot() -> None:
    assert validate_report_tool_manifest(None) == ["live Dataclaw tool registry is unavailable"]


def test_build_batch_entries_appends_to_tools_allow_when_no_profile() -> None:
    entries = build_batch_entries(
        channel_values={"dataclawApiUrl": "http://x"},
        also_allow_addition="dataclaw",
        current_also_allow=["existing-also"],  # left untouched in no-profile mode
        current_tools_allow=["existing-allow"],
        current_tools_profile=None,
    )

    paths = {e["path"]: e["value"] for e in entries}
    # No profile → extend tools.allow, never touch tools.alsoAllow.
    assert paths["tools.allow"] == ["existing-allow", "group:openclaw", "dataclaw"]
    assert "tools.alsoAllow" not in paths
    assert paths["channels.dataclaw.dataclawApiUrl"] == "http://x"


def test_build_batch_entries_appends_to_also_allow_when_profile_set() -> None:
    entries = build_batch_entries(
        channel_values={},
        also_allow_addition="dataclaw",
        current_also_allow=["existing-also"],
        current_tools_allow=["existing-allow"],  # left untouched in profile mode
        current_tools_profile="coding",
    )

    paths = {e["path"]: e["value"] for e in entries}
    # Profile active → extend tools.alsoAllow, never touch tools.allow.
    assert paths["tools.alsoAllow"] == ["existing-also", "group:openclaw", "dataclaw"]
    assert "tools.allow" not in paths


def test_build_batch_entries_idempotent_when_allow_already_complete() -> None:
    entries = build_batch_entries(
        channel_values={"dataclawApiUrl": "http://x"},
        also_allow_addition="dataclaw",
        current_also_allow=[],
        current_tools_allow=["group:openclaw", "dataclaw"],  # already complete
        current_tools_profile=None,
    )

    assert entries == [
        {"path": "channels.dataclaw.dataclawApiUrl", "value": "http://x"}
    ]


def test_build_batch_entries_enables_plugin_and_adds_to_allow() -> None:
    entries = build_batch_entries(
        channel_values={},
        also_allow_addition=None,
        current_also_allow=[],
        enable_plugin_id="dataclaw",
        current_plugins_allow=["other"],
    )

    paths = {e["path"]: e["value"] for e in entries}
    assert paths["plugins.entries.dataclaw.enabled"] is True
    assert paths["plugins.allow"] == ["other", "dataclaw"]


def test_build_batch_entries_skips_plugins_allow_when_unset() -> None:
    # plugins.allow=[] (or unset) means OpenClaw auto-allows discovered
    # plugins, so seeding it would narrow that posture and silently
    # disable everything else. Skip the write.
    for current in ([], None):
        entries = build_batch_entries(
            channel_values={},
            also_allow_addition=None,
            current_also_allow=[],
            enable_plugin_id="dataclaw",
            current_plugins_allow=current,
        )
        paths = [e["path"] for e in entries]
        assert "plugins.allow" not in paths, f"unexpected write for current={current!r}"
        # We still flip enabled to True so the plugin loads.
        assert "plugins.entries.dataclaw.enabled" in paths


def test_build_batch_entries_enables_without_duplicating_allow_membership() -> None:
    entries = build_batch_entries(
        channel_values={},
        also_allow_addition=None,
        current_also_allow=[],
        enable_plugin_id="dataclaw",
        current_plugins_allow=["dataclaw"],
    )

    paths = [e["path"] for e in entries]
    assert "plugins.entries.dataclaw.enabled" in paths
    assert "plugins.allow" not in paths


def test_build_batch_entries_skips_channel_values_already_at_desired_value() -> None:
    entries = build_batch_entries(
        channel_values={"dataclawApiUrl": "http://x", "token": "tok"},
        also_allow_addition=None,
        current_also_allow=[],
        current_channel_section={"dataclawApiUrl": "http://x"},  # token differs/missing
    )

    paths = {e["path"] for e in entries}
    assert "channels.dataclaw.token" in paths
    assert "channels.dataclaw.dataclawApiUrl" not in paths


def test_build_batch_entries_skips_enabled_when_already_true() -> None:
    entries = build_batch_entries(
        channel_values={},
        also_allow_addition=None,
        current_also_allow=[],
        enable_plugin_id="dataclaw",
        current_plugins_allow=["dataclaw"],
        current_plugin_enabled=True,
    )

    assert entries == []


def test_build_batch_entries_returns_empty_when_everything_matches() -> None:
    entries = build_batch_entries(
        channel_values={"token": "tok"},
        also_allow_addition="dataclaw",
        current_also_allow=[],
        enable_plugin_id="dataclaw",
        current_plugins_allow=["dataclaw"],
        current_channel_section={"token": "tok"},
        current_plugin_enabled=True,
        current_tools_allow=["group:openclaw", "dataclaw"],
    )

    assert entries == []


def test_build_batch_entries_seeds_tools_allow_when_unset() -> None:
    entries = build_batch_entries(
        channel_values={},
        also_allow_addition="dataclaw",
        current_also_allow=[],
    )

    # tools.allow needs seeding so the plugin gets past OpenClaw's
    # tool-loading allowlist gate; alsoAllow stays untouched (was empty).
    paths = {e["path"]: e["value"] for e in entries}
    assert paths["tools.allow"] == ["group:openclaw", "dataclaw"]
    assert "tools.alsoAllow" not in paths


def test_build_batch_entries_extends_tools_allow_preserving_existing() -> None:
    entries = build_batch_entries(
        channel_values={},
        also_allow_addition="dataclaw",
        current_also_allow=[],
        current_tools_allow=["existing-entry"],
    )

    paths = {e["path"]: e["value"] for e in entries}
    assert paths["tools.allow"] == ["existing-entry", "group:openclaw", "dataclaw"]


def test_build_batch_entries_omits_tools_allow_when_already_complete() -> None:
    entries = build_batch_entries(
        channel_values={},
        also_allow_addition="dataclaw",
        current_also_allow=[],
        current_tools_allow=["group:openclaw", "dataclaw", "other"],
    )

    paths = [e["path"] for e in entries]
    assert "tools.allow" not in paths
    assert "tools.alsoAllow" not in paths


def test_write_plugin_manifest_contracts_tools_writes_prefixed_names(
    tmp_path: Path,
) -> None:
    plugin_dir = _write_manifest(tmp_path, {"id": "dataclaw"})

    ok, msg = write_plugin_manifest_contracts_tools(
        plugin_dir,
        tools=[
            {"name": "alpha"},
            {"name": "beta"},
            {"name": "alpha"},  # duplicate dropped
            {"name": ""},  # empty dropped
        ],
        prefix="dataclaw_",
    )

    assert ok
    assert "2 entries" in msg
    written = json.loads((plugin_dir / PLUGIN_MANIFEST_FILENAME).read_text())
    assert written["contracts"]["tools"] == ["dataclaw_alpha", "dataclaw_beta"]


def test_write_plugin_manifest_contracts_tools_no_op_when_already_current(
    tmp_path: Path,
) -> None:
    plugin_dir = _write_manifest(
        tmp_path,
        {
            "id": "dataclaw",
            "contracts": {"tools": ["dataclaw_alpha"]},
        },
    )
    manifest_path = plugin_dir / PLUGIN_MANIFEST_FILENAME
    before = manifest_path.read_text()

    ok, msg = write_plugin_manifest_contracts_tools(
        plugin_dir, tools=[{"name": "alpha"}], prefix="dataclaw_"
    )

    assert ok
    assert "already current" in msg
    # File bytes are untouched — no reformatting churn on repeat installs.
    assert manifest_path.read_text() == before


def test_write_plugin_manifest_contracts_tools_skips_when_tools_none(
    tmp_path: Path,
) -> None:
    plugin_dir = _write_manifest(tmp_path, {"id": "dataclaw"})
    manifest_path = plugin_dir / PLUGIN_MANIFEST_FILENAME
    before = manifest_path.read_text()

    ok, msg = write_plugin_manifest_contracts_tools(
        plugin_dir, tools=None, prefix="dataclaw_"
    )

    assert not ok
    assert "tool registry unavailable" in msg
    assert manifest_path.read_text() == before


# ── install_plugin_atomic orchestrator ──────────────────────────────────────


@pytest.mark.asyncio
async def test_install_plugin_atomic_pre_flight_fails_on_missing_dir(
    tmp_path: Path,
) -> None:
    events = []
    async for event in install_plugin_atomic(
        plugin_dir=tmp_path / "nope",
        openclaw_cfg={},
        argv=["openclaw"],
    ):
        events.append(event)

    assert len(events) == 1
    assert events[0]["exit_code"] == 1
    assert "not found" in events[0]["error"]


@pytest.mark.asyncio
async def test_install_plugin_atomic_refuses_to_reuse_a_stale_generated_manifest(tmp_path: Path) -> None:
    plugin_dir = _write_manifest(tmp_path, {"id": "dataclaw"})

    events = []
    async for event in install_plugin_atomic(
        plugin_dir=plugin_dir,
        openclaw_cfg={},
        argv=["openclaw"],
        tools=None,
    ):
        events.append(event)

    assert len(events) == 1
    assert events[0]["exit_code"] == 1
    assert "live Dataclaw tool registry is unavailable" in events[0]["error"]


@pytest.mark.asyncio
async def test_install_plugin_atomic_happy_path(tmp_path: Path) -> None:
    plugin_dir = _write_manifest(
        tmp_path,
        {"id": "dataclaw"},
    )

    # Mock subprocess: every spawn returns a process whose stdout yields one
    # line and that exits 0.
    async def fake_subprocess_exec(*args, **kwargs):
        proc = AsyncMock()
        proc.stdout.__aiter__.return_value = iter([b"line one\n"])
        proc.wait.return_value = 0
        proc.communicate.return_value = (b"[]", b"")
        proc.returncode = 0
        return proc

    # Mock httpx healthz: always returns 200
    fake_response = AsyncMock()
    fake_response.is_success = True

    class FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def get(self, *_args, **_kwargs):
            return fake_response

    with (
        patch("asyncio.create_subprocess_exec", side_effect=fake_subprocess_exec) as spawn,
        patch("httpx.AsyncClient", FakeAsyncClient),
        patch("asyncio.sleep", new=AsyncMock()),
    ):
        events = []
        async for event in install_plugin_atomic(
            plugin_dir=plugin_dir,
            openclaw_cfg={"token": "tok"},
            argv=["openclaw"],
            also_allow_addition="dataclaw",
            tools=[
                {"name": "demo", "description": "d", "parameters": {}},
                {
                    "name": "report_design_report",
                    "description": "Design cohesive analytical reports",
                    "parameters": {
                        "type": "object",
                        "properties": {"design_passes": {}, "visual_author": {}},
                    },
                },
            ],
        ):
            events.append(event)

    # The install should have written tool-manifest.generated.ts with the
    # supplied tool list (the gitignored, user-specific sibling of the
    # committed tool-manifest.ts re-export stub).
    refreshed = plugin_dir / "src" / "tools" / "tool-manifest.generated.ts"
    assert refreshed.exists()
    body = refreshed.read_text()
    assert 'name: "demo"' in body
    assert 'name: "report_design_report"' in body
    assert "DATACLAW_TOOL_MANIFEST" in body

    # And it should have mirrored the tool list into openclaw.plugin.json's
    # contracts.tools — each tool prefixed with the configured tools_prefix
    # (default "dataclaw_") so OpenClaw's tool-contract gate accepts the
    # registerTool calls at load time.
    refreshed_manifest = json.loads(
        (plugin_dir / PLUGIN_MANIFEST_FILENAME).read_text()
    )
    assert refreshed_manifest["contracts"]["tools"] == [
        "dataclaw_demo",
        "dataclaw_report_design_report",
    ]

    # Expected subprocess calls (in order). Channel config writes happen AFTER
    # plugin install: OpenClaw 2026.5's plugin-install commit hard-fails on
    # orphan channel sections, and writing channels.<id> before the plugin is
    # registered creates exactly that orphan. So pre-install we only check
    # whether the channel section already exists (and would clear it if so);
    # post-install we batch all the real config writes.
    #    1. config get channels.dataclaw --json    (pre-install: any stale section?)
    #    2. npm install                             (devDeps for esbuild)
    #    3. npm run build                           (esbuild → dist/index.js)
    #    4. plugins install <dir> --force
    #    5. config get tools.alsoAllow --json
    #    6. config get tools.allow --json
    #    7. config get tools.profile --json         (picks allow vs alsoAllow target)
    #    8. config get plugins.allow --json
    #    9. config get channels.dataclaw --json
    #   10. config get plugins.entries.dataclaw.config --json
    #   11. config get plugins.entries.dataclaw.enabled --json
    #   12. config set --batch-json ...             (atomic config write)
    spawn_argvs = [c.args for c in spawn.call_args_list]
    assert len(spawn_argvs) == 12
    assert spawn_argvs[0][:5] == ("openclaw", "config", "get", "channels.dataclaw", "--json")
    assert spawn_argvs[1][:2] == ("npm", "install")
    assert spawn_argvs[2][:3] == ("npm", "run", "build")
    assert spawn_argvs[3][:3] == ("openclaw", "plugins", "install")
    assert "--force" in spawn_argvs[3]
    assert spawn_argvs[4][:5] == ("openclaw", "config", "get", "tools.alsoAllow", "--json")
    assert spawn_argvs[5][:5] == ("openclaw", "config", "get", "tools.allow", "--json")
    assert spawn_argvs[6][:5] == ("openclaw", "config", "get", "tools.profile", "--json")
    assert spawn_argvs[7][:5] == ("openclaw", "config", "get", "plugins.allow", "--json")
    assert spawn_argvs[8][:5] == ("openclaw", "config", "get", "channels.dataclaw", "--json")
    assert spawn_argvs[9][:5] == ("openclaw", "config", "get", "plugins.entries.dataclaw.config", "--json")
    assert spawn_argvs[10][:5] == ("openclaw", "config", "get", "plugins.entries.dataclaw.enabled", "--json")
    assert spawn_argvs[11][:3] == ("openclaw", "config", "set")
    assert "--batch-json" in spawn_argvs[11]

    # Final event reports success.
    assert events[-1] == {"exit_code": 0}

    # Batch payload splits config across two namespaces:
    # - channels.dataclaw.{token, dataclawApiUrl} for auth/transport.
    # - plugins.entries.dataclaw.config.{toolsPrefix, toolsOptional} for tools.
    # Plus tools.allow seeding + plugin enable. tools.alsoAllow is NOT written
    # because the mocked `config get` returns [] — nothing to clear. plugins.allow
    # is also NOT written because the mock's `[]` means OpenClaw is auto-allowing
    # discovered plugins; seeding would narrow that posture.
    batch_arg = spawn_argvs[11][spawn_argvs[11].index("--batch-json") + 1]
    batch = json.loads(batch_arg)
    paths = {entry["path"]: entry["value"] for entry in batch}
    assert paths["channels.dataclaw.token"] == "tok"
    assert paths["channels.dataclaw.dataclawApiUrl"] == "http://localhost:8000"
    assert paths["plugins.entries.dataclaw.config.toolsPrefix"] == "dataclaw_"
    assert paths["plugins.entries.dataclaw.config.toolsOptional"] is False
    # Channel section no longer carries tools knobs.
    assert "channels.dataclaw.toolsPrefix" not in paths
    assert "channels.dataclaw.toolsOptional" not in paths
    # No env.vars writes anymore.
    assert not any(p.startswith("env.vars.") for p in paths)
    assert paths["tools.allow"] == ["group:openclaw", "dataclaw"]
    assert "plugins.entries.dataclaw.enabled" in paths
    assert "plugins.allow" not in paths


@pytest.mark.asyncio
async def test_install_plugin_uses_config_unset_for_existing_orphan_channel(tmp_path: Path, monkeypatch) -> None:
    plugin_dir = _write_manifest(tmp_path, {"id": "dataclaw"})
    calls: list[list[str]] = []

    async def fake_stream(argv: list[str], cwd: Path | None = None):
        calls.append(argv)
        yield {"_rc": 0}

    async def fake_build(_plugin_dir: Path):
        yield {"line": "built"}

    async def fake_channel_section(*_args, **_kwargs):
        return {"dataclawApiUrl": "http://legacy"}

    monkeypatch.setattr(install_service, "_stream_subprocess", fake_stream)
    monkeypatch.setattr(install_service, "build_plugin_runtime", fake_build)
    monkeypatch.setattr(install_service, "_wait_for_gateway", _empty_async_events)
    monkeypatch.setattr(install_service, "fetch_current_channel_section", fake_channel_section)
    monkeypatch.setattr(install_service, "fetch_current_also_allow", AsyncMock(return_value=[]))
    monkeypatch.setattr(install_service, "fetch_current_tools_allow", AsyncMock(return_value=[]))
    monkeypatch.setattr(install_service, "fetch_current_tools_profile", AsyncMock(return_value=None))
    monkeypatch.setattr(install_service, "fetch_current_plugins_allow", AsyncMock(return_value=[]))
    monkeypatch.setattr(install_service, "fetch_current_plugin_entry_config", AsyncMock(return_value={}))
    monkeypatch.setattr(install_service, "fetch_current_plugin_enabled", AsyncMock(return_value=False))

    events = [
        event
        async for event in install_plugin_atomic(
            plugin_dir=plugin_dir,
            openclaw_cfg={},
            argv=["openclaw"],
            tools=[{"name": "demo", "description": "Demo tool", "parameters": {}}],
        )
    ]

    assert ["openclaw", "config", "unset", "channels.dataclaw"] in calls
    assert not any("--batch-json" in call and "channels.dataclaw" in call for call in calls)
    assert events[-1] == {"exit_code": 0}
