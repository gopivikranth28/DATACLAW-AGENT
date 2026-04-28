"""NotebookManager — in-memory notebook state with kernel lifecycle.

Each project (or the default workspace) gets its own isolated Python venv.
The venv is auto-created on first kernel start and cached for subsequent use.
This prevents agent code from polluting the system Python or Dataclaw's own venv.
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import nbformat
from jupyter_client import AsyncKernelManager

logger = logging.getLogger(__name__)


@dataclass
class NotebookState:
    name: str
    path: str
    notebook: nbformat.NotebookNode
    kernel_manager: AsyncKernelManager | None = None
    kernel_client: Any | None = None
    dirty: bool = False

    @property
    def kernel_alive(self) -> bool:
        return self.kernel_manager is not None and self.kernel_client is not None


class NotebookManager:
    """Tracks open notebooks and their kernel state.

    Each kernel runs in an isolated venv (auto-created per project or workspace).
    This prevents agent-installed packages from polluting system Python.
    """

    def __init__(
        self,
        notebooks_dir: Path,
        kernel_python: str | None = None,
        venvs_dir: Path | None = None,
        project_id: str | None = None,
    ) -> None:
        self._notebooks_dir = notebooks_dir
        self._kernel_python = kernel_python  # explicit override (skips venv)
        self._venvs_dir = venvs_dir or (notebooks_dir.parent / "venvs")
        self._project_id = project_id or "default"
        self._notebooks: dict[str, NotebookState] = {}
        self._current: str | None = None
        self._project_dir: Path | None = None  # set per-request via hook

    # ── Core operations ─────────────────────────────────────────────────

    async def open(self, path: str, name: str | None = None, create: bool = False) -> NotebookState:
        abs_path = str(Path(path).resolve())
        if name is None:
            name = Path(path).stem

        if name in self._notebooks:
            self._current = name
            return self._notebooks[name]

        p = Path(abs_path)
        if p.exists():
            with open(p, "r", encoding="utf-8") as f:
                nb = nbformat.read(f, as_version=4)
        elif create:
            nb = nbformat.v4.new_notebook()
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                nbformat.write(nb, f)
        else:
            raise FileNotFoundError(f"Notebook not found: {abs_path}")

        state = NotebookState(name=name, path=abs_path, notebook=nb)
        self._notebooks[name] = state
        self._current = name
        return state

    async def close(self, name: str) -> None:
        state = self._get(name)
        await self.save(name)
        await self._shutdown_kernel(state)
        del self._notebooks[name]
        if self._current == name:
            self._current = next(iter(self._notebooks), None)

    async def save(self, name: str) -> None:
        state = self._get(name)
        with open(state.path, "w", encoding="utf-8") as f:
            nbformat.write(state.notebook, f)
        state.dirty = False

    # ── Kernel lifecycle ────────────────────────────────────────────────

    async def start_kernel(self, name: str) -> None:
        state = self._get(name)
        if state.kernel_alive:
            return

        python = self._resolve_python()
        km = AsyncKernelManager(kernel_name="python3")
        # Provide a kernel spec directly so jupyter_client doesn't look it up
        # from the filesystem (ipykernel may not be registered in the host env).
        from jupyter_client.kernelspec import KernelSpec
        km._kernel_spec = KernelSpec(
            argv=[str(python), "-m", "ipykernel_launcher", "-f", "{connection_file}"],
            display_name="Python 3",
            language="python",
        )
        cwd = str(Path(state.path).parent)
        await km.start_kernel(cwd=cwd, env=self._kernel_env())
        kc = km.client()
        kc.start_channels()
        await kc.wait_for_ready(timeout=30)

        state.kernel_manager = km
        state.kernel_client = kc
        logger.info("Kernel started for notebook '%s'", name)

    async def _shutdown_kernel(self, state: NotebookState) -> None:
        if state.kernel_client:
            state.kernel_client.stop_channels()
            state.kernel_client = None
        if state.kernel_manager:
            await state.kernel_manager.shutdown_kernel(now=True)
            state.kernel_manager = None

    async def shutdown_all(self) -> None:
        for state in list(self._notebooks.values()):
            try:
                await self.save(state.name)
                await self._shutdown_kernel(state)
            except Exception as e:
                logger.warning("Error shutting down kernel for '%s': %s", state.name, e)
        self._notebooks.clear()
        self._current = None

    # ── Accessors ───────────────────────────────────────────────────────

    def get_current(self) -> NotebookState:
        if self._current is None or self._current not in self._notebooks:
            raise RuntimeError("No notebook is currently active. Use open_notebook first.")
        return self._notebooks[self._current]

    def list_notebooks(self) -> list[dict[str, Any]]:
        return [
            {
                "name": name,
                "path": state.path,
                "num_cells": len(state.notebook.cells),
                "kernel_alive": state.kernel_alive,
                "is_current": name == self._current,
                "dirty": state.dirty,
            }
            for name, state in self._notebooks.items()
        ]

    def _get(self, name: str) -> NotebookState:
        if name not in self._notebooks:
            raise KeyError(f"Notebook '{name}' is not open. Open: {list(self._notebooks.keys())}")
        return self._notebooks[name]

    def _resolve_python(self) -> Path:
        """Resolve the Python binary for the kernel.

        Reads the project's kernel config from .dataclaw/project.json if available.
        Priority: explicit config > project kernel config > isolated venv > sys.executable.
        """
        # 1. Explicit override from plugin config
        if self._kernel_python:
            p = Path(self._kernel_python).expanduser().resolve()
            if p.exists():
                return p

        # 2. Read project kernel config
        kernel_cfg = self._read_project_kernel_config()
        mode = kernel_cfg.get("mode", "new_env")

        if mode == "system":
            return Path(sys.executable)

        if mode == "custom":
            custom_path = kernel_cfg.get("python_path", "")
            if custom_path:
                p = Path(custom_path).expanduser().resolve()
                if p.exists():
                    return p
                logger.warning("Custom kernel python not found: %s, falling back to venv", p)

        # 3. Isolated venv (default)
        packages = kernel_cfg.get("packages")
        python_version = kernel_cfg.get("python_version", "")
        venv_python = self._ensure_venv(packages=packages, python_version=python_version)
        if venv_python:
            return venv_python

        return Path(sys.executable)

    def _read_project_kernel_config(self) -> dict[str, Any]:
        """Read kernel config from the project's .dataclaw/project.json."""
        try:
            from dataclaw.config.paths import plugin_data_dir
            import json

            # Check project registry for directory
            registry_file = plugin_data_dir("projects") / "registry.json"
            if not registry_file.exists():
                return {}
            registry = json.loads(registry_file.read_text())
            entry = next((e for e in registry if e.get("id") == self._project_id), None)
            if not entry:
                return {}

            project_json = Path(entry["directory"]) / ".dataclaw" / "project.json"
            if not project_json.exists():
                return {}
            meta = json.loads(project_json.read_text())
            return meta.get("kernel", {})
        except Exception:
            return {}

    def _venv_dir(self) -> Path:
        return self._venvs_dir / self._project_id

    def _venv_python(self) -> Path:
        venv = self._venv_dir()
        if sys.platform == "win32":
            return venv / "Scripts" / "python.exe"
        return venv / "bin" / "python"

    def _ensure_venv(self, packages: list[str] | None = None, python_version: str = "") -> Path | None:
        """Create the project venv if it doesn't exist. Install specified packages via uv."""
        venv = self._venv_dir()
        python = self._venv_python()

        if python.exists():
            return python

        if packages is None:
            try:
                from dataclaw_projects.registry import DEFAULT_PACKAGES
                packages = list(DEFAULT_PACKAGES)
            except ImportError:
                packages = [
                    "ipykernel", "pandas", "numpy", "matplotlib", "seaborn",
                    "scikit-learn", "scipy", "plotly", "duckdb", "requests",
                    "mlflow",
                ]

        # Ensure required packages are always included
        try:
            from dataclaw_projects.registry import REQUIRED_PACKAGES
            for pkg in REQUIRED_PACKAGES:
                if pkg not in packages:
                    packages.append(pkg)
        except ImportError:
            if "ipykernel" not in packages:
                packages = ["ipykernel"] + packages

        logger.info("Creating isolated venv for '%s' at %s with %d packages", self._project_id, venv, len(packages))
        try:
            venv_cmd = ["uv", "venv", str(venv)]
            if python_version:
                venv_cmd += ["--python", python_version]

            subprocess.run(venv_cmd, check=True, capture_output=True, timeout=60)

            subprocess.run(
                ["uv", "pip", "install", "--python", str(python)] + packages,
                check=True, capture_output=True, timeout=300,
            )

            logger.info("Venv ready for '%s': %s", self._project_id, ", ".join(packages))
            return python

        except subprocess.CalledProcessError as e:
            logger.error("Failed to create venv for '%s': %s", self._project_id, e.stderr.decode()[:500] if e.stderr else str(e))
            return None
        except Exception as e:
            logger.error("Failed to create venv for '%s': %s", self._project_id, e)
            return None

    def set_session_context(self, session_id: str) -> None:
        """Set the chat session context for MLflow env injection into kernels."""
        self._session_id = session_id
        # Resolve MLflow tracking URI and experiment ID lazily
        try:
            from dataclaw_plans.mlflow_tools import get_or_create_experiment, _get_tracking_uri
            self._mlflow_tracking_uri = _get_tracking_uri()
            self._mlflow_experiment_id = get_or_create_experiment(session_id)
        except Exception:
            self._mlflow_tracking_uri = ""
            self._mlflow_experiment_id = ""

    def _kernel_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env.setdefault("DATACLAW_API_URL", os.environ.get("DATACLAW_API_URL", "http://127.0.0.1:8000"))

        # Inject runtime_packages into PYTHONPATH so dataclaw_data is importable
        runtime_dir = str(Path(__file__).parent / "runtime_packages")
        python_path = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = runtime_dir if not python_path else f"{runtime_dir}{os.pathsep}{python_path}"

        # Set VIRTUAL_ENV so tools like pip work correctly inside the kernel
        venv = self._venv_dir()
        if venv.exists():
            env["VIRTUAL_ENV"] = str(venv)

        # Inject session and MLflow context
        if getattr(self, '_session_id', ''):
            env["DATACLAW_SESSION_ID"] = self._session_id
        if getattr(self, '_mlflow_tracking_uri', ''):
            env["MLFLOW_TRACKING_URI"] = self._mlflow_tracking_uri
        if getattr(self, '_mlflow_experiment_id', ''):
            env["MLFLOW_EXPERIMENT_ID"] = self._mlflow_experiment_id

        return env

    @property
    def notebooks_dir(self) -> Path:
        return self._notebooks_dir

    @property
    def project_dir(self) -> Path | None:
        """The active project directory, or None for the default workspace."""
        return self._project_dir

    @project_dir.setter
    def project_dir(self, value: Path | None) -> None:
        self._project_dir = value

    @property
    def project_id(self) -> str:
        return self._project_id

    @project_id.setter
    def project_id(self, value: str) -> None:
        self._project_id = value or "default"
