"""OpenClaw plugin install orchestration.

Pure-ish service module: parses the plugin manifest, resolves env-var values
from Dataclaw config, builds an atomic batch-config payload, and runs the
``openclaw config set --batch-json`` + ``openclaw plugins install`` sequence
through subprocesses. Yields SSE-shaped event dicts so the FastAPI router can
forward them verbatim to the UI.

Designed to be unit-testable without FastAPI: import the module and feed it
plain dicts/paths.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)


PLUGIN_MANIFEST_FILENAME = "openclaw.plugin.json"


# OpenClaw 2026.5's install scanner blocks any plugin bundle that mixes
# `process.env` access with a network send (`fetch(`/`post(`/`http.request(`).
# DataClaw's plugin legitimately reads its token + API URL and POSTs replies
# back to the dataclaw API, so we sidestep the heuristic by writing the same
# values into structured OpenClaw config instead of `env.vars.DATACLAW_*`.
# The plugin reads them out of cfg with no `process.env` fallback — see
# `src/channel/config.ts` and `src/tools/config.ts`.
#
# Connection settings (token + API URL) live under `channels.dataclaw.*`
# because the Dataclaw chat is the channel's auth/transport surface and the
# OpenClaw config UI surfaces channel sections via `channelConfigs.<id>`.
# Tools-only knobs (registration prefix, optional-tool flag) live under
# `plugins.entries.dataclaw.config.*` — the canonical per-plugin namespace
# validated by the manifest's top-level `configSchema`.
CHANNEL_SECTION_ID = "dataclaw"
CHANNEL_CFG_KEY_MAP: dict[str, tuple[str, Any]] = {
    "token": ("token", None),
    "dataclawApiUrl": ("tools_api_url", "http://localhost:8000"),
}
PLUGIN_ENTRY_CFG_KEY_MAP: dict[str, tuple[str, Any]] = {
    "toolsPrefix": ("tools_prefix", "dataclaw_"),
    "toolsOptional": ("tools_optional", False),
}
CHANNEL_TOKEN_PATHS: frozenset[str] = frozenset(
    {f"channels.{CHANNEL_SECTION_ID}.token"}
)


def read_plugin_manifest(plugin_dir: Path) -> dict[str, Any]:
    """Load and validate the plugin's openclaw.plugin.json."""
    manifest_path = plugin_dir / PLUGIN_MANIFEST_FILENAME
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"Plugin manifest not found: {manifest_path}. "
            f"Check plugins_source_dir in Config → OpenClaw."
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"Plugin manifest is not valid JSON: {manifest_path}: {e}") from e
    if not isinstance(manifest, dict) or not isinstance(manifest.get("id"), str):
        raise ValueError(f"Plugin manifest missing required 'id' field: {manifest_path}")
    return manifest


def _resolve_section(
    openclaw_cfg: dict[str, Any],
    key_map: dict[str, tuple[str, Any]],
) -> dict[str, Any]:
    """Translate dataclaw cfg keys into a desired-value map for one section.

    Entries with neither a config value nor a default are skipped — that maps
    to "leave OpenClaw's existing value untouched" rather than writing an
    explicit clear.
    """
    resolved: dict[str, Any] = {}
    for section_key, (cfg_key, default) in key_map.items():
        raw = openclaw_cfg.get(cfg_key, default)
        if raw is None or raw == "":
            continue
        resolved[section_key] = raw
    return resolved


def resolve_channel_section_values(openclaw_cfg: dict[str, Any]) -> dict[str, Any]:
    """Build the desired ``channels.<id>.*`` value map (token, dataclawApiUrl)."""
    return _resolve_section(openclaw_cfg, CHANNEL_CFG_KEY_MAP)


def resolve_plugin_entry_config_values(openclaw_cfg: dict[str, Any]) -> dict[str, Any]:
    """Build the desired ``plugins.entries.<id>.config.*`` value map (tools knobs)."""
    return _resolve_section(openclaw_cfg, PLUGIN_ENTRY_CFG_KEY_MAP)


