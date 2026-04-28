"""OpenClaw plugin installation and management endpoints.

Provides endpoints to check plugin status, install plugins, fetch gateway
tokens, and debug the OpenClaw directory layout.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shlex
import shutil
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from starlette.responses import StreamingResponse

logger = logging.getLogger(__name__)

router = APIRouter()

PLUGIN_IDS = ["dataclaw-tools", "dataclaw-frontend"]

# Default path to the TypeScript plugin sources (relative to this file)
_DEFAULT_PLUGINS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "openclaw-plugins"


def _get_openclaw_config(request: Request) -> dict[str, Any]:
    """Read the openclaw plugin config from app state."""
    cfg: Any = request.app.state.config
    return cfg.plugins.get("openclaw", {})


def _openclaw_argv(cfg: dict[str, Any]) -> list[str]:
    """Build the base openclaw command argv, validating that it exists."""
    cmd = cfg.get("openclaw_cmd", "openclaw")
    argv = shlex.split(cmd)
    if not shutil.which(argv[0]):
        raise HTTPException(
            status_code=503,
            detail=f"Command not found: {argv[0]!r}. Check openclaw_cmd in Config → OpenClaw.",
        )
    return argv


def _plugin_env_vars(plugin_id: str, cfg: dict[str, Any]) -> dict[str, str]:
    """Return env var key→value pairs to set before installing a plugin."""
    if plugin_id == "dataclaw-tools":
        env: dict[str, str] = {}
        api_url = cfg.get("tools_api_url", "http://localhost:8000")
        if api_url:
            env["DATACLAW_API_URL"] = api_url
        token = cfg.get("tools_token", "")
        if token:
            env["DATACLAW_TOOLS_TOKEN"] = token
        prefix = cfg.get("tools_prefix", "dataclaw_")
        if prefix:
            env["DATACLAW_TOOLS_PREFIX"] = prefix
        return env
    if plugin_id == "dataclaw-frontend":
        env2: dict[str, str] = {}
        token = cfg.get("frontend_token", "")
        if token:
            env2["DATACLAW_FRONTEND_TOKEN"] = token
        return env2
    return {}


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


# ---------------------------------------------------------------------------
# OpenClaw CLI check and installation
# ---------------------------------------------------------------------------

DEFAULT_SOUL = """\
# SOUL.md

## Core Truths

**Be genuinely helpful, not performatively helpful.** Skip the "Great question!" \
and "I'd be happy to help!" — just help. Actions speak louder than filler words.

**Have opinions.** You're allowed to disagree, prefer things, find stuff amusing \
or boring. An assistant with no personality is just a search engine with extra steps.

**Be resourceful before asking.** Try to figure it out. Read the file. Check the \
context. Search for it. Then ask if you're stuck. The goal is to come back with \
answers, not questions.

**Earn trust through competence.** Be careful with external actions (emails, \
tweets, anything public). Be bold with internal ones (reading, organizing, learning).

## Boundaries

- Private things stay private. Period.
- When in doubt, ask before acting externally.
- Never send half-baked replies to messaging surfaces.

## Vibe

Be the assistant you'd actually want to talk to. Concise when needed, thorough \
when it matters. Not a corporate drone. Not a sycophant. Just... good.

## Continuity

Each session, you wake up fresh. These files are your memory. Read them. Update \
them. They're how you persist.
"""

DEFAULT_IDENTITY = """\
# IDENTITY.md

