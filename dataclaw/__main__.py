"""CLI entrypoint — python -m dataclaw starts the API server."""

import subprocess
import sys
from pathlib import Path

import uvicorn

from dataclaw.api.app import create_app
from dataclaw.config.resolver import resolve

app = create_app()

UI_DIR = Path(__file__).parent.parent / "ui"


def _build_ui() -> None:
    """Install deps and build the React UI if ui/dist/ doesn't exist."""
    dist = UI_DIR / "dist"
    if dist.is_dir():
        return

    if not (UI_DIR / "package.json").exists():
        print("Warning: ui/ directory not found, skipping UI build", file=sys.stderr)
        return

    print("Building UI (first run)...")
    subprocess.run(["npm", "install", "--prefix", str(UI_DIR)], check=True)
    subprocess.run(["npm", "run", "build", "--prefix", str(UI_DIR)], check=True)
    print("UI build complete.")


def main() -> None:
    _build_ui()

    host = resolve("app.host", "DATACLAW_HOST", "0.0.0.0")
    port = int(resolve("app.port", "DATACLAW_PORT", "8000"))
    debug = resolve("app.debug", "DATACLAW_DEBUG", "false")
    reload = str(debug).lower() in ("true", "1", "yes")

    reload_dirs = None
    if reload:
        root = Path(__file__).parent.parent
        reload_dirs = [str(root / "dataclaw"), str(root / "plugins")]

    uvicorn.run(
        "dataclaw.__main__:app",
        host=host,
        port=port,
        reload=reload,
        reload_dirs=reload_dirs,
    )


if __name__ == "__main__":
    main()
