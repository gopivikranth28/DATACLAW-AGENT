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

    assert "report_design_report missing properties: visual_author" in issues
    assert "report_publish missing properties: require_visual_review" in issues
    assert "publish_artifact missing properties: report_receipt_path" in issues
    assert "report_publish is present but report_review_visuals is unavailable" in issues


def test_report_tool_manifest_accepts_a_complete_governed_publish_flow() -> None:
    tools = [
        {"name": "report_design_report", "parameters": {"properties": {"visual_author": {}}}},
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


def _write_built_plugin(tmp_path: Path) -> Path:
    """A plugin dir that looks like it went through `npm run build`."""
    plugin_dir = _write_manifest(
        tmp_path,
        {"id": "dataclaw", "channels": ["dataclaw"], "skills": ["./skills"]},
    )
    (plugin_dir / "package.json").write_text('{"name": "@dataclaw/openclaw-dataclaw"}')
    (plugin_dir / "dist").mkdir()
    (plugin_dir / "dist" / "index.js").write_text("export default {};\n")
    (plugin_dir / "skills" / "dataclaw").mkdir(parents=True)
    (plugin_dir / "skills" / "dataclaw" / "SKILL.md").write_text("---\nname: dataclaw\n---\n")
    (plugin_dir / "node_modules" / "openclaw").mkdir(parents=True)
    return plugin_dir


@pytest.mark.asyncio
async def test_install_plugin_atomic_happy_path(tmp_path: Path) -> None:
    plugin_dir = _write_built_plugin(tmp_path)

    # Mock subprocess: every spawn returns a process whose stdout yields one
    # line and that exits 0. `--version` reports the supported minimum.
    async def fake_subprocess_exec(*args, **kwargs):
        proc = AsyncMock()
        proc.stdout.__aiter__.return_value = iter([b"line one\n"])
        proc.wait.return_value = 0
        if args[-1] == "--version":
            proc.communicate.return_value = (b"OpenClaw 2026.10.7 (157d8c2)\n", b"")
        else:
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
                        "properties": {"visual_author": {}},
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
    # plugin install so channels.<id> and plugins.entries.<id> are known to
    # the validator. Nothing is written before the install: OpenClaw 2026.10
    # no longer rejects a leftover channels.<id> section, so the old
    # pre-install `config unset` is gone.
    #    1. openclaw --version                      (minimum-version gate)
    #    2. npm install                             (devDeps for esbuild)
    #    3. npm run build                           (esbuild → dist/index.js)
    #    4. plugins install <dir>/.openclaw-package --force --accept-capabilities
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
    assert spawn_argvs[0] == ("openclaw", "--version")
    assert spawn_argvs[1][:2] == ("npm", "install")
    assert "--ignore-scripts" in spawn_argvs[1]
    assert spawn_argvs[2][:3] == ("npm", "run", "build")
    assert spawn_argvs[3] == (
        "openclaw", "plugins", "install",
        str(plugin_dir / ".openclaw-package"),
        "--force", "--accept-capabilities",
    )
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

    # Only runtime files are staged for the install — never node_modules or
    # the TypeScript sources.
    staged = plugin_dir / ".openclaw-package"
    assert sorted(p.name for p in staged.iterdir()) == [
        "dist", PLUGIN_MANIFEST_FILENAME, "package.json", "skills",
    ]
    assert (staged / "dist" / "index.js").is_file()
    assert (staged / "skills" / "dataclaw" / "SKILL.md").is_file()

    # The declared capability surface is logged before consenting to it.
    lines = [e.get("line", "") for e in events]
    assert any(
        line.startswith("Accepting declared capabilities:")
        and "channels=dataclaw" in line and "tools=2" in line and "skills=./skills" in line
        for line in lines
    )

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


def _patch_install_flow(monkeypatch, *, version: str | None = "OpenClaw 2026.10.7 (157d8c2)",
                        install_lines: list[str] | None = None, plugin_enabled: bool = False):
    """Stub every subprocess-backed step of install_plugin_atomic.

    Returns the list that records each `_stream_subprocess` argv.
    """
    calls: list[list[str]] = []

    async def fake_stream(argv: list[str], cwd: Path | None = None):
        calls.append(argv)
        if argv[1:3] == ["plugins", "install"]:
            for line in install_lines or []:
                yield {"line": line}
        yield {"_rc": 0}

    async def fake_build(_plugin_dir: Path):
        yield {"line": "built"}

    monkeypatch.setattr(install_service, "_stream_subprocess", fake_stream)
    monkeypatch.setattr(install_service, "build_plugin_runtime", fake_build)
    monkeypatch.setattr(install_service, "_wait_for_gateway", _empty_async_events)
    monkeypatch.setattr(install_service, "fetch_openclaw_version", AsyncMock(return_value=version))
    monkeypatch.setattr(
        install_service, "fetch_current_channel_section",
        AsyncMock(return_value={"dataclawApiUrl": "http://legacy"}),
    )
    monkeypatch.setattr(install_service, "fetch_current_also_allow", AsyncMock(return_value=[]))
    monkeypatch.setattr(install_service, "fetch_current_tools_allow", AsyncMock(return_value=[]))
    monkeypatch.setattr(install_service, "fetch_current_tools_profile", AsyncMock(return_value=None))
    monkeypatch.setattr(install_service, "fetch_current_plugins_allow", AsyncMock(return_value=[]))
    monkeypatch.setattr(install_service, "fetch_current_plugin_entry_config", AsyncMock(return_value={}))
    monkeypatch.setattr(
        install_service, "fetch_current_plugin_enabled", AsyncMock(return_value=plugin_enabled),
    )
    return calls


async def _run_install(plugin_dir: Path, **kwargs) -> list[dict]:
    return [
        event
        async for event in install_plugin_atomic(
            plugin_dir=plugin_dir,
            openclaw_cfg=kwargs.pop("openclaw_cfg", {}),
            argv=["openclaw"],
            tools=[{"name": "demo", "description": "Demo tool", "parameters": {}}],
            **kwargs,
        )
    ]


@pytest.mark.asyncio
async def test_install_plugin_does_not_unset_an_existing_channel_section(tmp_path: Path, monkeypatch) -> None:
    plugin_dir = _write_built_plugin(tmp_path)
    calls = _patch_install_flow(monkeypatch)

    events = await _run_install(plugin_dir)

    assert not any(call[1:3] == ["config", "unset"] for call in calls)
    # The existing section is updated in place by the post-install batch.
    batch_calls = [call for call in calls if "--batch-json" in call]
    assert len(batch_calls) == 1
    batch = json.loads(batch_calls[0][batch_calls[0].index("--batch-json") + 1])
    assert {"path": "channels.dataclaw.dataclawApiUrl", "value": "http://localhost:8000"} in batch
    assert events[-1] == {"exit_code": 0}


@pytest.mark.asyncio
async def test_install_plugin_installs_from_the_openclaw_side_staged_package(tmp_path: Path, monkeypatch) -> None:
    plugin_dir = _write_built_plugin(tmp_path)
    calls = _patch_install_flow(monkeypatch)

    events = await _run_install(plugin_dir, install_dir=Path("/dataclaw/openclaw-plugins/dataclaw"))

    assert [
        "openclaw", "plugins", "install",
        "/dataclaw/openclaw-plugins/dataclaw/.openclaw-package",
        "--force", "--accept-capabilities",
    ] in calls
    assert events[-1] == {"exit_code": 0}


@pytest.mark.asyncio
async def test_install_plugin_blocks_unsupported_openclaw_before_writing(tmp_path: Path, monkeypatch) -> None:
    plugin_dir = _write_built_plugin(tmp_path)
    calls = _patch_install_flow(monkeypatch, version="OpenClaw 2026.5.3-1 (abc1234)")

    events = await _run_install(plugin_dir)

    assert events[-1]["exit_code"] == 1
    assert "older than the supported minimum 2026.10.7" in events[-1]["error"]
    assert calls == []
    assert not (plugin_dir / "src" / "tools" / "tool-manifest.generated.ts").exists()


@pytest.mark.asyncio
async def test_install_plugin_continues_when_version_is_unknown(tmp_path: Path, monkeypatch) -> None:
    plugin_dir = _write_built_plugin(tmp_path)
    _patch_install_flow(monkeypatch, version=None)

    events = await _run_install(plugin_dir)

    assert any("could not determine the OpenClaw version" in e.get("line", "") for e in events)
    assert events[-1] == {"exit_code": 0}


@pytest.mark.asyncio
async def test_install_plugin_fails_when_capability_consent_is_refused(tmp_path: Path, monkeypatch) -> None:
    # The CLI exits 0 when it refuses an install for missing consent.
    plugin_dir = _write_built_plugin(tmp_path)
    calls = _patch_install_flow(monkeypatch, install_lines=[
        'Plugin "dataclaw" requires capability consent. The plugin was not installed. Re-run ...',
    ])

    events = await _run_install(plugin_dir)

    assert events[-1]["exit_code"] == 1
    assert "plugins install failed" in events[-1]["error"]
    assert not any("--batch-json" in call for call in calls)


@pytest.mark.asyncio
async def test_install_plugin_fails_when_build_output_is_missing(tmp_path: Path, monkeypatch) -> None:
    plugin_dir = _write_built_plugin(tmp_path)
    (plugin_dir / "dist" / "index.js").unlink()
    calls = _patch_install_flow(monkeypatch)

    events = await _run_install(plugin_dir)

    assert events[-1]["exit_code"] == 1
    assert "dist/index.js" in events[-1]["error"]
    assert calls == []


@pytest.mark.asyncio
async def test_install_plugin_records_state_when_config_is_already_current(tmp_path: Path, monkeypatch) -> None:
    plugin_dir = _write_built_plugin(tmp_path)
    calls = _patch_install_flow(monkeypatch, plugin_enabled=True)
    monkeypatch.setattr(install_service, "build_batch_entries", lambda *a, **k: [])

    events = await _run_install(plugin_dir)

    assert not any("--batch-json" in call for call in calls)
    assert events[-1] == {"exit_code": 0}
    assert install_service.read_install_state("dataclaw")["tool_names"] == ["demo"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("OpenClaw 2026.10.7 (157d8c2)", True),
        ("2026.10.7", True),
        ("OpenClaw 2026.10.12 (deadbee)", True),
        ("OpenClaw 2026.11.0", True),
        ("OpenClaw 2027.1.1", True),
        ("OpenClaw 2026.10.7-1", True),
        ("OpenClaw 2026.10.7-beta.2", False),
        ("OpenClaw 2026.10.6", False),
        ("OpenClaw 2026.9.34 (extended-stable)", False),
        ("OpenClaw 2026.5.3-1", False),
        ("openclaw: command not found", None),
        ("", None),
    ],
)
def test_is_supported_openclaw_version(text: str, expected: bool | None) -> None:
    assert install_service.is_supported_openclaw_version(text) is expected


def test_describe_declared_capabilities() -> None:
    manifest = {
        "channels": ["dataclaw"],
        "skills": ["./skills"],
        "contracts": {"tools": ["dataclaw_a", "dataclaw_b"]},
    }
    assert install_service.describe_declared_capabilities(manifest) == (
        "channels=dataclaw tools=2 skills=./skills"
    )
    assert install_service.describe_declared_capabilities({}) == "channels=none tools=0 skills=none"


def test_parse_plugin_inspect_output_reads_real_2026_10_7_payload() -> None:
    from dataclaw_openclaw.install_router import parse_plugin_inspect_output

    fixture = Path(__file__).parent / "fixtures" / "plugins_inspect_dataclaw_2026.10.7.json"
    # stdout and stderr are merged; a state-dir warning can precede the JSON.
    output = (
        'State directory root "/root/.openclaw" is owned by another user: uid 1000, gid 1000; '
        "leaving mode 755.\n" + fixture.read_text()
    )
    assert parse_plugin_inspect_output(output) == {
        "installed": True,
        "status": "loaded",
        "version": "0.1.0",
        "enabled": True,
    }
    assert parse_plugin_inspect_output('Plugin not found: dataclaw') == {"installed": False}
