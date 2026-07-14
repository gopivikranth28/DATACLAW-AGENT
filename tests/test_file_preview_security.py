from __future__ import annotations

import socket
import threading
import time
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import HTTPException

import dataclaw.config.paths as paths
from dataclaw.api.routers.files import preview_html_document, preview_html_file, router, serve_file


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
async def test_workspace_html_preview_uses_sandbox_shell(tmp_path, monkeypatch):
    home = tmp_path / ".dataclaw"
    monkeypatch.setattr(paths, "DATACLAW_HOME", home)
    workspace = home / "workspaces"
    workspace.mkdir(parents=True)
    report = workspace / "report.html"
    report.write_text("<h1>preview</h1><script>window.reportReady = true</script>", encoding="utf-8")

    response = await preview_html_file(path=str(report))

    body = response.body.decode("utf-8")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-security-policy"].startswith("default-src 'none'")
    assert "Content-Disposition" not in response.headers
    assert 'sandbox="allow-scripts allow-forms allow-popups allow-modals"' in body
    assert "preview/document?path=" in body
    assert "workspace-preview-frame" in body
    assert "contentWindow.print" not in body
    assert "<h1>preview</h1>" not in body


@pytest.mark.asyncio
async def test_workspace_html_preview_url_encodes_case_insensitive_script_close_in_path(tmp_path, monkeypatch):
    home = tmp_path / ".dataclaw"
    monkeypatch.setattr(paths, "DATACLAW_HOME", home)
    workspace = home / "workspaces"
    report_dir = workspace / "foo<" / "SCRIPT"
    report_dir.mkdir(parents=True)
    report = report_dir / "report.html"
    report.write_text("<h1>preview</h1>", encoding="utf-8")

    response = await preview_html_file(path=str(report))

    body = response.body.decode("utf-8")
    assert "</SCRIPT" not in body
    assert "foo%3C%2FSCRIPT" in body


@pytest.mark.asyncio
async def test_workspace_html_preview_document_serves_interactive_html_with_csp(tmp_path, monkeypatch):
    home = tmp_path / ".dataclaw"
    monkeypatch.setattr(paths, "DATACLAW_HOME", home)
    workspace = home / "workspaces"
    report_dir = workspace / "reports"
    asset_dir = report_dir / "assets"
    asset_dir.mkdir(parents=True)
    (asset_dir / "report.js").write_text("window.reportReady = true", encoding="utf-8")
    report = report_dir / "report.html"
    report.write_text(
        '<h1>preview</h1><script>window.inlineReady = true</script><script src="assets/report.js?v=123#ready"></script>',
        encoding="utf-8",
    )

    response = await preview_html_document(path=str(report))

    body = response.body.decode("utf-8")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "Content-Disposition" not in response.headers
    csp = response.headers["content-security-policy"]
    assert "sandbox allow-scripts allow-forms allow-popups allow-modals" in csp
    assert "script-src 'self' 'unsafe-inline' 'unsafe-eval' blob:" in csp
    assert "<h1>preview</h1>" in body
    assert "window.inlineReady = true" in body
    assert "data-dc-preview-resize" in body
    assert "dataclaw:report-height" in body
    body_close = body.lower().find("</body>")
    if body_close >= 0:
        assert body.index("data-dc-preview-resize") < body_close
    assert 'src="../files?path=' in body
    assert "&asset_query=v%3D123#ready" in body
    assert "assets/report.js" not in body


