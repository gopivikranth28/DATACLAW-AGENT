"""Independent Hermes/extension installation helpers."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dataclaw.api.security import api_token
from dataclaw.config.secure_io import write_private_text
from dataclaw_hermes.config import HERMES_COMPAT_VERSION, HermesConfig


def _resolve_executable(cli_path: str) -> str | None:
    """Resolve configured and standard uv-tool locations for the Hermes CLI."""
    expanded = Path(cli_path).expanduser()
    if expanded.is_file() and os.access(expanded, os.X_OK):
        return str(expanded)
    executable = shutil.which(cli_path)
    if executable:
        return executable
    if cli_path == "hermes":
        uv_tool_executable = Path.home() / ".local" / "bin" / "hermes"
        if uv_tool_executable.is_file() and os.access(
            uv_tool_executable, os.X_OK
        ):
            return str(uv_tool_executable)
    return None


def _configured_model(profile_config: Path) -> tuple[str | None, str | None]:
    """Read the non-secret primary model/provider selected for a profile."""
    if not profile_config.exists():
        return None, None
    try:
        import yaml

        raw = yaml.safe_load(profile_config.read_text()) or {}
        model_config = raw.get("model") if isinstance(raw, dict) else None
        if isinstance(model_config, str):
            return model_config or None, None
        if isinstance(model_config, dict):
            model = model_config.get("default") or model_config.get("model")
            provider = model_config.get("provider")
            return (
                str(model) if model else None,
                str(provider) if provider else None,
            )
    except Exception:
        pass
    return None, None


def _provider_auth_status(
    executable: str,
    config: HermesConfig,
    provider: str,
) -> tuple[bool | None, str | None]:
    """Read structural credential status through Hermes' public CLI."""
    command = [executable]
    if config.profile not in {"", "default"}:
        command.extend(["-p", config.profile])
    command.extend(["auth", "status", provider])
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except Exception:
        return None, None

    output = (result.stdout or result.stderr).strip()
    first_line = output.splitlines()[0].strip() if output else None
    if result.returncode != 0 or first_line is None:
        return None, first_line
    normalized = first_line.lower()
    if ": logged in" in normalized:
        return True, first_line
    if ": logged out" in normalized:
        return False, first_line
    return None, first_line


def check_installation(config: HermesConfig) -> dict[str, Any]:
    executable = _resolve_executable(config.cli_path)
    version = None
    version_output = None
    if executable:
        try:
            result = subprocess.run(
                [executable, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            version_output = (
                (result.stdout or result.stderr).strip() or None
            )
            if version_output:
                match = re.search(
                    r"(?<![\d.])(\d+\.\d+\.\d+)(?![\d.])",
                    version_output,
                )
                version = match.group(1) if match else version_output
        except Exception:
            version = None
    home = _profile_home(config)
    target = home / "plugins" / "dataclaw"
    profile_config = home / "config.yaml"
    model, provider = _configured_model(profile_config)
    provider_auth_configured: bool | None = None
    provider_auth_detail: str | None = None
    if executable and provider:
        provider_auth_configured, provider_auth_detail = (
            _provider_auth_status(executable, config, provider)
        )
    return {
        "installed": executable is not None,
        "executable": executable,
        "version": version,
        "version_output": version_output,
        "compatible_version": HERMES_COMPAT_VERSION,
        "version_compatible": version == HERMES_COMPAT_VERSION,
        "extension_installed": (target / "plugin.yaml").exists(),
        "extension_path": str(target),
        "profile": config.profile,
        "profile_configured": profile_config.exists(),
        "restricted_profile": _restricted_profile(profile_config),
        "model": model,
        "provider": provider,
        "model_selected": bool(model),
        "model_configured": bool(model),
        "provider_auth_configured": provider_auth_configured,
        "provider_auth_detail": provider_auth_detail,
    }


def extension_environment(config: HermesConfig) -> dict[str, str]:
    env = {
        "DATACLAW_API_URL": config.dataclaw_api_url,
        "DATACLAW_HERMES_TOOL_TIMEOUT_SECONDS": str(
            config.tool_callback_timeout_seconds
        ),
    }
    # The extension's callbacks into Dataclaw authenticate with the API token.
    token = api_token()
    if token:
        env["DATACLAW_TOKEN"] = token
    return env


def install_extension(
    source: Path,
    *,
    hermes_home: Path | None = None,
    config: HermesConfig,
) -> dict[str, Any]:
    """Install the versioned extension after an explicit API/UI request."""
    home = hermes_home or Path(
        os.environ.get("HERMES_HOME", Path.home() / ".hermes")
    )
    target = home / "plugins" / "dataclaw"
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(
        tempfile.mkdtemp(prefix=".dataclaw-stage-", dir=target.parent)
    )
    backup: Path | None = None
    try:
        shutil.rmtree(stage)
        shutil.copytree(source, stage)
        if target.exists():
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            backup = target.with_name(f"dataclaw.backup-{stamp}")
            target.rename(backup)
        stage.rename(target)
    except Exception:
        if not target.exists() and backup is not None and backup.exists():
            backup.rename(target)
        if stage.exists():
            shutil.rmtree(stage)
        raise
    env_path = target / ".dataclaw-env.json"
    write_private_text(env_path, json.dumps(extension_environment(config), indent=2))
    return {
        "installed": True,
        "path": str(target),
        "environment": str(env_path),
        "backup": str(backup) if backup else None,
    }


def _hermes_root() -> Path:
    return Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))


