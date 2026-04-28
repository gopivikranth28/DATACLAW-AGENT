"""Notebook tools — callable by AI agents.

All tools operate on a shared NotebookManager singleton stored
in app.state during plugin registration.
"""

from __future__ import annotations

import asyncio
import difflib
import re
from pathlib import Path
from typing import Any

import nbformat

from dataclaw_notebooks.manager import NotebookManager
from dataclaw_notebooks.helpers import cell_summary, format_cell_outputs, outputs_to_nbformat

# The manager is set during plugin registration
_manager: NotebookManager | None = None


def set_manager(mgr: NotebookManager) -> None:
    global _manager
    _manager = mgr


def _mgr() -> NotebookManager:
    if _manager is None:
        raise RuntimeError("NotebookManager not initialized. Is the notebooks plugin loaded?")
    return _manager


def _resolve_path(path: str) -> Path:
    """Resolve a notebook path inside the active project or default notebooks directory."""
    mgr = _mgr()
    base = (mgr.project_dir or mgr.notebooks_dir).resolve()
    raw = Path(path).expanduser()
    resolved = raw.resolve() if raw.is_absolute() else (base / raw).resolve()
    if resolved.suffix != ".ipynb":
        resolved = resolved.with_suffix(".ipynb")
    try:
        resolved.relative_to(base)
    except ValueError as exc:
        raise ValueError(f"Notebook path must be inside {base}") from exc
    return resolved


# ── Lifecycle tools ─────────────────────────────────────────────────────────


async def open_notebook(*, path: str, name: str | None = None, create: bool = False, start_kernel: bool = True, **kw: Any) -> dict[str, Any]:
    notebook_path = _resolve_path(path)
    state = await _mgr().open(str(notebook_path), name=name, create=create)
    if start_kernel:
        try:
            await _mgr().start_kernel(state.name)
        except Exception:
            pass  # Kernel start is best-effort — cell CRUD still works
    cells = [cell_summary(c, i) for i, c in enumerate(state.notebook.cells)]
    return {"name": state.name, "path": state.path, "num_cells": len(state.notebook.cells), "cells": cells[:20]}


async def close_notebook(*, name: str, **kw: Any) -> dict[str, Any]:
    await _mgr().close(name)
    return {"closed": name}


async def list_notebooks(**kw: Any) -> dict[str, Any]:
    return {"notebooks": _mgr().list_notebooks()}


# ── Reading tools ───────────────────────────────────────────────────────────


async def read_notebook(*, start: int = 0, limit: int = 20, **kw: Any) -> dict[str, Any]:
    state = _mgr().get_current()
    cells = state.notebook.cells
    page = cells[start:start + limit]
    return {
        "notebook": state.name, "total_cells": len(cells),
        "start": start, "limit": limit,
        "cells": [cell_summary(c, start + i) for i, c in enumerate(page)],
    }


async def read_cell(*, cell_index: int, **kw: Any) -> dict[str, Any]:
    state = _mgr().get_current()
    _validate_index(cell_index, len(state.notebook.cells))
    cell = state.notebook.cells[cell_index]
    return {
        "index": cell_index, "cell_type": cell.cell_type,
        "source": cell.source, "execution_count": cell.get("execution_count"),
        "outputs": format_cell_outputs(cell),
    }


# ── Writing tools ───────────────────────────────────────────────────────────


async def insert_cell(*, index: int = -1, cell_type: str = "code", source: str = "", **kw: Any) -> dict[str, Any]:
    state = _mgr().get_current()
    cells = state.notebook.cells
    if cell_type == "code":
        new_cell = nbformat.v4.new_code_cell(source=source)
    elif cell_type == "markdown":
        new_cell = nbformat.v4.new_markdown_cell(source=source)
    else:
        raise ValueError(f"Invalid cell_type: {cell_type}")

    if index == -1 or index >= len(cells):
        cells.append(new_cell)
        actual = len(cells) - 1
    else:
        cells.insert(index, new_cell)
        actual = index

    state.dirty = True
    await _mgr().save(state.name)
    return {"inserted_at": actual, "cell_type": cell_type, "num_cells": len(cells)}


async def edit_cell(*, cell_index: int, new_source: str, **kw: Any) -> dict[str, Any]:
    state = _mgr().get_current()
    _validate_index(cell_index, len(state.notebook.cells))
    old = state.notebook.cells[cell_index].source
    state.notebook.cells[cell_index].source = new_source
    state.dirty = True
    await _mgr().save(state.name)
    return {"cell_index": cell_index, "diff": _diff(old, new_source)}


async def edit_cell_source(*, cell_index: int, old_string: str, new_string: str, replace_all: bool = False, **kw: Any) -> dict[str, Any]:
    state = _mgr().get_current()
    _validate_index(cell_index, len(state.notebook.cells))
    source = state.notebook.cells[cell_index].source
    if old_string not in source:
        raise ValueError(f"'{old_string}' not found in cell {cell_index}")
    new_source = source.replace(old_string, new_string) if replace_all else source.replace(old_string, new_string, 1)
    state.notebook.cells[cell_index].source = new_source
    state.dirty = True
    await _mgr().save(state.name)
    return {"cell_index": cell_index, "diff": _diff(source, new_source)}


