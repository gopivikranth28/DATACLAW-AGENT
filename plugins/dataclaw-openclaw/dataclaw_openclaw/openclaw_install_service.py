"""OpenClaw plugin install orchestration.

Pure-ish service module: parses the plugin manifest, resolves the plugin's
OpenClaw config values from Dataclaw config, builds an atomic batch-config
payload, and runs the ``openclaw plugins install`` + ``openclaw config set
--batch-json`` sequence through subprocesses. Yields SSE-shaped event dicts so the FastAPI router can
forward them verbatim to the UI.

Designed to be unit-testable without FastAPI: import the module and feed it
plain dicts/paths.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)


PLUGIN_MANIFEST_FILENAME = "openclaw.plugin.json"

# Report publication is a multi-tool transaction.  A stale generated manifest
# used to omit fields added to the Dataclaw tools, letting an OpenClaw agent
# discover only a partial flow (for example it could not pass the publish
# receipt into publish_artifact).  The installer owns the generated manifest,
# so fail before modifying OpenClaw when the in-process registry is internally
# inconsistent.
_REPORT_TOOL_REQUIRED_PROPERTIES: dict[str, set[str]] = {
    "report_design_report": {"visual_author"},
    "report_publish": {"require_visual_review"},
    "publish_artifact": {"report_receipt_path"},
}


# The plugin reads its connection settings from structured OpenClaw config
# (no `process.env` fallback) — see `src/channel/config.ts` and
# `src/tools/config.ts` — so the installer writes them there.
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

# Oldest OpenClaw the plugin is built and tested against. Keep in sync with
# `openclaw.install.minHostVersion` in openclaw-plugins/dataclaw/package.json
# and OPENCLAW_VERSION in Dockerfile.bundled.
MIN_OPENCLAW_VERSION = "2026.10.7"

_OPENCLAW_VERSION_RE = re.compile(r"(\d{4})\.(\d{1,2})\.(\d{1,3})(?:-([0-9A-Za-z.]+))?")


def parse_openclaw_version(text: str) -> tuple[int, int, int, bool] | None:
    """Parse ``openclaw --version`` output into ``(year, month, patch, prerelease)``.

    The CLI prints the version inside a banner (``OpenClaw 2026.10.7 (abc1234)``),
    so search rather than match. ``-beta.N``/``-rc.N`` suffixes are pre-releases
    of that version; a purely numeric suffix (``2026.5.3-1``) is a re-publish of
    it and compares equal.
    """
    m = _OPENCLAW_VERSION_RE.search(text or "")
    if not m:
        return None
    suffix = m.group(4) or ""
    prerelease = bool(suffix) and not suffix.isdigit()
    return int(m.group(1)), int(m.group(2)), int(m.group(3)), prerelease


def is_supported_openclaw_version(text: str) -> bool | None:
    """True/False against MIN_OPENCLAW_VERSION, or None when unparseable."""
    found = parse_openclaw_version(text)
    if found is None:
        return None
    minimum = parse_openclaw_version(MIN_OPENCLAW_VERSION)
    assert minimum is not None
    # A pre-release sorts below its release: (y, m, p, not prerelease).
    return (*found[:3], not found[3]) >= (*minimum[:3], not minimum[3])


async def fetch_openclaw_version(argv: list[str]) -> str | None:
    """Run ``openclaw --version``; return its stdout, or None on failure."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
    except (asyncio.TimeoutError, OSError):
        return None
    if proc.returncode != 0:
        return None
    return out.decode(errors="replace").strip() or None


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
    secrets: list[str | None] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Spawn a subprocess and yield each stdout/stderr line as an SSE event.

    Lines are redacted (``secrets`` plus anything shaped like an OpenRouter
    key) before they leave this function: ``config set --batch-json`` carries
    secret values on argv and OpenClaw can echo them back in error output.

    The final event is ``{"_rc": <returncode>}`` so callers can inspect it.
    """
    from dataclaw_openclaw.openrouter_config import redact

    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=str(cwd) if cwd else None,
    )
    assert proc.stdout
    async for raw in proc.stdout:
        yield _sse({"line": redact(raw.decode(errors="replace").rstrip(), secrets or ())})
    rc = await proc.wait()
    yield {"_rc": rc}


async def build_plugin_runtime(plugin_dir: Path) -> AsyncIterator[dict[str, Any]]:
    """Compile the plugin's TS entry point to ``dist/index.js``.

    OpenClaw installs require compiled JS (``openclaw.runtimeExtensions`` in
    the plugin's package.json). The ``build`` script runs esbuild against
    ``./index.ts`` with all ``openclaw/*`` imports left external (the host
    resolves them at runtime). esbuild lives in devDependencies so we install
    those first (idempotent — fast when ``node_modules`` is already populated)
    before invoking the build script.
    """
    # `--include=dev` forces devDependencies even when NODE_ENV=production —
    # esbuild lives there and we need it to build the runtime entry.
    # `--ignore-scripts`: the `openclaw` devDependency (types only) has a
    # preinstall that hard-fails on Node < 24.22.1, which would block the build
    # on a host whose Node only runs Dataclaw. esbuild works without its
    # postinstall (that step only swaps in the native binary for speed).
    npm_install = ["npm", "install", "--no-audit", "--no-fund", "--include=dev", "--ignore-scripts", "--silent"]
    yield _sse({"line": f"$ {' '.join(npm_install)} (cwd: {plugin_dir})"})
    install_rc: int | None = None
    async for event in _stream_subprocess(
        npm_install,
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
                "error": f"npm run build failed (exit {build_rc}). OpenClaw installs the compiled runtime entry at ./dist/index.js.",
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


def validate_report_tool_manifest(tools: list[dict[str, Any]] | None) -> list[str]:
    """Return report-flow schema gaps in a live tool-registry snapshot.

    Tool availability is intentionally dynamic, so absent report tools are not
    errors.  The *registry snapshot* itself is mandatory, however: reusing an
    on-disk generated manifest is precisely how an older, partial contract
    was installed. Once a report tool is present, its schema must expose all
    parameters needed for the governed storyboard → publish → artifact
    transaction.
    """
    if tools is None:
        return ["live Dataclaw tool registry is unavailable"]
    by_name = {
        str(tool.get("name") or ""): tool
        for tool in tools
        if isinstance(tool, dict) and str(tool.get("name") or "")
    }
    issues: list[str] = []
    for name, required in _REPORT_TOOL_REQUIRED_PROPERTIES.items():
        tool = by_name.get(name)
        if not tool:
            continue
        parameters = tool.get("parameters") if isinstance(tool.get("parameters"), dict) else {}
        properties = parameters.get("properties") if isinstance(parameters.get("properties"), dict) else {}
        missing = sorted(field for field in required if field not in properties)
        if missing:
            issues.append(f"{name} missing properties: {', '.join(missing)}")
    if "report_publish" in by_name and "report_review_visuals" not in by_name:
        issues.append("report_publish is present but report_review_visuals is unavailable")
    return issues


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


# Files copied into the install package. Everything else in the plugin source
# dir (node_modules with the full `openclaw` devDependency tree, TS sources,
# lockfile) is build-time only; copying it made `plugins install` ~10x slower.
INSTALL_PACKAGE_DIRNAME = ".openclaw-package"
_INSTALL_PACKAGE_FILES = ("package.json", PLUGIN_MANIFEST_FILENAME, "HOOK.md")
_INSTALL_PACKAGE_DIRS = ("dist", "skills")


def stage_install_package(plugin_dir: Path) -> Path:
    """Copy the runtime files of the built plugin into a clean package dir.

    Returns the staged directory (``<plugin_dir>/.openclaw-package``), which is
    what ``openclaw plugins install`` receives. Raises ``FileNotFoundError``
    when the build output is missing.
    """
    entry = plugin_dir / "dist" / "index.js"
    if not entry.is_file():
        raise FileNotFoundError(f"Built runtime entry not found: {entry}")
    stage = plugin_dir / INSTALL_PACKAGE_DIRNAME
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir()
    for name in _INSTALL_PACKAGE_FILES:
        src = plugin_dir / name
        if src.is_file():
            shutil.copy2(src, stage / name)
    for name in _INSTALL_PACKAGE_DIRS:
        src = plugin_dir / name
        if src.is_dir():
            shutil.copytree(src, stage / name)
    return stage


def describe_declared_capabilities(manifest: dict[str, Any]) -> str:
    """One-line summary of what the manifest asks OpenClaw to accept.

    OpenClaw records the accepted surface (channels, tools, skills, hooks, …)
    at install time and requires fresh consent whenever it widens — e.g. when
    a new Dataclaw tool lands in ``contracts.tools``.
    """
    channels = manifest.get("channels") or []
    contracts = manifest.get("contracts") if isinstance(manifest.get("contracts"), dict) else {}
    tools = contracts.get("tools") or []
    skills = manifest.get("skills") or []
    return (
        f"channels={','.join(channels) or 'none'} "
        f"tools={len(tools)} "
        f"skills={','.join(skills) or 'none'}"
    )


async def install_plugin_atomic(
    plugin_dir: Path,
    openclaw_cfg: dict[str, Any],
    argv: list[str],
    also_allow_addition: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    install_dir: Path | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Install an openclaw plugin with one plugins-install + one batch config write.

    Works the same whether or not the gateway is running: with a running
    gateway, ``plugins install`` applies the new plugin generation through it
    and ``config set`` hot-reloads; without one (the bundled bootstrap), both
    are saved for the next gateway start.

    1. Pre-flight: manifest present, live tool registry consistent, OpenClaw
       version supported.
    2. Write ``tool-manifest.generated.ts`` + ``contracts.tools``.
    3. Build ``dist/index.js`` and stage the runtime files.
    4. ``openclaw plugins install <staged> --force --accept-capabilities``.
    5. ``openclaw config set --batch-json '...'`` with only the values that
       would change (channel connection settings, tools knobs, tool allowlist,
       plugin enable flag, plugins.allow merge).
    """
    # Step 1: pre-flight
    try:
        manifest = read_plugin_manifest(plugin_dir)
    except (FileNotFoundError, ValueError) as e:
        yield _sse({"error": str(e), "exit_code": 1})
        return

    plugin_id = manifest["id"]

    schema_gaps = validate_report_tool_manifest(tools)
    if schema_gaps:
        yield _sse({
            "error": "OpenClaw tool-manifest sync refused an incomplete report-flow schema: " + "; ".join(schema_gaps),
            "exit_code": 1,
        })
        return

    version_text = await fetch_openclaw_version(argv)
    supported = is_supported_openclaw_version(version_text or "")
    if supported is False:
        yield _sse({
            "error": (
                f"OpenClaw {version_text} is older than the supported minimum "
                f"{MIN_OPENCLAW_VERSION}. Upgrade OpenClaw "
                f"(npm install -g openclaw@{MIN_OPENCLAW_VERSION}) and retry."
            ),
            "exit_code": 1,
        })
        return
    if supported is None:
        yield _sse({
            "line": f"warning: could not determine the OpenClaw version (need >= {MIN_OPENCLAW_VERSION}); continuing",
        })
    else:
        yield _sse({"line": f"OpenClaw version: {version_text}"})

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

    # Step 3: build the TS entry point, then stage only the runtime files.
    build_failed = False
    async for event in build_plugin_runtime(plugin_dir):
        if "error" in event:
            build_failed = True
        yield event
    if build_failed:
        return
    try:
        stage_install_package(plugin_dir)
    except OSError as e:
        yield _sse({"error": f"failed to stage the plugin package: {e}", "exit_code": 1})
        return

    # Step 4: plugin install. --force confirms the local (non-ClawHub) source
    # and replaces an existing install. --accept-capabilities records consent
    # for the manifest's declared surface: the operator clicking Install (or
    # the bundled bootstrap the operator started) is that consent, and the
    # surface widens whenever a Dataclaw tool is added, so it is needed on
    # reinstalls too. Use the OpenClaw-side path — it may differ from
    # plugin_dir when openclaw runs in Docker with the source mounted elsewhere.
    install_target = (install_dir or plugin_dir) / INSTALL_PACKAGE_DIRNAME
    refreshed = read_plugin_manifest(plugin_dir)
    yield _sse({"line": f"=== Installing {plugin_id} ==="})
    yield _sse({"line": f"Accepting declared capabilities: {describe_declared_capabilities(refreshed)}"})
    yield _sse({"line": f"$ openclaw plugins install {install_target} --force --accept-capabilities"})
    install_rc: int | None = None
    consent_refused = False
    async for event in _stream_subprocess([
        *argv, "plugins", "install", str(install_target), "--force", "--accept-capabilities",
    ]):
        if "_rc" in event:
            install_rc = int(event["_rc"])
        else:
            # The CLI exits 0 when it refuses an install for missing consent.
            if "was not installed" in str(event.get("line", "")):
                consent_refused = True
            yield event

    if install_rc not in (0, 137) or consent_refused:
        yield _sse({"error": f"plugins install failed (exit {install_rc}).",
                    "exit_code": install_rc or 1})
        return

    yield _sse({"line": "Waiting for OpenClaw to apply the plugin..."})
    async for event in _wait_for_gateway(_healthz_url_from_cfg(openclaw_cfg)):
        yield event
        if "error" in event:
            return

    # Step 5: post-install config. Now that the plugin is installed,
    # channels.<id> is a known section and plugins.entries.<id> is a known
    # plugin, so the validator accepts these writes.
    channel_values = resolve_channel_section_values(openclaw_cfg)
    plugin_entry_config_values = resolve_plugin_entry_config_values(openclaw_cfg)
    current_also_allow = await fetch_current_also_allow(argv)
    current_tools_allow = await fetch_current_tools_allow(argv)
    current_tools_profile = await fetch_current_tools_profile(argv)
    current_plugins_allow = await fetch_current_plugins_allow(argv)
    # `config get` redacts secrets, so the token never compares equal and is
    # rewritten each time; an unchanged value is a no-op write in OpenClaw.
    current_channel_section = await fetch_current_channel_section(argv)
    current_plugin_entry_config = await fetch_current_plugin_entry_config(argv, plugin_id)
    # Reinstalls preserve an authored `enabled: false` (e.g. left behind by
    # `plugins uninstall`), so the enable flag is part of the batch.
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
    else:
        masked = [
            {"path": e["path"], "value": "****" if e["path"] in CHANNEL_TOKEN_PATHS else e["value"]}
            for e in batch_entries
        ]
        yield _sse({"line": f"$ openclaw config set --batch-json (entries: {len(batch_entries)})"})
        yield _sse({"line": f"  payload: {json.dumps(masked)}"})

        rc: int | None = None
        secret_values = [
            str(e["value"]) for e in batch_entries if e["path"] in CHANNEL_TOKEN_PATHS
        ]
        async for event in _stream_subprocess([
            *argv, "config", "set", "--batch-json", json.dumps(batch_entries),
        ], secrets=secret_values):
            if "_rc" in event:
                rc = int(event["_rc"])
            else:
                yield event
        if rc not in (0, 137):
            yield _sse({"error": f"post-install config set failed (exit {rc}).",
                        "exit_code": rc or 1})
            return

        yield _sse({"line": "Waiting for OpenClaw to apply the config..."})
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
    url = openclaw_cfg.get("url") or "http://127.0.0.1:18789"
    return url.rstrip("/") + "/healthz"


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