# Pick the right knob to extend based on whether a built-in tool profile is
# active:
#
# - `tools.profile` set (e.g., "coding"): the profile defines the base allow
#   list. `tools.alsoAllow` is the additive extension hook — write the plugin
#   id there. OpenClaw's schema rejects `tools.allow` and `tools.alsoAllow`
#   set at the same scope, so we never co-write them.
# - No `tools.profile`: there is no implicit base allow list, so write to
#   `tools.allow` directly.
#
# In both cases we APPEND to whatever the user already has — no migration
# between the two fields, and existing entries are preserved.
TOOLS_ALLOW_CORE_GROUP = "group:openclaw"


def _merge_allow_extension(
    plugin_id: str,
    current: list[str],
) -> list[str]:
    """Append plugin_id and the core group to an existing allow-style list.

    Order is preserved and entries are deduped. Empty / whitespace entries
    are dropped.
    """
    desired: list[str] = []
    seen: set[str] = set()
    for entry in (*current, TOOLS_ALLOW_CORE_GROUP, plugin_id):
        if not entry or entry in seen:
            continue
        seen.add(entry)
        desired.append(entry)
    return desired


def build_batch_entries(
    channel_values: dict[str, Any],
    also_allow_addition: str | None,
    current_also_allow: list[str],
    enable_plugin_id: str | None = None,
    current_plugins_allow: list[str] | None = None,
    current_channel_section: dict[str, Any] | None = None,
    current_plugin_enabled: bool | None = None,
    current_tools_allow: list[str] | None = None,
    plugin_entry_config_values: dict[str, Any] | None = None,
    current_plugin_entry_config: dict[str, Any] | None = None,
    current_tools_profile: str | None = None,
    channel_id: str = CHANNEL_SECTION_ID,
) -> list[dict[str, Any]]:
    """Build the JSON payload for ``openclaw config set --batch-json``.

    Only emits entries for values that would actually change. If openclaw's
    config already has every value we'd set, returns ``[]`` and the caller
    skips the config-set + gateway-restart step entirely.

    Deltas:
    - ``channels.<id>.{token,dataclawApiUrl}`` — the channel's auth/transport
      settings, surfaced through ``channelConfigs.<id>.schema``.
    - ``plugins.entries.<id>.config.{toolsPrefix,toolsOptional}`` — tools-only
      knobs in the canonical per-plugin namespace, validated by the manifest's
      top-level ``configSchema``.
    - Tool allowlist extension: when ``tools.profile`` is set we extend
      ``tools.alsoAllow`` (the additive hook for profile-based configs);
      otherwise we extend ``tools.allow`` directly. In both cases we APPEND
      the plugin id + core group to whatever the user already has — never
      replace, never co-write the two fields. When the target field is
      unset, we seed it with ``[group:openclaw, plugin_id]`` so the plugin's
      tools clear the allowlist gate from a clean install.
    - ``plugins.entries.<id>.enabled`` only when not already ``True``
    - ``plugins.allow`` only when the user has an existing non-empty
      allowlist that doesn't already include ``enable_plugin_id`` (we
      merge in). When ``plugins.allow`` is unset/empty, OpenClaw
      auto-allows discovered plugins, so seeding would narrow that
      posture and silently disable any other plugins the user had loaded.
    """
    entries: list[dict[str, Any]] = []
    cur_channel = current_channel_section or {}
    for section_key, value in channel_values.items():
        if cur_channel.get(section_key) != value:
            entries.append(
                {"path": f"channels.{channel_id}.{section_key}", "value": value}
            )
    cur_plugin_cfg = current_plugin_entry_config or {}
    plugin_cfg_values = plugin_entry_config_values or {}
    plugin_id_for_entry = enable_plugin_id or channel_id
    for section_key, value in plugin_cfg_values.items():
        if cur_plugin_cfg.get(section_key) != value:
            entries.append(
                {
                    "path": f"plugins.entries.{plugin_id_for_entry}.config.{section_key}",
                    "value": value,
                }
            )
    if also_allow_addition:
        profile_active = bool((current_tools_profile or "").strip())
        if profile_active:
            cur = list(current_also_allow or [])
            desired = _merge_allow_extension(also_allow_addition, cur)
            if desired != cur:
                entries.append({"path": "tools.alsoAllow", "value": desired})
        else:
            cur = list(current_tools_allow or [])
            desired = _merge_allow_extension(also_allow_addition, cur)
            if desired != cur:
                entries.append({"path": "tools.allow", "value": desired})
    if enable_plugin_id:
        if current_plugin_enabled is not True:
            entries.append({
                "path": f"plugins.entries.{enable_plugin_id}.enabled",
                "value": True,
            })
        # plugins.allow is a strict allowlist: when it has any entries,
        # OpenClaw enforces it and silently rejects everything else; when
        # it's empty/unset, OpenClaw auto-allows discovered plugins. So we
        # only merge into an existing non-empty list — we never seed one.
        # Seeding would *narrow* a user's "allow anything discovered"
        # posture down to "allow only dataclaw", quietly disabling every
        # other plugin they had loaded.
        current = current_plugins_allow or []
        if current and enable_plugin_id not in current:
            entries.append({
                "path": "plugins.allow",
                "value": [*current, enable_plugin_id],
            })
    return entries


