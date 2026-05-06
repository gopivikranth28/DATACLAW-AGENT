"""Tests for notebook path resolution — ensures notebooks land in the right directory."""

import pytest
from pathlib import Path

import nbformat

import dataclaw.config.paths as paths
from dataclaw_notebooks.manager import NotebookManager
from dataclaw_notebooks import tools


@pytest.fixture(autouse=True)
def tmp_home(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DATACLAW_HOME", tmp_path)
    return tmp_path


@pytest.fixture
def mgr(tmp_home):
    nb_dir = tmp_home / "workspaces"
    nb_dir.mkdir(parents=True)
    m = NotebookManager(notebooks_dir=nb_dir)
    tools.set_manager(m)
    return m


# ── Path resolution with no project ───────────────────────────────────────


@pytest.mark.asyncio
async def test_notebook_lands_in_default_dir(mgr):
    """Without a project, notebooks resolve relative to the default notebooks_dir."""
    result = await tools.open_notebook(path="analysis.ipynb", create=True)
    expected = mgr.notebooks_dir / "analysis.ipynb"
    assert expected.exists()
    assert result["path"] == str(expected)


# ── Path resolution with a project ────────────────────────────────────────


@pytest.mark.asyncio
async def test_notebook_lands_in_project_dir(mgr, tmp_home):
    """With a project_dir set, notebooks resolve relative to the project."""
    project_dir = tmp_home / "my-project"
    project_dir.mkdir()
    mgr.project_dir = project_dir

    result = await tools.open_notebook(path="experiment.ipynb", create=True)
    expected = project_dir / "experiment.ipynb"
    assert expected.exists()
    assert result["path"] == str(expected)


@pytest.mark.asyncio
async def test_project_dir_overrides_default(mgr, tmp_home):
    """project_dir takes priority over notebooks_dir."""
    project_dir = tmp_home / "proj"
    project_dir.mkdir()
    mgr.project_dir = project_dir

    result = await tools.open_notebook(path="nb.ipynb", create=True)
    # Should NOT be in the default notebooks_dir
    assert not (mgr.notebooks_dir / "nb.ipynb").exists()
    assert (project_dir / "nb.ipynb").exists()


# ── Path traversal prevention ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_traversal_outside_base_rejected(mgr):
    """Paths that escape the base directory are rejected."""
    with pytest.raises(ValueError, match="must be inside"):
        await tools.open_notebook(path="../../etc/passwd", create=True)


@pytest.mark.asyncio
async def test_traversal_outside_project_rejected(mgr, tmp_home):
    """Paths that escape the project directory are rejected."""
    project_dir = tmp_home / "proj"
    project_dir.mkdir()
    mgr.project_dir = project_dir

    with pytest.raises(ValueError, match="must be inside"):
        await tools.open_notebook(path="../../../etc/passwd", create=True)