@pytest.mark.asyncio
async def test_workspace_html_preview_rewrite_namespaces_asset_query_path(tmp_path, monkeypatch):
    home = tmp_path / ".dataclaw"
    monkeypatch.setattr(paths, "DATACLAW_HOME", home)
    workspace = home / "workspaces"
    report_dir = workspace / "reports"
    asset_dir = report_dir / "assets"
    asset_dir.mkdir(parents=True)
    asset = asset_dir / "report.js"
    other = workspace / "other.js"
    asset.write_text("window.reportReady = true", encoding="utf-8")
    other.write_text("window.wrongFile = true", encoding="utf-8")
    report = report_dir / "report.html"
    report.write_text(
        f'<script src="assets/report.js?path={other}&v=123"></script>',
        encoding="utf-8",
    )

    response = await preview_html_document(path=str(report))

    body = response.body.decode("utf-8")
    src = body.split('src="', 1)[1].split('"', 1)[0]
    params = parse_qs(urlsplit(src).query)
    assert params["path"] == [str(asset)]
    assert params["asset_query"] == [f"path={other}&v=123"]
    assert body.count("path=") == 1


@pytest.mark.asyncio
async def test_workspace_html_preview_print_is_triggered_inside_document(tmp_path, monkeypatch):
    home = tmp_path / ".dataclaw"
    monkeypatch.setattr(paths, "DATACLAW_HOME", home)
    workspace = home / "workspaces"
    workspace.mkdir(parents=True)
    report = workspace / "report.html"
    report.write_text("<h1>preview</h1></body>", encoding="utf-8")

    shell_response = await preview_html_file(path=str(report), print_report=True)
    document_response = await preview_html_document(path=str(report), print_report=True)

    shell_body = shell_response.body.decode("utf-8")
    document_body = document_response.body.decode("utf-8")
    assert "&amp;print=1" in shell_body
    assert "contentWindow.print" not in shell_body
    assert "data-dc-preview-print" in document_body
    assert "window.print()" in document_body
    assert document_body.index("data-dc-preview-print") < document_body.lower().index("</body>")


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


def test_workspace_html_preview_executes_in_real_browser_when_playwright_available(tmp_path, monkeypatch):
    playwright = pytest.importorskip("playwright.sync_api")
    from fastapi import FastAPI
    import uvicorn

    home = tmp_path / ".dataclaw"
    monkeypatch.setattr(paths, "DATACLAW_HOME", home)
    workspace = home / "workspaces"
    workspace.mkdir(parents=True)
    report = workspace / "interactive.html"
    report.write_text(
        """<!doctype html>
<html><body>
  <nav class="r-story-nav"></nav>
  <section class="r-hero" data-dc-section-id="sec-hero"><h1>Hero</h1></section>
  <section class="r-section" data-dc-section-id="sec-chart"><h2>Chart</h2><div id="chart"></div></section>
  <script>
    window.Plotly = { newPlot: function(id) { document.getElementById(id).textContent = 'plotly-ready'; } };
    Plotly.newPlot('chart');
    document.querySelector('.r-story-nav').classList.add('ready');
    window.reportReady = true;
  </script>
</body></html>""",
        encoding="utf-8",
    )

    app = FastAPI()
    app.include_router(router, prefix="/api/workspace")
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.time() + 5
        while not server.started and time.time() < deadline:
            time.sleep(0.05)
        if not server.started:
            pytest.skip("uvicorn preview smoke server did not start")

        try:
            with playwright.sync_playwright() as p:
                try:
                    browser = p.chromium.launch()
                except Exception as exc:
                    pytest.skip(f"Playwright Chromium is unavailable: {exc}")
                try:
                    page = browser.new_page()
                    page.goto(
                        f"http://127.0.0.1:{port}/api/workspace/preview?path={report}",
                        wait_until="networkidle",
                    )
                    frame = _preview_document_frame(page)
                    frame.wait_for_selector(".r-story-nav.ready", timeout=5000)
                    assert frame.evaluate("window.reportReady") is True
                    assert frame.evaluate("typeof window.Plotly") == "object"
                    assert frame.locator("#chart").inner_text() == "plotly-ready"
                finally:
                    browser.close()
        except Exception as exc:
            pytest.fail(f"browser preview smoke failed: {exc}")
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _preview_document_frame(page):
    deadline = time.time() + 5
    while time.time() < deadline:
        for frame in page.frames:
            if "/preview/document" in frame.url:
                return frame
        time.sleep(0.05)
    raise AssertionError("preview document iframe did not load")