- **Name:** Dataclaw
- **Creature:** AI data scientist
- **Vibe:** Sharp, resourceful, direct
"""


@router.get("/check")
async def check_openclaw(request: Request):
    """Check whether the OpenClaw CLI is installed and reachable."""
    cfg = _get_openclaw_config(request)
    cmd = cfg.get("openclaw_cmd", "openclaw")
    cmd_parts = shlex.split(cmd)
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd_parts, "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
        if proc.returncode == 0:
            version = stdout_bytes.decode().strip()
            return {"installed": True, "version": version}
        return {"installed": False, "version": None}
    except (FileNotFoundError, asyncio.TimeoutError, OSError):
        return {"installed": False, "version": None}


@router.post("/install")
async def install_openclaw(request: Request):
    """Install OpenClaw CLI, run onboard, wait for gateway, and write workspace files.

    Streams SSE progress events. Non-interactive — uses --non-interactive onboard flags.
    """
    cfg = _get_openclaw_config(request)
    gateway_port = "18789"
    # Extract port from configured URL if present
    url = cfg.get("url", "")
    if url:
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            if parsed.port:
                gateway_port = str(parsed.port)
        except Exception:
            pass

    async def _stream():
        # Build an env that prevents OpenClaw from detecting a headless environment.
        # The embedded UI IS the user's local interface, so we fake a display.
        proc_env = os.environ.copy()
        proc_env["TERM"] = "xterm-256color"
        proc_env.setdefault("DISPLAY", ":0")

        # Step 1: Install OpenClaw via curl script
        yield _sse({"line": "=== Step 1: Install OpenClaw ==="})

        install_proc = await asyncio.create_subprocess_exec(
            "bash", "-c",
            "curl -fsSL https://openclaw.ai/install.sh | bash -s -- --no-onboard",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=proc_env,
        )
        assert install_proc.stdout
        async for raw in install_proc.stdout:
            yield _sse({"line": raw.decode(errors="replace").rstrip()})
        rc = await install_proc.wait()
        if rc != 0:
            yield _sse({"error": f"OpenClaw install failed (exit {rc})", "exit_code": rc})
            return

        # Determine the openclaw command — check common locations
        openclaw_cmd = cfg.get("openclaw_cmd", "openclaw")
        openclaw_parts = shlex.split(openclaw_cmd)
        if not shutil.which(openclaw_parts[0]):
            # Try common post-install paths
            for candidate in [
                Path.home() / ".openclaw" / "bin" / "openclaw",
                Path(os.popen("npm prefix -g 2>/dev/null").read().strip()) / "bin" / "openclaw",
            ]:
                if candidate.exists():
                    openclaw_parts = [str(candidate)]
                    yield _sse({"line": f"Found openclaw at {candidate}"})
                    break
            else:
                yield _sse({"error": "openclaw not found in PATH after install. Restart your shell and try again.", "exit_code": 1})
                return

        # Step 2: Onboard (non-interactive)
        yield _sse({"line": ""})
        yield _sse({"line": "=== Step 2: Configure OpenClaw ==="})
        onboard_argv = [
            *openclaw_parts, "onboard",
            "--non-interactive", "--accept-risk",
            "--mode", "local",
            "--secret-input-mode", "plaintext",
            "--gateway-port", gateway_port,
            "--gateway-bind", "loopback",
            "--install-daemon",
            "--daemon-runtime", "node",
            "--skip-skills",
        ]
        yield _sse({"line": f"$ {' '.join(onboard_argv)}"})
        onboard_proc = await asyncio.create_subprocess_exec(
            *onboard_argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=proc_env,
        )
        assert onboard_proc.stdout
        async for raw in onboard_proc.stdout:
            yield _sse({"line": raw.decode(errors="replace").rstrip()})
        rc2 = await onboard_proc.wait()
        if rc2 != 0:
            yield _sse({"error": f"openclaw onboard failed (exit {rc2})", "exit_code": rc2})
            return

        # Step 3: Wait for gateway
        yield _sse({"line": ""})
        yield _sse({"line": "=== Step 3: Waiting for gateway ==="})
        healthz_url = f"http://127.0.0.1:{gateway_port}/healthz"
        gateway_up = False
        async with httpx.AsyncClient() as client:
            for i in range(15):
                try:
                    r = await client.get(healthz_url, timeout=2.0)
                    if r.is_success:
                        gateway_up = True
                        yield _sse({"line": "Gateway is up."})
                        break
                except Exception:
                    pass
                yield _sse({"line": f"  waiting... ({i + 1}/15)"})
                await asyncio.sleep(1)

        if not gateway_up:
            yield _sse({"line": "Gateway not up, starting it..."})
            start_proc = await asyncio.create_subprocess_exec(
                *openclaw_parts, "gateway", "start",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                env=proc_env,
            )
            try:
                await asyncio.wait_for(start_proc.wait(), timeout=10)
            except asyncio.TimeoutError:
                pass
            await asyncio.sleep(3)

            async with httpx.AsyncClient() as client:
                try:
                    r = await client.get(healthz_url, timeout=3.0)
                    if r.is_success:
                        gateway_up = True
                        yield _sse({"line": "Gateway is up."})
                except Exception:
                    pass

            if not gateway_up:
                yield _sse({"error": "Gateway did not start", "exit_code": 1})
                return

        # Step 4: Write default workspace files
        yield _sse({"line": ""})
        yield _sse({"line": "=== Step 4: Bootstrap workspace ==="})
        workspace = Path.home() / ".openclaw" / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        for name, content in [("SOUL.md", DEFAULT_SOUL), ("IDENTITY.md", DEFAULT_IDENTITY)]:
            path = workspace / name
            if path.exists():
                yield _sse({"line": f"  {name}: already exists, skipped"})
            else:
                path.write_text(content, encoding="utf-8")
                yield _sse({"line": f"  {name}: created"})

        yield _sse({"line": ""})
        yield _sse({"line": "=== OpenClaw installation complete ==="})

        # Check version
        try:
            ver_proc = await asyncio.create_subprocess_exec(
                *openclaw_parts, "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            ver_out, _ = await asyncio.wait_for(ver_proc.communicate(), timeout=5)
            if ver_proc.returncode == 0:
                yield _sse({"line": f"OpenClaw version: {ver_out.decode().strip()}"})
        except Exception:
            pass

        yield _sse({"exit_code": 0})

    return StreamingResponse(_stream(), media_type="text/event-stream")


BOOTSTRAP_SCRIPT = """\
#!/bin/bash
set -e