async def move_cell(*, source_index: int, target_index: int, **kw: Any) -> dict[str, Any]:
    state = _mgr().get_current()
    cells = state.notebook.cells
    _validate_index(source_index, len(cells))
    cell = cells.pop(source_index)
    if target_index > source_index:
        target_index -= 1
    target_index = max(0, min(target_index, len(cells)))
    cells.insert(target_index, cell)
    state.dirty = True
    await _mgr().save(state.name)
    return {"moved": f"cell {source_index} -> {target_index}", "num_cells": len(cells)}


async def delete_cells(*, cell_indices: list[int], **kw: Any) -> dict[str, Any]:
    state = _mgr().get_current()
    cells = state.notebook.cells
    for idx in cell_indices:
        _validate_index(idx, len(cells))
    deleted = []
    for idx in sorted(cell_indices, reverse=True):
        cell = cells.pop(idx)
        deleted.append({"index": idx, "cell_type": cell.cell_type, "preview": cell.source.split("\n")[0][:80]})
    state.dirty = True
    await _mgr().save(state.name)
    return {"deleted": list(reversed(deleted)), "num_cells": len(cells)}


# ── Execution tools ─────────────────────────────────────────────────────────


async def execute_cell(*, cell_index: int, timeout: int = 120, **kw: Any) -> dict[str, Any]:
    state = _mgr().get_current()
    cells = state.notebook.cells
    _validate_index(cell_index, len(cells))
    cell = cells[cell_index]
    if cell.cell_type != "code":
        raise ValueError(f"Cell {cell_index} is {cell.cell_type}, not code")
    if not cell.source.strip():
        return {"cell_index": cell_index, "outputs": [], "error": None}

    if not state.kernel_alive:
        await _mgr().start_kernel(state.name)

    outputs, error = await _run_code(state, cell.source, timeout)
    cell.outputs = outputs_to_nbformat(outputs)
    max_count = max((c.get("execution_count") or 0 for c in cells if c.cell_type == "code"), default=0)
    cell.execution_count = max_count + 1
    state.dirty = True
    await _mgr().save(state.name)
    return {"cell_index": cell_index, "outputs": outputs, "error": error}


async def execute_code(*, code: str, timeout: int = 120, **kw: Any) -> dict[str, Any]:
    state = _mgr().get_current()
    if not state.kernel_alive:
        await _mgr().start_kernel(state.name)
    outputs, error = await _run_code(state, code, timeout)
    return {"outputs": outputs, "error": error}


async def display_cell_output(*, cell_index: int, caption: str = "", **kw: Any) -> dict[str, Any]:
    state = _mgr().get_current()
    _validate_index(cell_index, len(state.notebook.cells))
    cell = state.notebook.cells[cell_index]
    outputs = format_cell_outputs(cell)
    if not outputs:
        raise ValueError(f"Cell {cell_index} has no outputs. Execute it first.")
    return {"cell_index": cell_index, "output_count": len(outputs), "outputs": outputs, "caption": caption}


# ── Helpers ─────────────────────────────────────────────────────────────────


async def _run_code(state: Any, code: str, timeout: int) -> tuple[list[dict], str | None]:
    kc = state.kernel_client
    error = None
    try:
        outputs = await _execute_and_collect(kc, code, timeout)
    except asyncio.TimeoutError:
        error = f"Execution timed out after {timeout} seconds"
        outputs = []
        try:
            state.kernel_manager.interrupt_kernel()
        except Exception:
            pass
    except Exception as e:
        error = str(e)
        outputs = []
    return outputs, error


async def _execute_and_collect(kc: Any, code: str, timeout: int) -> list[dict]:
    msg_id = kc.execute(code)
    outputs: list[dict] = []
    deadline = asyncio.get_event_loop().time() + timeout

    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            raise asyncio.TimeoutError()
        try:
            msg = await asyncio.wait_for(kc.get_iopub_msg(), timeout=min(remaining, 5.0))
        except asyncio.TimeoutError:
            continue

        if msg["parent_header"].get("msg_id") != msg_id:
            continue

        msg_type = msg["header"]["msg_type"]
        content = msg["content"]

        if msg_type == "stream":
            outputs.append({"type": "text", "text": content["text"]})
        elif msg_type in ("execute_result", "display_data"):
            data = content.get("data", {})
            if "image/png" in data:
                outputs.append({"type": "image", "data": data["image/png"], "mimetype": "image/png"})
            elif "text/html" in data:
                outputs.append({"type": "html", "text": data["text/html"]})
            elif "text/plain" in data:
                outputs.append({"type": "text", "text": data["text/plain"]})
        elif msg_type == "error":
            tb = "\n".join(content.get("traceback", []))
            tb = re.sub(r"\x1b\[[0-9;]*m", "", tb)
            outputs.append({"type": "error", "text": tb})
        elif msg_type == "status" and content.get("execution_state") == "idle":
            break

    return outputs


def _validate_index(index: int, length: int) -> None:
    if index < 0 or index >= length:
        raise IndexError(f"Cell index {index} out of range (notebook has {length} cells)")


def _diff(old: str, new: str) -> str:
    return "\n".join(difflib.unified_diff(
        old.splitlines(), new.splitlines(),
        fromfile="before", tofile="after", lineterm="",
    ))
