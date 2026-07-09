"""Workspace file serving — serves files from workspace directories."""

from __future__ import annotations

import html
import re
from pathlib import Path
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse

from dataclaw.config.paths import workspaces_dir

router = APIRouter()
_RELATIVE_ASSET_RE = re.compile(
    r"(<(?:img|script|link|source|video|audio)\s[^>]*?\b(?:src|href)=['\"])(?![a-z][a-z0-9+.-]*:|/|#)([^'\"]+)(['\"])",
    re.IGNORECASE,
)
_REPORT_SANDBOX = "allow-scripts allow-forms allow-popups allow-modals"
_BODY_CLOSE_RE = re.compile(r"</body\s*>", re.IGNORECASE)
_PRINT_SCRIPT = """<script data-dc-preview-print>
window.addEventListener('load', function() {
  window.setTimeout(function() {
    try {
      window.focus();
      window.print();
    } catch (_err) {}
  }, 350);
});
</script>"""


def _workspace_file_href(path: Path, query: str = "", fragment: str = "") -> str:
    href = f"../files?path={quote(str(path), safe='')}"
    if query:
        href += f"&asset_query={quote(query, safe='')}"
    if fragment:
        href += f"#{fragment}"
    return href


def _rewrite_workspace_relative_urls(source: str, file_path: Path) -> str:
    base_dir = file_path.parent
    roots = _allowed_roots()

    def replace(match: re.Match[str]) -> str:
        prefix, relative_url, suffix = match.groups()
        parsed = urlsplit(relative_url)
        asset_path = (base_dir / parsed.path).resolve()
        if not any(asset_path.is_relative_to(root) for root in roots):
            return match.group(0)
        return f"{prefix}{_workspace_file_href(asset_path, parsed.query, parsed.fragment)}{suffix}"

    return _RELATIVE_ASSET_RE.sub(replace, source)


def _inject_print_script(source: str) -> str:
    if _PRINT_SCRIPT in source:
        return source
    if _BODY_CLOSE_RE.search(source):
        return _BODY_CLOSE_RE.sub(_PRINT_SCRIPT + r"\g<0>", source, count=1)
    return source + "\n" + _PRINT_SCRIPT


def _allowed_roots() -> list[Path]:
    """Build the list of directories from which files may be served."""
    roots = [
        workspaces_dir().resolve(),
        (Path.home() / "dataclaw-projects").resolve(),
    ]

    # Also allow every registered project directory (projects can live anywhere)
    try:
        from dataclaw_projects.registry import _read_registry
        for entry in _read_registry():
            d = entry.get("directory", "")
            if d:
                roots.append(Path(d).resolve())
    except Exception:
        pass

    return roots


def _resolve_allowed_file(path: str) -> Path:
    file_path = Path(path).expanduser().resolve()

    if not any(file_path.is_relative_to(root) for root in _allowed_roots()):
        raise HTTPException(403, "File path is outside allowed directories")

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(404, f"File not found: {path}")

    return file_path


@router.get("/files")
async def serve_file(path: str = Query(..., description="Absolute or workspace-relative file path")) -> FileResponse:
    """Serve a file from the workspace. Validates the path is within workspace bounds."""
    file_path = _resolve_allowed_file(path)

    headers = {"X-Content-Type-Options": "nosniff"}
    if file_path.suffix.lower() in {".html", ".htm", ".svg"}:
        headers["Content-Disposition"] = f'attachment; filename="{file_path.name}"'

    return FileResponse(file_path, headers=headers)


@router.get("/preview")
async def preview_html_file(
    path: str = Query(..., description="Absolute or workspace-relative HTML path"),
    print_report: bool = Query(False, alias="print"),
) -> HTMLResponse:
    """Open workspace HTML in a sandboxed browser preview.

    Raw `/files` keeps HTML/SVG as attachments so untrusted workspace files do
    not run at the DataClaw app origin. This preview shell is the intentional
    rendering path: the report runs in a sandboxed iframe without same-origin
    access to the app.
    """
    file_path = _resolve_allowed_file(path)
    if file_path.suffix.lower() not in {".html", ".htm"}:
        raise HTTPException(400, "Preview is only supported for HTML files")

    safe_title = html.escape(file_path.name)
    document_url = f"preview/document?path={quote(str(file_path), safe='')}"
    if print_report:
        document_url += "&print=1"
    safe_document_url = html.escape(document_url, quote=True)
    shell = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_title}</title>
  <style>
    html, body {{ margin: 0; height: 100%; background: #f7f8fb; }}
    body {{ overflow: hidden; }}
    iframe {{ display: block; width: 100%; height: 100vh; border: 0; background: #fff; }}
  </style>
</head>
<body>
  <iframe id="workspace-preview-frame" sandbox="{_REPORT_SANDBOX}" src="{safe_document_url}"></iframe>
</body>
</html>"""
    return HTMLResponse(
        shell,
        headers={
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
            "Content-Security-Policy": (
                "default-src 'none'; style-src 'unsafe-inline'; frame-src 'self'"
            ),
        },
    )


@router.get("/preview/document")
async def preview_html_document(
    path: str = Query(..., description="Absolute or workspace-relative HTML path"),
    print_report: bool = Query(False, alias="print"),
) -> HTMLResponse:
    """Serve the report document for a sandboxed preview iframe."""
    file_path = _resolve_allowed_file(path)
    if file_path.suffix.lower() not in {".html", ".htm"}:
        raise HTTPException(400, "Preview is only supported for HTML files")

    source = file_path.read_text(encoding="utf-8", errors="replace")
    rewritten = _rewrite_workspace_relative_urls(source, file_path)
    if print_report:
        rewritten = _inject_print_script(rewritten)
    return HTMLResponse(
        rewritten,
        headers={
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
            "Content-Security-Policy": (
                f"sandbox {_REPORT_SANDBOX}; "
                "default-src 'none'; "
                "script-src 'self' 'unsafe-inline' 'unsafe-eval' blob:; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data: blob:; "
                "font-src 'self' data:; "
                "worker-src blob:; "
                "connect-src 'none'; "
                "base-uri 'none'; "
                "form-action 'none'"
            ),
        },
    )
