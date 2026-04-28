"""Tests for workspace tools."""

import pytest
from pathlib import Path

from dataclaw_workspace.config import WorkspaceConfig
from dataclaw_workspace.tools import (
    ws_list_files,
    ws_read_file,
    ws_write_file,
    ws_update_file,
    ws_exec,
    display_image,
    _base_dir,
)

import dataclaw.config.paths as paths


@pytest.fixture(autouse=True)
def tmp_workspaces(tmp_path, monkeypatch):
    ws_dir = tmp_path / "workspaces"
    ws_dir.mkdir()
    monkeypatch.setattr(paths, "DATACLAW_HOME", tmp_path)
    return ws_dir


@pytest.fixture
def cfg():
    return WorkspaceConfig()


@pytest.mark.asyncio
async def test_write_and_read(cfg):
    result = await ws_write_file(cfg=cfg, path="hello.txt", content="Hello world\nLine 2\n")
    assert result["created"] is True
    assert result["size"] > 0

    result = await ws_read_file(cfg=cfg, path="hello.txt")
    assert result["content"] == "Hello world\nLine 2\n"
    assert result["total_lines"] == 2


@pytest.mark.asyncio
async def test_read_with_offset_limit(cfg):
    await ws_write_file(cfg=cfg, path="lines.txt", content="a\nb\nc\nd\ne\n")
    result = await ws_read_file(cfg=cfg, path="lines.txt", offset=1, limit=2)
    assert result["lines_returned"] == 2
    assert result["content"] == "b\nc\n"


@pytest.mark.asyncio
async def test_read_too_large(cfg):
    cfg.max_read_bytes = 10
    await ws_write_file(cfg=cfg, path="big.txt", content="x" * 100)
    with pytest.raises(ValueError, match="too large"):
        await ws_read_file(cfg=cfg, path="big.txt")


@pytest.mark.asyncio
async def test_write_too_large(cfg):
    cfg.max_write_bytes = 10
    with pytest.raises(ValueError, match="too large"):
        await ws_write_file(cfg=cfg, path="big.txt", content="x" * 100)


@pytest.mark.asyncio
async def test_list_files(cfg):
    await ws_write_file(cfg=cfg, path="a.txt", content="a")
    await ws_write_file(cfg=cfg, path="b.txt", content="b")
    result = await ws_list_files(cfg=cfg)
    names = {e["name"] for e in result["entries"]}
    assert "a.txt" in names
    assert "b.txt" in names


@pytest.mark.asyncio
async def test_list_truncation(cfg):
    cfg.max_list_entries = 2
    for i in range(5):
        await ws_write_file(cfg=cfg, path=f"file{i}.txt", content=str(i))
    result = await ws_list_files(cfg=cfg)
    assert result["truncated"] is True
    assert len(result["entries"]) == 2


@pytest.mark.asyncio
async def test_update_file(cfg):
    await ws_write_file(cfg=cfg, path="code.py", content="x = 1\ny = 2\n")
    result = await ws_update_file(cfg=cfg, path="code.py", old_string="x = 1", new_string="x = 42")
    assert result["replacements"] == 1
    assert "x = 42" in result["diff"]

    read = await ws_read_file(cfg=cfg, path="code.py")
    assert "x = 42" in read["content"]


@pytest.mark.asyncio
async def test_update_file_not_found(cfg):
    with pytest.raises(ValueError, match="not found"):
        await ws_update_file(cfg=cfg, path="nope.txt", old_string="a", new_string="b")


@pytest.mark.asyncio
async def test_update_string_not_found(cfg):
    await ws_write_file(cfg=cfg, path="f.txt", content="hello")
    with pytest.raises(ValueError, match="old_string not found"):
        await ws_update_file(cfg=cfg, path="f.txt", old_string="nope", new_string="x")


@pytest.mark.asyncio
async def test_exec(cfg):
    result = await ws_exec(cfg=cfg, command="echo hello")
    assert result["exit_code"] == 0
    assert "hello" in result["stdout"]
    assert result["timed_out"] is False


@pytest.mark.asyncio
async def test_exec_timeout(cfg):
    cfg.exec_timeout_max = 1
    result = await ws_exec(cfg=cfg, command="sleep 10", timeout=1)
    assert result["timed_out"] is True


@pytest.mark.asyncio
async def test_path_traversal_blocked(cfg):
    with pytest.raises(ValueError, match="inside workspace"):
        await ws_read_file(cfg=cfg, path="../../etc/passwd")


@pytest.mark.asyncio
async def test_display_image(cfg, tmp_path):
    # Create a fake image file in the workspace
    base = _base_dir("default")
    img = base / "chart.png"
    img.write_bytes(b"fake png data")

    result = await display_image(cfg=cfg, path="chart.png", caption="A chart")
    assert result["displayed"] is True
    assert result["caption"] == "A chart"


@pytest.mark.asyncio
async def test_display_image_not_found(cfg):
    with pytest.raises(ValueError, match="not found"):
        await display_image(cfg=cfg, path="nope.png")


@pytest.mark.asyncio
async def test_display_image_bad_format(cfg):
    base = _base_dir("default")
    (base / "file.txt").write_text("not an image")
    with pytest.raises(ValueError, match="Unsupported"):
        await display_image(cfg=cfg, path="file.txt")
