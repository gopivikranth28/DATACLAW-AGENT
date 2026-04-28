"""Tests for notebook plugin — cell CRUD operations (no kernel required)."""

import pytest
from pathlib import Path

import nbformat

import dataclaw.config.paths as paths
from dataclaw_notebooks.manager import NotebookManager
from dataclaw_notebooks import tools


@pytest.fixture(autouse=True)
def tmp_home(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DATACLAW_HOME", tmp_path)
    nb_dir = tmp_path / "plugins" / "notebooks" / "files"
    nb_dir.mkdir(parents=True)
    return tmp_path


@pytest.fixture
def mgr(tmp_home):
    nb_dir = tmp_home / "plugins" / "notebooks" / "files"
    m = NotebookManager(notebooks_dir=nb_dir)
    tools.set_manager(m)
    return m


@pytest.fixture
def sample_notebook(mgr):
    """Create a sample notebook with a few cells."""
    nb_dir = mgr.notebooks_dir
    nb = nbformat.v4.new_notebook()
    nb.cells = [
        nbformat.v4.new_code_cell(source="x = 1"),
        nbformat.v4.new_code_cell(source="y = x + 1"),
        nbformat.v4.new_markdown_cell(source="# Results"),
    ]
    path = nb_dir / "test.ipynb"
    with open(path, "w") as f:
        nbformat.write(nb, f)
    return str(path)


# ── Manager tests ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_open_and_list(mgr, sample_notebook):
    state = await mgr.open(sample_notebook)
    assert state.name == "test"
    assert len(state.notebook.cells) == 3
    notebooks = mgr.list_notebooks()
    assert len(notebooks) == 1
    assert notebooks[0]["name"] == "test"


@pytest.mark.asyncio
async def test_open_create(mgr):
    state = await mgr.open(str(mgr.notebooks_dir / "new.ipynb"), create=True)
    assert state.name == "new"
    assert len(state.notebook.cells) == 0
    assert Path(state.path).exists()


@pytest.mark.asyncio
async def test_open_not_found(mgr):
    with pytest.raises(FileNotFoundError):
        await mgr.open(str(mgr.notebooks_dir / "nonexistent.ipynb"))


@pytest.mark.asyncio
async def test_close(mgr, sample_notebook):
    await mgr.open(sample_notebook)
    await mgr.close("test")
    assert mgr.list_notebooks() == []


# ── Tool tests (cell CRUD) ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_open_notebook_tool(sample_notebook):
    result = await tools.open_notebook(path="test.ipynb", start_kernel=False)
    assert result["name"] == "test"
    assert result["num_cells"] == 3


@pytest.mark.asyncio
async def test_list_notebooks_tool(sample_notebook):
    await tools.open_notebook(path="test.ipynb", start_kernel=False)
    result = await tools.list_notebooks()
    assert len(result["notebooks"]) == 1


@pytest.mark.asyncio
async def test_read_notebook_tool(sample_notebook):
    await tools.open_notebook(path="test.ipynb", start_kernel=False)
    result = await tools.read_notebook(start=0, limit=10)
    assert result["total_cells"] == 3
    assert len(result["cells"]) == 3


@pytest.mark.asyncio
async def test_read_cell_tool(sample_notebook):
    await tools.open_notebook(path="test.ipynb", start_kernel=False)
    result = await tools.read_cell(cell_index=0)
    assert result["source"] == "x = 1"
    assert result["cell_type"] == "code"


@pytest.mark.asyncio
async def test_insert_cell_tool(sample_notebook):
    await tools.open_notebook(path="test.ipynb", start_kernel=False)
    result = await tools.insert_cell(index=1, cell_type="code", source="z = 42")
    assert result["inserted_at"] == 1
    assert result["num_cells"] == 4

    cell = await tools.read_cell(cell_index=1)
    assert cell["source"] == "z = 42"


@pytest.mark.asyncio
async def test_edit_cell_tool(sample_notebook):
    await tools.open_notebook(path="test.ipynb", start_kernel=False)
    result = await tools.edit_cell(cell_index=0, new_source="x = 100")
    assert "diff" in result

    cell = await tools.read_cell(cell_index=0)
    assert cell["source"] == "x = 100"


@pytest.mark.asyncio
async def test_edit_cell_source_tool(sample_notebook):
    await tools.open_notebook(path="test.ipynb", start_kernel=False)
    result = await tools.edit_cell_source(cell_index=1, old_string="x + 1", new_string="x * 2")
    assert "diff" in result

    cell = await tools.read_cell(cell_index=1)
    assert cell["source"] == "y = x * 2"


@pytest.mark.asyncio
async def test_move_cell_tool(sample_notebook):
    await tools.open_notebook(path="test.ipynb", start_kernel=False)
    result = await tools.move_cell(source_index=2, target_index=0)
    assert result["num_cells"] == 3

    cell = await tools.read_cell(cell_index=0)
    assert cell["cell_type"] == "markdown"


@pytest.mark.asyncio
async def test_delete_cells_tool(sample_notebook):
    await tools.open_notebook(path="test.ipynb", start_kernel=False)
    result = await tools.delete_cells(cell_indices=[2])
    assert result["num_cells"] == 2


@pytest.mark.asyncio
async def test_read_cell_out_of_range(sample_notebook):
    await tools.open_notebook(path="test.ipynb", start_kernel=False)
    with pytest.raises(IndexError):
        await tools.read_cell(cell_index=99)


@pytest.mark.asyncio
async def test_edit_cell_source_not_found(sample_notebook):
    await tools.open_notebook(path="test.ipynb", start_kernel=False)
    with pytest.raises(ValueError, match="not found"):
        await tools.edit_cell_source(cell_index=0, old_string="nonexistent", new_string="x")


@pytest.mark.asyncio
async def test_close_notebook_tool(sample_notebook):
    await tools.open_notebook(path="test.ipynb", start_kernel=False)
    result = await tools.close_notebook(name="test")
    assert result["closed"] == "test"
    assert (await tools.list_notebooks())["notebooks"] == []
