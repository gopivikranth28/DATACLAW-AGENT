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
    assert result["cell_index"] == 1            # alias for the renderer
    assert result["source"] == "z = 42"          # echoed for the renderer
    assert result["cell_type"] == "code"
    assert result["num_cells"] == 4

    cell = await tools.read_cell(cell_index=1)
    assert cell["source"] == "z = 42"


@pytest.mark.asyncio
async def test_insert_cell_appends_at_end(sample_notebook):
    await tools.open_notebook(path="test.ipynb", start_kernel=False)
    result = await tools.insert_cell(cell_type="code", source="appended = True")
    # index=-1 default → appended at end (was 3 cells, now 4 → cell_index 3)
    assert result["cell_index"] == 3
    assert result["source"] == "appended = True"


@pytest.mark.asyncio
async def test_edit_cell_tool(sample_notebook):
    await tools.open_notebook(path="test.ipynb", start_kernel=False)
    result = await tools.edit_cell(cell_index=0, new_source="x = 100")
    assert "diff" in result
    # Diff should show the actual change.
    assert "-x = 1" in result["diff"]
    assert "+x = 100" in result["diff"]

    cell = await tools.read_cell(cell_index=0)
    assert cell["source"] == "x = 100"


@pytest.mark.asyncio
async def test_edit_cell_source_tool(sample_notebook):
    await tools.open_notebook(path="test.ipynb", start_kernel=False)
    result = await tools.edit_cell_source(cell_index=1, old_string="x + 1", new_string="x * 2")
    assert "diff" in result
    assert "-y = x + 1" in result["diff"]
    assert "+y = x * 2" in result["diff"]

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


# ── _execute_and_collect MIME capture ──────────────────────────────────────


class _FakeKernelClient:
    """Minimal stand-in for jupyter_client's kernel client.

    Replays a pre-scripted list of iopub messages and answers `execute()`
    with a deterministic msg_id that matches the messages' parent_header.
    """

    MSG_ID = "msg-test-1"

    def __init__(self, messages: list[dict]):
        self._queue = list(messages)

    def execute(self, code: str) -> str:
        return self.MSG_ID

    async def get_iopub_msg(self):
        if not self._queue:
            # Default terminal message: idle status, ends the collect loop.
            return {
                "parent_header": {"msg_id": self.MSG_ID},
                "header": {"msg_type": "status"},
                "content": {"execution_state": "idle"},
            }
        return self._queue.pop(0)


def _msg(msg_type: str, content: dict) -> dict:
    return {
        "parent_header": {"msg_id": _FakeKernelClient.MSG_ID},
        "header": {"msg_type": msg_type},
        "content": content,
    }


@pytest.mark.asyncio
async def test_execute_and_collect_dataframe_keeps_html_plain_and_markdown():
    """Multi-MIME display_data → captured output retains all three reps."""
    fake_kc = _FakeKernelClient([
        _msg("execute_result", {"data": {
            "text/html": "<table border=\"1\"><tr><th>a</th></tr></table>",
            "text/plain": "   a\n0  1",
            "text/markdown": "| a |\n|---|\n| 1 |",
        }}),
        _msg("status", {"execution_state": "idle"}),
    ])
    outputs = await tools._execute_and_collect(fake_kc, "df", timeout=5)
    assert len(outputs) == 1
    out = outputs[0]
    assert out["type"] == "html"
    assert "<table" in out["text"]
    assert out["plain_text"] == "   a\n0  1"
    assert out["markdown"] == "| a |\n|---|\n| 1 |"


@pytest.mark.asyncio
async def test_execute_and_collect_image_keeps_summary():
    """image/png + text/plain → captured output retains base64 and summary."""
    fake_kc = _FakeKernelClient([
        _msg("display_data", {"data": {
            "image/png": "BASE64DATA",
            "text/plain": "<Figure size 600x400 with 1 Axes>",
        }}),
        _msg("status", {"execution_state": "idle"}),
    ])
    outputs = await tools._execute_and_collect(fake_kc, "plt.show()", timeout=5)
    assert len(outputs) == 1
    out = outputs[0]
    assert out["type"] == "image"
    assert out["mimetype"] == "image/png"
    assert out["data"] == "BASE64DATA"
    assert out["summary"] == "<Figure size 600x400 with 1 Axes>"


@pytest.mark.asyncio
async def test_execute_cell_empty_source_returns_source(sample_notebook):
    """execute_cell short-circuits on empty cells but still returns the source field."""
    await tools.open_notebook(path="test.ipynb", start_kernel=False)
    # sample_notebook cell 0 is "x = 1" — overwrite it with whitespace to hit the
    # empty-source short-circuit which doesn't need a kernel.
    await tools.edit_cell(cell_index=0, new_source="   \n   ")
    result = await tools.execute_cell(cell_index=0)
    assert "source" in result
    assert result["source"].strip() == ""
    assert result["outputs"] == []