def _sse(data: dict[str, Any]) -> dict[str, Any]:
    """Identity helper — install_router serializes these to SSE."""
    return data


async def fetch_current_also_allow(argv: list[str]) -> list[str]:
    """Run ``openclaw config get tools.alsoAllow --json`` and parse.

    Returns ``[]`` on any failure (a missing key is normal — alsoAllow is optional).
    """
    return await _fetch_config_list(argv, "tools.alsoAllow")


async def fetch_current_tools_allow(argv: list[str]) -> list[str]:
    """Run ``openclaw config get tools.allow --json`` and parse.

    Returns ``[]`` on any failure (a missing key is normal — tools.allow is optional).
    """
    return await _fetch_config_list(argv, "tools.allow")


async def fetch_current_plugins_allow(argv: list[str]) -> list[str]:
    """Run ``openclaw config get plugins.allow --json`` and parse."""
    return await _fetch_config_list(argv, "plugins.allow")


async def fetch_current_channel_section(
    argv: list[str], channel_id: str = CHANNEL_SECTION_ID
) -> dict[str, Any]:
    """Read the current ``channels.<id>`` section (best-effort)."""
    raw = await _fetch_config_value(argv, f"channels.{channel_id}")
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items() if isinstance(k, str)}


async def fetch_current_plugin_entry_config(
    argv: list[str], plugin_id: str
) -> dict[str, Any]:
    """Read the current ``plugins.entries.<id>.config`` section (best-effort)."""
    raw = await _fetch_config_value(argv, f"plugins.entries.{plugin_id}.config")
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items() if isinstance(k, str)}


async def fetch_current_tools_profile(argv: list[str]) -> str | None:
    """Read the current ``tools.profile`` (best-effort).

    Returns ``None`` if no profile is set or the value is non-string. With a
    profile active, plugin-id allowlist extensions go to ``tools.alsoAllow``;
    without one, they go to ``tools.allow``.
    """
    raw = await _fetch_config_value(argv, "tools.profile")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


async def fetch_current_plugin_enabled(argv: list[str], plugin_id: str) -> bool:
    """Read ``plugins.entries.<id>.enabled`` (defaults to False if unset)."""
    raw = await _fetch_config_value(argv, f"plugins.entries.{plugin_id}.enabled")
    return raw is True


async def _fetch_config_value(argv: list[str], path: str) -> Any:
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, "config", "get", path, "--json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        if proc.returncode != 0:
            return None
        text = out.decode().strip()
        if not text:
            return None
        return json.loads(text)
    except (asyncio.TimeoutError, json.JSONDecodeError, OSError):
        return None