def _profile_home(config: HermesConfig) -> Path:
    root = _hermes_root()
    if config.profile in {"", "default"}:
        return root
    return root / "profiles" / config.profile


def _restricted_profile(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        import yaml

        raw = yaml.safe_load(path.read_text()) or {}
        enabled = (
            (raw.get("platform_toolsets") or {}).get("api_server") or []
        )
        plugins = (raw.get("plugins") or {}).get("enabled") or []
        api_server = (raw.get("platforms") or {}).get("api_server") or {}
        api_server_extra = api_server.get("extra") or {}
        return (
            enabled == ["dataclaw"]
            and plugins == ["dataclaw"]
            and api_server.get("enabled") is True
            and bool(api_server_extra.get("key"))
        )
    except Exception:
        return False


def _write_restricted_profile(config: HermesConfig) -> Path:
    """Merge the API-server Dataclaw-only tool whitelist into the profile."""
    import yaml

    home = _profile_home(config)
    home.mkdir(parents=True, exist_ok=True)
    path = home / "config.yaml"
    raw: dict[str, Any] = {}
    if path.exists():
        loaded = yaml.safe_load(path.read_text()) or {}
        if isinstance(loaded, dict):
            raw = loaded
        backup = path.with_suffix(".yaml.dataclaw-backup")
        if not backup.exists():
            shutil.copy2(path, backup)
    raw.setdefault("platform_toolsets", {})["api_server"] = ["dataclaw"]
    raw.setdefault("plugins", {})["enabled"] = ["dataclaw"]
    api_server = raw.setdefault("platforms", {}).setdefault(
        "api_server", {}
    )
    api_server["enabled"] = True
    api_server.setdefault("extra", {})["key"] = config.api_key
    # Dataclaw versions before the Hermes 0.19 live-install gate wrote this
    # switch under gateway.api_server. Hermes reads platform enablement from
    # platforms.api_server; remove only the obsolete switch while preserving
    # valid gateway.api_server settings such as max_concurrent_runs.
    gateway = raw.get("gateway")
    if isinstance(gateway, dict):
        api_server = gateway.get("api_server")
        if isinstance(api_server, dict):
            api_server.pop("enabled", None)
            if not api_server:
                gateway.pop("api_server", None)
        if not gateway:
            raw.pop("gateway", None)
    # Holds the Hermes API server key.
    write_private_text(path, yaml.safe_dump(raw, sort_keys=False))
    return path


def _extension_source() -> Path:
    packaged = Path(__file__).resolve().parent / "extension"
    if (packaged / "plugin.yaml").exists():
        return packaged
    # Editable installs keep the independent Hermes plugin at repository root.
    source = (
        Path(__file__).resolve().parents[3]
        / "hermes-plugins"
        / "dataclaw"
    )
    if not (source / "plugin.yaml").exists():
        raise FileNotFoundError(
            f"Bundled Hermes extension was not found at {source}"
        )
    return source


def install_dataclaw_extension(config: HermesConfig) -> dict[str, Any]:
    """Explicit setup operation used by the Config UI/API."""
    config.validate()
    executable = _resolve_executable(config.cli_path)
    if executable is None:
        raise RuntimeError(
            f"Hermes CLI {config.cli_path!r} is not installed"
        )
    status = check_installation(config)
    if not status["version_compatible"]:
        raise RuntimeError(
            "Incompatible Hermes CLI: expected hermes-agent "
            f"{HERMES_COMPAT_VERSION}, got "
            f"{status.get('version') or 'unknown'}"
        )
    home = _profile_home(config)
    if not home.exists() and config.profile not in {"", "default"}:
        result = subprocess.run(
            [
                executable,
                "profile",
                "create",
                config.profile,
                "--no-skills",
                "--no-alias",
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                "Could not create the Hermes profile: "
                + (result.stderr or result.stdout)[-500:]
            )
    profile_config = _write_restricted_profile(config)
    installed = install_extension(
        _extension_source(), hermes_home=home, config=config
    )
    return {
        **installed,
        "profile": config.profile,
        "profile_config": str(profile_config),
        "restricted_profile": True,
        "restart_required": True,
    }


def restart_hermes_gateway(config: HermesConfig) -> dict[str, Any]:
    """Restart the configured Hermes profile gateway through the pinned CLI."""
    executable = _resolve_executable(config.cli_path)
    if executable is None:
        raise RuntimeError(
            f"Hermes CLI {config.cli_path!r} is not installed"
        )
    command = [executable]
    if config.profile not in {"", "default"}:
        command.extend(["-p", config.profile])
    command.extend(["gateway", "restart"])
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            "Hermes gateway restart timed out after 60 seconds"
        ) from exc
    output = (result.stdout or result.stderr).strip()
    if result.returncode != 0:
        raise RuntimeError(
            "Hermes gateway restart failed"
            + (f": {output[-500:]}" if output else "")
        )
    return {
        "status": "restarted",
        "profile": config.profile or "default",
        "output": output[-1_000:],
    }


def remove_dataclaw_extension(config: HermesConfig) -> dict[str, Any]:
    """Move the extension aside so removal remains recoverable."""
    target = _profile_home(config) / "plugins" / "dataclaw"
    if not target.exists():
        return {"removed": False, "path": str(target), "backup": None}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    backup = target.with_name(f"dataclaw.removed-{stamp}")
    target.rename(backup)
    return {
        "removed": True,
        "path": str(target),
        "backup": str(backup),
        "restart_required": True,
    }