@pytest.mark.asyncio
async def test_execute_and_collect_text_unchanged():
    """Plain text outputs flow through with type='text'."""
    fake_kc = _FakeKernelClient([
        _msg("stream", {"text": "hello\n"}),
        _msg("execute_result", {"data": {"text/plain": "42"}}),
        _msg("status", {"execution_state": "idle"}),
    ])
    outputs = await tools._execute_and_collect(fake_kc, "x", timeout=5)
    assert outputs == [
        {"type": "text", "text": "hello\n"},
        {"type": "text", "text": "42"},
    ]


@pytest.mark.asyncio
async def test_execute_and_collect_plotly_prefers_json_over_html():
    """Plotly emits both the JSON MIME and a text/html fallback — keep the JSON."""
    figure = {"data": [{"type": "bar", "x": ["a"], "y": [1]}], "layout": {"title": {"text": "T"}}}
    fake_kc = _FakeKernelClient([
        _msg("display_data", {"data": {
            "application/vnd.plotly.v1+json": figure,
            "text/html": "<div>plotly fallback html</div>",
            "text/plain": "Figure({...})",
        }}),
        _msg("status", {"execution_state": "idle"}),
    ])
    outputs = await tools._execute_and_collect(fake_kc, "fig.show()", timeout=5)
    assert len(outputs) == 1
    out = outputs[0]
    assert out["type"] == "plotly"
    assert out["figure"] == figure
    assert out["summary"] == "Figure({...})"


def test_plotly_output_roundtrip_nbformat():
    """plotly output survives outputs_to_nbformat → format_cell_outputs."""
    from dataclaw_notebooks.helpers import format_cell_outputs, outputs_to_nbformat

    figure = {"data": [{"type": "scatter", "x": [1, 2], "y": [3, 4]}], "layout": {}}
    nb_outputs = outputs_to_nbformat([{"type": "plotly", "figure": figure, "summary": ""}])
    assert nb_outputs[0]["output_type"] == "display_data"
    assert nb_outputs[0]["data"]["application/vnd.plotly.v1+json"] == figure

    cell = nbformat.v4.new_code_cell(source="fig.show()")
    cell["outputs"] = nb_outputs
    results = format_cell_outputs(cell)
    assert results == [{"type": "plotly", "figure": figure}]


@pytest.mark.asyncio
async def test_display_metric_tool():
    result = await tools.display_metric(
        label="AI Adoption Rate", value="67%", delta="+12 pp vs 2022", trend="up",
    )
    assert result == {
        "type": "metric",
        "label": "AI Adoption Rate",
        "value": "67%",
        "delta": "+12 pp vs 2022",
        "unit": "",
        "trend": "up",
    }


@pytest.mark.asyncio
async def test_display_metric_rejects_bad_trend():
    with pytest.raises(ValueError, match="trend"):
        await tools.display_metric(label="X", value="1", trend="sideways")


def test_resolve_python_keeps_venv_symlink(tmp_path):
    """Regression: a venv's bin/python is a symlink to the base interpreter.
    _resolve_python must NOT dereference it, or the kernel loses the venv's
    site-packages (plotly, pandas, ...).
    """
    base = tmp_path / "base-python"
    base.touch()
    link = tmp_path / "venv" / "bin" / "python"
    link.parent.mkdir(parents=True)
    link.symlink_to(base)

    mgr = NotebookManager(notebooks_dir=tmp_path, kernel_python=str(link))
    resolved = mgr._resolve_python()
    assert resolved == link, f"symlink was dereferenced to {resolved}"


# ── Event-loop regression tests ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_kernel_does_not_block_event_loop(mgr, sample_notebook, monkeypatch):
    """Regression: _resolve_python may shell out to `uv venv`/`uv pip install`.
    If start_kernel ran it inline it would freeze the event loop. Verify it's
    pushed to a worker thread so other tasks make progress concurrently.
    """
    import asyncio
    import time

    # Patch _resolve_python with a SYNC sleep (blocks the calling thread for 0.5s).
    # If start_kernel awaits it inline, no concurrent task can run during that 0.5s.
    def slow_resolve(self):
        time.sleep(0.5)
        raise RuntimeError("stop here — we don't actually want a real kernel")

    monkeypatch.setattr(
        "dataclaw_notebooks.manager.NotebookManager._resolve_python",
        slow_resolve,
    )

    await mgr.open(sample_notebook)

    ticks = 0

    async def ticker():
        nonlocal ticks
        for _ in range(20):
            ticks += 1
            await asyncio.sleep(0.02)

    ticker_task = asyncio.create_task(ticker())
    try:
        await mgr.start_kernel("test")
    except RuntimeError:
        pass  # expected — we raise to short-circuit kernel start
    await ticker_task

    # If the event loop were blocked for 0.5s we'd see < ~5 ticks. With
    # asyncio.to_thread we should easily see most of them complete.
    assert ticks >= 15, f"event loop appears blocked: only {ticks}/20 ticks ran"
