from __future__ import annotations

import pytest
from fastapi import HTTPException

import dataclaw.config.paths as paths
from dataclaw.api.routers.files import serve_file


@pytest.mark.asyncio
async def test_workspace_file_route_blocks_prefix_spoof(tmp_path, monkeypatch):
    home = tmp_path / ".dataclaw"
    monkeypatch.setattr(paths, "DATACLAW_HOME", home)
    (home / "workspaces").mkdir(parents=True)
    evil_root = tmp_path / ".dataclaw" / "workspaces_evil"
    evil_root.mkdir()
    evil = evil_root / "report.html"
    evil.write_text("<h1>nope</h1>", encoding="utf-8")

    with pytest.raises(HTTPException) as exc:
        await serve_file(path=str(evil))

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_workspace_file_route_serves_html_as_attachment(tmp_path, monkeypatch):
    home = tmp_path / ".dataclaw"
    monkeypatch.setattr(paths, "DATACLAW_HOME", home)
    workspace = home / "workspaces"
    workspace.mkdir(parents=True)
    report = workspace / "report.html"
    report.write_text("<h1>download</h1>", encoding="utf-8")

    response = await serve_file(path=str(report))

    assert response.headers["content-disposition"] == 'attachment; filename="report.html"'
    assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.asyncio
async def test_workspace_file_route_serves_svg_as_attachment(tmp_path, monkeypatch):
    home = tmp_path / ".dataclaw"
    monkeypatch.setattr(paths, "DATACLAW_HOME", home)
    workspace = home / "workspaces"
    workspace.mkdir(parents=True)
    svg = workspace / "hostile.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg"><script>fetch("/api/providers")</script></svg>',
        encoding="utf-8",
    )

    response = await serve_file(path=str(svg))

    assert response.headers["content-disposition"] == 'attachment; filename="hostile.svg"'
    assert response.headers["x-content-type-options"] == "nosniff"