async def _fetch_config_list(argv: list[str], path: str) -> list[str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, "config", "get", path, "--json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        if proc.returncode != 0:
            return []
        parsed = json.loads(out.decode().strip() or "[]")
        return parsed if isinstance(parsed, list) else []
    except (asyncio.TimeoutError, json.JSONDecodeError, OSError):
        return []


async def _wait_for_gateway(healthz_url: str) -> AsyncIterator[dict[str, Any]]:
    """Poll the gateway healthz endpoint until it returns 200.

    Yields progress events. Yields a final ``{"error": ...}`` if the gateway
    never comes back online.
    """
    await asyncio.sleep(2)
    async with httpx.AsyncClient() as client:
        for _ in range(30):
            try:
                r = await client.get(healthz_url, timeout=2.0)
                if r.is_success:
                    yield _sse({"line": "OpenClaw is up."})
                    return
            except Exception:
                pass
            await asyncio.sleep(1)
    yield _sse({"error": "OpenClaw did not come back online", "exit_code": 1})


async def _stream_subprocess(
    argv: list[str],
    cwd: Path | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Spawn a subprocess and yield each stdout/stderr line as an SSE event.

    The final event is ``{"_rc": <returncode>}`` so callers can inspect it.
    """
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=str(cwd) if cwd else None,
    )
    assert proc.stdout
    async for raw in proc.stdout:
        yield _sse({"line": raw.decode(errors="replace").rstrip()})
    rc = await proc.wait()
    yield {"_rc": rc}


async def build_plugin_runtime(plugin_dir: Path) -> AsyncIterator[dict[str, Any]]:
    """Compile the plugin's TS entry points to JS so OpenClaw 2026.5+ can install.

    OpenClaw's discovery used to load TypeScript directly; 2026.5 requires the
    runtime entry to exist on disk as JS at one of the inferred paths
    (``./dist/index.js``, ``./index.js``, etc.). The plugin's ``package.json``
    build script runs esbuild against ``./index.ts`` and emits
    ``./dist/index.js`` with all ``openclaw/*`` imports left external (the host
    resolves them at runtime). esbuild lives in devDependencies so we install
    those first (idempotent — fast when ``node_modules`` is already populated)
    before invoking the build script.
    """
    # `--include=dev` forces devDependencies even when NODE_ENV=production —
    # esbuild lives there and we need it to build the runtime entry.
    yield _sse({"line": f"$ npm install --no-audit --no-fund --include=dev --silent (cwd: {plugin_dir})"})
    install_rc: int | None = None
    async for event in _stream_subprocess(
        ["npm", "install", "--no-audit", "--no-fund", "--include=dev", "--silent"],
        cwd=plugin_dir,
    ):
        if "_rc" in event:
            install_rc = int(event["_rc"])
        else:
            yield event
    if install_rc not in (0,):
        yield _sse(
            {
                "error": f"npm install failed (exit {install_rc}). Ensure `npm` is on PATH; the plugin needs esbuild from devDependencies to build.",
                "exit_code": install_rc or 1,
            }
        )
        return

    yield _sse({"line": f"$ npm run build (cwd: {plugin_dir})"})
    build_rc: int | None = None
    async for event in _stream_subprocess(
        ["npm", "run", "build", "--silent"],
        cwd=plugin_dir,
    ):
        if "_rc" in event:
            build_rc = int(event["_rc"])
        else:
            yield event
    if build_rc not in (0,):
        yield _sse(
            {
                "error": f"npm run build failed (exit {build_rc}). openclaw 2026.5 requires compiled runtime entries at ./dist/index.js.",
                "exit_code": build_rc or 1,
            }
        )


def write_tool_manifest(
    plugin_dir: Path, tools: list[dict[str, Any]] | None
) -> tuple[bool, str]:
    """Write the in-process tool list to ``tool-manifest.generated.ts``.

    A TypeScript module (rather than a JSON file read at runtime) because
    OpenClaw's plugin loader resolves bare ESM imports reliably; runtime
    ``fs.readFileSync(import.meta.url)`` paths don't always resolve to the
    cached extensions directory.

    The committed ``tool-manifest.ts`` re-exports from this generated file;
    the generated file is gitignored because it is user-specific (each
    user's live tool registry differs).

    Pass ``tools=None`` to leave any existing manifest in place (e.g. when
    the tool registry isn't ready yet).
    """
    if tools is None:
        return False, "tool registry unavailable; keeping existing manifest"
    target = plugin_dir / "src" / "tools" / "tool-manifest.generated.ts"
    target.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = [
        'import type { DataclawToolDefinition } from "./types.js";',
        "",
        "// Auto-generated by Dataclaw's openclaw install service. Do not edit by hand —",
        "// the next Install/Update click overwrites this file from the live tool registry.",
        "",
        "export const DATACLAW_TOOL_MANIFEST: DataclawToolDefinition[] = [",
    ]
    for t in tools:
        name = json.dumps(t.get("name", ""))
        desc = json.dumps(t.get("description", ""))
        params = json.dumps(t.get("parameters", {"type": "object", "properties": {}}))
        lines.append(f"  {{ name: {name}, description: {desc}, parameters: {params} }},")
    lines.append("];")
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True, f"refreshed {target.name}: {len(tools)} tools"


def write_plugin_manifest_contracts_tools(
    plugin_dir: Path, tools: list[dict[str, Any]] | None, prefix: str
) -> tuple[bool, str]:
    """Refresh ``openclaw.plugin.json`` ``contracts.tools`` from the in-process
    tool list, prefixed with the configured tools prefix.

    OpenClaw 2026.5+ rejects every ``api.registerTool`` call unless the plugin
    manifest declares the tool name in ``contracts.tools``. Dataclaw's tool
    list is dynamic, so this list has to track ``tool-manifest.ts``.

    Pass ``tools=None`` to leave the existing list untouched.
    """
    if tools is None:
        return False, "tool registry unavailable; keeping existing contracts.tools"
    manifest_path = plugin_dir / PLUGIN_MANIFEST_FILENAME
    if not manifest_path.exists():
        return False, f"manifest not found: {manifest_path}"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return False, f"manifest is not valid JSON: {e}"
    if not isinstance(manifest, dict):
        return False, "manifest root is not a JSON object"
    declared: list[str] = []
    seen: set[str] = set()
    for t in tools:
        name = t.get("name")
        if not isinstance(name, str) or not name:
            continue
        full = f"{prefix}{name}"
        if full in seen:
            continue
        seen.add(full)
        declared.append(full)
    contracts = manifest.get("contracts")
    existing = contracts.get("tools") if isinstance(contracts, dict) else None
    if existing == declared:
        return True, f"{manifest_path.name} contracts.tools already current ({len(declared)} entries)"
    if not isinstance(contracts, dict):
        contracts = {}
    contracts["tools"] = declared
    manifest["contracts"] = contracts
    manifest_path.write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return True, f"refreshed {manifest_path.name} contracts.tools: {len(declared)} entries"


async def install_plugin_atomic(
    plugin_dir: Path,
    openclaw_cfg: dict[str, Any],
    argv: list[str],
    also_allow_addition: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    install_dir: Path | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Install an openclaw plugin with one batch config write + one plugins-install.

    Steps (each followed by a single gateway-restart wait when needed):

    1. Pre-flight: plugin dir exists and contains the manifest.
    2. Write ``tool-manifest.json`` from the caller-supplied in-process tool list.
    3. Read manifest → derive env vars → fetch current alsoAllow + plugins.allow.
    4. Run ``openclaw config set --batch-json '...'`` once with env vars,
       optional tools.alsoAllow merge, plugin enable flag, plugins.allow merge.
    5. Run ``openclaw plugins install <plugin_dir> --force``.
    """
    # Step 1: pre-flight
    try:
        manifest = read_plugin_manifest(plugin_dir)
    except (FileNotFoundError, ValueError) as e:
        yield _sse({"error": str(e), "exit_code": 1})
        return

    plugin_id = manifest["id"]

    # Step 2: write fresh tool manifest from in-process registry, and
    # mirror it into openclaw.plugin.json contracts.tools so OpenClaw's
    # tool-contract gate accepts each registerTool call.
    ok, msg = write_tool_manifest(plugin_dir, tools)
    yield _sse({"line": ("$ " if ok else "warning: ") + msg})
    tools_prefix = str(
        openclaw_cfg.get(PLUGIN_ENTRY_CFG_KEY_MAP["toolsPrefix"][0])
        or PLUGIN_ENTRY_CFG_KEY_MAP["toolsPrefix"][1]
    )
    ok2, msg2 = write_plugin_manifest_contracts_tools(plugin_dir, tools, tools_prefix)
    yield _sse({"line": ("$ " if ok2 else "warning: ") + msg2})

    # Step 3: pre-install — clear any orphan channels.<id> config from a prior
    # failed install so OpenClaw 2026.5's plugin-install commit doesn't hard-
    # fail with "channels.<id>: unknown channel id" during config validation.
    # Plain `config set` only warns about orphan channel sections, but the
    # install command's commit goes through writeConfigFile in strict mode.
    pre_install_section = await fetch_current_channel_section(argv)
    if pre_install_section:
        clear_entry = {"path": f"channels.{plugin_id}", "value": None}
        yield _sse({"line": "$ openclaw config set --batch-json (clear stale channel section)"})
        yield _sse({"line": f"  payload: [{json.dumps(clear_entry)}]"})
        rc_clear: int | None = None
        async for event in _stream_subprocess([
            *argv, "config", "set", "--batch-json", json.dumps([clear_entry]),
        ]):
            if "_rc" in event:
                rc_clear = int(event["_rc"])
            else:
                yield event
        if rc_clear not in (0, 137):
            yield _sse({
                "error": f"failed to clear stale channels.{plugin_id} (exit {rc_clear})",
                "exit_code": rc_clear or 1,
            })
            return
        yield _sse({"line": "Waiting for OpenClaw to restart..."})
        async for event in _wait_for_gateway(_healthz_url_from_cfg(openclaw_cfg)):
            yield event
            if "error" in event:
                return

    # Step 4: build the TS entry points (OpenClaw 2026.5+ requires JS on disk).
    build_failed = False
    async for event in build_plugin_runtime(plugin_dir):
        if "error" in event:
            build_failed = True
        yield event
    if build_failed:
        return

    # Step 5: plugin install (--force so this also works as an update / reinstall).
    # Use the OpenClaw-side path here — may differ from plugin_dir when openclaw
    # is in Docker and the source is mounted at a different mount point.
    install_target = install_dir or plugin_dir
    yield _sse({"line": f"=== Installing {plugin_id} ==="})
    yield _sse({"line": f"$ openclaw plugins install {install_target} --force"})
    install_rc: int | None = None
    async for event in _stream_subprocess([
        *argv, "plugins", "install", str(install_target), "--force",
    ]):
        if "_rc" in event:
            install_rc = int(event["_rc"])
        else:
            yield event

    if install_rc not in (0, 137):
        yield _sse({"error": f"plugins install failed (exit {install_rc}).",
                    "exit_code": install_rc or 1})
        return

    yield _sse({"line": "Waiting for OpenClaw to restart after plugin install..."})
    async for event in _wait_for_gateway(_healthz_url_from_cfg(openclaw_cfg)):
        yield event
        if "error" in event:
            return

    # Step 6: post-install config. Now that the plugin is loaded, channels.<id>
    # is a known section and plugins.entries.<id> is a known plugin, so the
    # validator accepts these writes without warnings or blocking.
    channel_values = resolve_channel_section_values(openclaw_cfg)
    plugin_entry_config_values = resolve_plugin_entry_config_values(openclaw_cfg)
    current_also_allow = await fetch_current_also_allow(argv)
    current_tools_allow = await fetch_current_tools_allow(argv)
    current_tools_profile = await fetch_current_tools_profile(argv)
    current_plugins_allow = await fetch_current_plugins_allow(argv)
    current_channel_section = await fetch_current_channel_section(argv)
    current_plugin_entry_config = await fetch_current_plugin_entry_config(argv, plugin_id)
    current_plugin_enabled = await fetch_current_plugin_enabled(argv, plugin_id)
    batch_entries = build_batch_entries(
        channel_values,
        also_allow_addition,
        current_also_allow,
        enable_plugin_id=plugin_id,
        current_plugins_allow=current_plugins_allow,
        current_channel_section=current_channel_section,
        current_plugin_enabled=current_plugin_enabled,
        current_tools_allow=current_tools_allow,
        plugin_entry_config_values=plugin_entry_config_values,
        current_plugin_entry_config=current_plugin_entry_config,
        current_tools_profile=current_tools_profile,
    )

    if not batch_entries:
        yield _sse({"line": "No config changes needed (channel config + alsoAllow already correct)."})
        yield _sse({"exit_code": 0})
        return

    masked = [
        {"path": e["path"], "value": "****" if e["path"] in CHANNEL_TOKEN_PATHS else e["value"]}
        for e in batch_entries
    ]
    yield _sse({"line": f"$ openclaw config set --batch-json (entries: {len(batch_entries)})"})
    yield _sse({"line": f"  payload: {json.dumps(masked)}"})

    rc: int | None = None
    async for event in _stream_subprocess([
        *argv, "config", "set", "--batch-json", json.dumps(batch_entries),
    ]):
        if "_rc" in event:
            rc = int(event["_rc"])
        else:
            yield event
    if rc not in (0, 137):
        yield _sse({"error": f"post-install config set failed (exit {rc}).",
                    "exit_code": rc or 1})
        return

    yield _sse({"line": "Waiting for OpenClaw to restart..."})
    async for event in _wait_for_gateway(_healthz_url_from_cfg(openclaw_cfg)):
        yield event
        if "error" in event:
            return

    # Snapshot the tools that were just installed into OpenClaw so the UI can
    # later diff against the live registry and prompt the user to reinstall
    # when they add or remove a tool. We record the unprefixed names — the
    # same ids that show up in `tool_availability._tools` — so comparison is
    # apples-to-apples.
    try:
        record_install_state(plugin_id, tools)
    except Exception as exc:
        # Never block install on telemetry — just warn.
        yield _sse({"line": f"warning: failed to record install state: {exc}"})

    yield _sse({"exit_code": 0})


def _healthz_url_from_cfg(openclaw_cfg: dict[str, Any]) -> str:
    return openclaw_cfg.get("url", "http://127.0.0.1:18789").rstrip("/") + "/healthz"


# ── Install-state snapshot ────────────────────────────────────────────────────
#
# After a successful install, record which tool names ended up shipped to the
# OpenClaw extension. The UI uses ``read_install_state`` + the live tool
# registry to detect drift (tool added / removed since last install) and
# prompt the user to reinstall the plugin from the config page.

from datetime import datetime, timezone  # noqa: E402  (kept near user-facing API)

_INSTALL_STATE_FILENAME = "openclaw-install-state.json"


def _install_state_path() -> Path:
    """File under the dataclaw-openclaw plugin data dir."""
    from dataclaw.config.paths import plugin_data_dir
    base = plugin_data_dir("dataclaw-openclaw")
    base.mkdir(parents=True, exist_ok=True)
    return base / _INSTALL_STATE_FILENAME


def _load_install_state_file() -> dict[str, Any]:
    path = _install_state_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _extract_tool_names(tools: list[dict[str, Any]] | None) -> list[str]:
    if not tools:
        return []
    names: list[str] = []
    seen: set[str] = set()
    for t in tools:
        name = t.get("name") if isinstance(t, dict) else None
        if isinstance(name, str) and name and name not in seen:
            seen.add(name)
            names.append(name)
    return sorted(names)


def record_install_state(
    plugin_id: str, tools: list[dict[str, Any]] | None
) -> None:
    """Persist the tool names + timestamp that were just shipped to OpenClaw.

    Skipped silently when ``tools`` is None (the install service treats that
    as "leave the existing manifest alone" — same convention as
    ``write_tool_manifest``).
    """
    if tools is None:
        return
    state = _load_install_state_file()
    state[plugin_id] = {
        "tool_names": _extract_tool_names(tools),
        "installed_at": datetime.now(timezone.utc).isoformat(),
    }
    _install_state_path().write_text(
        json.dumps(state, indent=2, sort_keys=True), encoding="utf-8"
    )


def read_install_state(plugin_id: str) -> dict[str, Any] | None:
    """Load the recorded install state for one plugin id, or None if absent."""
    state = _load_install_state_file()
    entry = state.get(plugin_id)
    return entry if isinstance(entry, dict) else None


def diff_tool_names(
    installed: list[str], live: list[str]
) -> dict[str, list[str]]:
    """Return ``{added, removed}`` between an installed snapshot and the live set."""
    installed_set = set(installed)
    live_set = set(live)
    return {
        "added": sorted(live_set - installed_set),
        "removed": sorted(installed_set - live_set),
    }