echo "=== Step 1: Install OpenClaw ==="
curl -fsSL https://openclaw.ai/install.sh | bash -s -- --no-onboard

export PATH="$(npm prefix -g 2>/dev/null)/bin:$HOME/.openclaw/bin:$PATH"
hash -r 2>/dev/null

echo ""
echo "=== Step 2: Configure OpenClaw ==="
openclaw onboard --non-interactive --accept-risk \\
  --mode local \\
  --secret-input-mode plaintext \\
  --gateway-port {gateway_port} \\
  --gateway-bind loopback \\
  --install-daemon \\
  --daemon-runtime node \\
  --skip-skills

echo ""
echo "=== Step 3: Waiting for gateway ==="
for i in $(seq 1 15); do
  if curl -sf http://127.0.0.1:{gateway_port}/healthz > /dev/null 2>&1; then
    echo "Gateway is up."
    break
  fi
  echo "  waiting... ($i/15)"
  sleep 1
done

echo ""
echo "=== Step 4: Bootstrap workspace ==="
WORKSPACE="$HOME/.openclaw/workspace"
mkdir -p "$WORKSPACE"

cat > "$WORKSPACE/SOUL.md" << 'SOULEOF'
# SOUL.md

## Core Truths

**Be genuinely helpful, not performatively helpful.** Skip the "Great question!"
and "I'd be happy to help!" - just help. Actions speak louder than filler words.

**Have opinions.** You're allowed to disagree, prefer things, find stuff amusing
or boring. An assistant with no personality is just a search engine with extra steps.

**Be resourceful before asking.** Try to figure it out. Read the file. Check the
context. Search for it. Then ask if you're stuck. The goal is to come back with
answers, not questions.

**Earn trust through competence.** Be careful with external actions (emails,
tweets, anything public). Be bold with internal ones (reading, organizing, learning).

## Boundaries

- Private things stay private. Period.
- When in doubt, ask before acting externally.
- Never send half-baked replies to messaging surfaces.

## Vibe

Be the assistant you'd actually want to talk to. Concise when needed, thorough
when it matters. Not a corporate drone. Not a sycophant. Just... good.

## Continuity

Each session, you wake up fresh. These files are your memory. Read them. Update
them. They're how you persist.
SOULEOF
echo "  SOUL.md: written"

cat > "$WORKSPACE/IDENTITY.md" << 'IDEOF'
# IDENTITY.md

- **Name:** Dataclaw
- **Creature:** AI data scientist
- **Vibe:** Sharp, resourceful, direct
IDEOF
echo "  IDENTITY.md: written"
echo "  Workspace ready."

echo ""
echo "=== Step 5: Configure model provider ==="
openclaw models auth login --set-default

echo ""
echo "=== Step 6: Restarting gateway ==="
openclaw gateway stop 2>/dev/null || true
sleep 1
openclaw gateway start &
sleep 3
GATEWAY_UP=0
for i in $(seq 1 20); do
  if curl -sf http://127.0.0.1:{gateway_port}/healthz > /dev/null 2>&1; then
    GATEWAY_UP=1
    echo "Gateway is up."
    break
  fi
  echo "  waiting... ($i/20)"
  sleep 2
done

if [ "$GATEWAY_UP" = "0" ]; then
  echo "Warning: Gateway did not come back up. Try: openclaw gateway start"
fi

echo ""
echo "=== OpenClaw setup complete ==="
"""


@router.post("/bootstrap-script")
async def generate_bootstrap_script(request: Request):
    """Write the OpenClaw bootstrap script to a temp file and return its path.

    The terminal runs this as a file so stdin stays connected to the PTY,
    allowing interactive commands (model auth) to work.
    """
    cfg = _get_openclaw_config(request)
    gateway_port = "18789"
    url = cfg.get("url", "")
    if url:
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            if parsed.port:
                gateway_port = str(parsed.port)
        except Exception:
            pass

    script = BOOTSTRAP_SCRIPT.format(
        gateway_port=gateway_port,
    )

    script_path = Path("/tmp/dataclaw-bootstrap.sh")
    script_path.write_text(script, encoding="utf-8")
    script_path.chmod(0o755)

    return {"script": str(script_path)}


@router.post("/bootstrap-workspace")
async def bootstrap_workspace():
    """Write default SOUL.md and IDENTITY.md to the OpenClaw workspace.

    Always overwrites with Dataclaw defaults.
    """
    workspace = Path.home() / ".openclaw" / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    written = []
    for name, content in [("SOUL.md", DEFAULT_SOUL), ("IDENTITY.md", DEFAULT_IDENTITY)]:
        path = workspace / name
        path.write_text(content, encoding="utf-8")
        written.append(name)
    return {"written": written}


# ---------------------------------------------------------------------------
# Plugin status and installation
# ---------------------------------------------------------------------------

@router.get("/plugins/{plugin_id}/status")
async def plugin_status(plugin_id: str, request: Request):
    if plugin_id not in PLUGIN_IDS:
        raise HTTPException(status_code=404, detail="Unknown plugin")

    cfg = _get_openclaw_config(request)
    argv = _openclaw_argv(cfg)

    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, "plugins", "inspect", plugin_id,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout_bytes, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
        output = stdout_bytes.decode(errors="replace")
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="openclaw plugins inspect timed out")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to run openclaw: {e}")

    if "Plugin not found" in output:
        return {"installed": False}

    status_line = next(
        (line.split("Status:", 1)[1].strip() for line in output.splitlines() if "Status:" in line),
        None,
    )
    version_line = next(
        (line.split("Version:", 1)[1].strip() for line in output.splitlines() if "Version:" in line),
        None,
    )
    return {"installed": True, "status": status_line, "version": version_line}


@router.post("/plugins/{plugin_id}/install")
async def install_plugin(plugin_id: str, request: Request):
    if plugin_id not in PLUGIN_IDS:
        raise HTTPException(status_code=404, detail="Unknown plugin")

    cfg = _get_openclaw_config(request)
    argv = _openclaw_argv(cfg)

    plugins_source_dir = Path(cfg.get("plugins_source_dir", str(_DEFAULT_PLUGINS_DIR)))
    plugin_dir = plugins_source_dir / plugin_id

    env_vars = _plugin_env_vars(plugin_id, cfg)
    gateway_url = cfg.get("url", "http://127.0.0.1:18789")
    healthz_url = gateway_url.rstrip("/") + "/healthz"

    async def _run(run_argv: list[str]) -> tuple[asyncio.StreamReader, asyncio.subprocess.Process]:
        proc = await asyncio.create_subprocess_exec(
            *run_argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        assert proc.stdout
        return proc.stdout, proc

    async def _restart_and_wait() -> tuple[bool, list[str]]:
        """Restart the OpenClaw gateway and wait for it to come back."""
        chunks: list[str] = []

        chunks.append(_sse({"line": f"$ {' '.join(argv)} gateway restart"}))
        restart_proc = await asyncio.create_subprocess_exec(
            *argv, "gateway", "restart",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            rc = await asyncio.wait_for(restart_proc.wait(), timeout=15)
        except asyncio.TimeoutError:
            restart_proc.kill()
            rc = -1

        if rc != 0:
            chunks.append(_sse({"line": "Restart failed, trying gateway start..."}))
            start_proc = await asyncio.create_subprocess_exec(
                *argv, "gateway", "start",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            try:
                await asyncio.wait_for(start_proc.wait(), timeout=15)
            except asyncio.TimeoutError:
                start_proc.kill()

        await asyncio.sleep(2)
        async with httpx.AsyncClient() as client:
            for _ in range(30):
                try:
                    r = await client.get(healthz_url, timeout=2.0)
                    if r.is_success:
                        chunks.append(_sse({"line": "OpenClaw is up."}))
                        return True, chunks
                except Exception:
                    pass
                await asyncio.sleep(1)

        chunks.append(_sse({"error": "OpenClaw did not come back online", "exit_code": 1}))
        return False, chunks

    async def _stream():
        # Set env vars (each triggers a gateway restart)
        for var, val in env_vars.items():
            yield _sse({"line": f"$ {' '.join(argv)} config set env.vars.{var} ****"})
            stdout, proc = await _run([*argv, "config", "set", f"env.vars.{var}", val])
            output_lines: list[str] = []
            async for raw in stdout:
                line = raw.decode(errors="replace").rstrip()
                output_lines.append(line)
                yield _sse({"line": line})
            rc = await proc.wait()
            wrote = any("Config overwrite" in l or "Updated env.vars" in l for l in output_lines)
            killed_by_restart = rc == 137
            if rc != 0 and not (killed_by_restart and wrote):
                yield _sse({"error": f"config set {var} failed (exit {rc})", "exit_code": rc})
                return

            yield _sse({"line": "Waiting for OpenClaw to restart..."})
            ok, chunks = await _restart_and_wait()
            for chunk in chunks:
                yield chunk
            if not ok:
                return

        # Install plugin
        yield _sse({"line": f"=== Installing {plugin_id} ==="})
        stdout2, proc2 = await _run([*argv, "plugins", "install", str(plugin_dir)])
        async for line in stdout2:
            yield _sse({"line": line.decode(errors="replace").rstrip()})
        rc2 = await proc2.wait()

        # Plugin install triggers a gateway restart — wait for it
        if rc2 == 0 or rc2 == 137:
            yield _sse({"line": "Waiting for OpenClaw to restart after plugin install..."})
            ok, chunks = await _restart_and_wait()
            for chunk in chunks:
                yield chunk
            if not ok:
                yield _sse({"exit_code": 1})
                return

        # After installing dataclaw-tools, ensure it's in tools.alsoAllow
        if rc2 == 0 and plugin_id == "dataclaw-tools":
            yield _sse({"line": "Checking tools.alsoAllow..."})

            current_list: list[str] = []
            try:
                get_proc = await asyncio.create_subprocess_exec(
                    *argv, "config", "get", "tools.alsoAllow", "--json",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                get_stdout, _ = await asyncio.wait_for(get_proc.communicate(), timeout=10)
                if get_proc.returncode == 0:
                    parsed = json.loads(get_stdout.decode().strip())
                    if isinstance(parsed, list):
                        current_list = parsed
            except Exception:
                pass

            if "dataclaw-tools" not in current_list:
                current_list.append("dataclaw-tools")
                new_value = json.dumps(current_list)
                yield _sse({"line": f"Setting tools.alsoAllow to {new_value}"})
                stdout3, proc3 = await _run([
                    *argv, "config", "set", "tools.alsoAllow", new_value,
                ])
                async for raw in stdout3:
                    yield _sse({"line": raw.decode(errors="replace").rstrip()})
                rc3 = await proc3.wait()
                if rc3 != 0 and rc3 != 137:
                    yield _sse({"line": f"Warning: could not set tools.alsoAllow (exit {rc3})"})
                else:
                    yield _sse({"line": "Waiting for OpenClaw to restart..."})
                    ok, chunks = await _restart_and_wait()
                    for chunk in chunks:
                        yield chunk
            else:
                yield _sse({"line": "dataclaw-tools already in tools.alsoAllow."})

        yield _sse({"exit_code": rc2})

    return StreamingResponse(_stream(), media_type="text/event-stream")


@router.get("/fetch-token")
async def fetch_openclaw_token(request: Request):
    cfg = _get_openclaw_config(request)
    openclaw_dir = cfg.get("openclaw_dir", "")
    if not openclaw_dir:
        raise HTTPException(
            status_code=400,
            detail="No .openclaw directory configured. Set openclaw_dir in Config → OpenClaw first.",
        )
    base = Path(openclaw_dir).expanduser()
    candidates = [
        base / ".openclaw" / "openclaw.json",
        base / "openclaw.json",
        Path.home() / ".openclaw" / "openclaw.json",
    ]
    # Deduplicate preserving order
    seen: set[Path] = set()
    unique: list[Path] = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            unique.append(c)
    candidates = unique

    config_path = next((p for p in candidates if p.exists()), None)
    if config_path is None:
        details = []
        for p in candidates:
            if p.parent.exists() and not os.access(p.parent, os.R_OK):
                details.append(f"  {p}  (directory not readable)")
            elif p.parent.exists():
                details.append(f"  {p}  (file not found)")
            else:
                details.append(f"  {p}  (directory does not exist)")
        raise HTTPException(
            status_code=404,
            detail=(
                f"openclaw.json not found.\n"
                f"openclaw_dir={base}  (API home={Path.home()})\n"
                + "\n".join(details)
            ),
        )
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not read openclaw.json: {e}")
    token = data.get("gateway", {}).get("auth", {}).get("token")
    if not token:
        raise HTTPException(
            status_code=404,
            detail="gateway.auth.token not found in openclaw.json",
        )
    return {"token": token, "source": str(config_path)}


@router.get("/debug-dir")
async def debug_openclaw_dir(request: Request):
    """Diagnostic: show what the API process can see under openclaw_dir."""
    cfg = _get_openclaw_config(request)
    openclaw_dir = cfg.get("openclaw_dir", "")
    if not openclaw_dir:
        return {"error": "openclaw_dir not configured"}
    base = Path(openclaw_dir)
    result: dict[str, Any] = {
        "openclaw_dir": str(base),
        "base_exists": base.exists(),
        "base_readable": os.access(base, os.R_OK) if base.exists() else False,
        "base_contents": [],
        "dot_openclaw_exists": False,
        "dot_openclaw_contents": [],
    }
    if base.exists() and os.access(base, os.R_OK):
        try:
            result["base_contents"] = sorted(p.name for p in base.iterdir())
        except Exception as e:
            result["base_contents"] = [f"error: {e}"]
    dot = base / ".openclaw"
    result["dot_openclaw_exists"] = dot.exists()
    if dot.exists():
        result["dot_openclaw_readable"] = os.access(dot, os.R_OK)
        try:
            result["dot_openclaw_contents"] = sorted(p.name for p in dot.iterdir())
        except Exception as e:
            result["dot_openclaw_contents"] = [f"error: {e}"]
    return result
