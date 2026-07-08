"""Workspace tools — file I/O and shell execution.

All tools take a WorkspaceConfig and operate relative to the workspace
base directory (~/.dataclaw/workspaces/ by default). Path traversal
outside the base directory is prevented.
"""

from __future__ import annotations

import asyncio
import difflib
import html as html_lib
import json
import uuid
from pathlib import Path
from typing import Any

from dataclaw.config.paths import workspaces_dir
from dataclaw_artifacts.sections import (
    TABLE_PREVIEW_MAX_BYTES,
    clean_text,
    normalize_section,
    section_attrs as artifact_section_attrs,
    section_meta_script as artifact_section_meta_script,
)

from dataclaw_workspace.config import WorkspaceConfig

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
_REPORT_SECTION_START = "<!-- DATACLAW_REPORT_SECTIONS_START -->"
_REPORT_SECTION_END = "<!-- DATACLAW_REPORT_SECTIONS_END -->"
# Project directory override — set per-request via hook when a project is active.
_project_dir: Path | None = None


def set_project_dir(d: Path | None) -> None:
    global _project_dir
    _project_dir = d


# ── Path helpers ────────────────────────────────────────────────────────────


def _safe_id(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in value.strip())
    return safe or "default"


def _base_dir(workspace_id: str = "default") -> Path:
    if _project_dir is not None:
        _project_dir.mkdir(parents=True, exist_ok=True)
        return _project_dir
    base = workspaces_dir() / _safe_id(workspace_id)
    base.mkdir(parents=True, exist_ok=True)
    return base


def _resolve_path(workspace_id: str, path: str) -> Path:
    """Resolve a path within the workspace, preventing traversal."""
    base = _base_dir(workspace_id).resolve()
    raw = Path(path).expanduser()
    resolved = raw.resolve() if raw.is_absolute() else (base / raw).resolve()
    try:
        resolved.relative_to(base)
    except ValueError as exc:
        raise ValueError(f"Path must be inside workspace directory: {base}") from exc
    return resolved


# ── Tools ───────────────────────────────────────────────────────────────────


async def ws_list_files(
    *,
    cfg: WorkspaceConfig,
    path: str = ".",
    pattern: str = "*",
    recursive: bool = False,
    workspace_id: str = "default",
) -> dict[str, Any]:
    """List files and directories in the workspace."""
    base = _base_dir(workspace_id).resolve()
    target = _resolve_path(workspace_id, path)
    if not target.is_dir():
        raise ValueError(f"Not a directory: {path}")

    entries: list[dict[str, Any]] = []
    truncated = False
    iterator = target.rglob(pattern) if recursive else target.glob(pattern)

    for item in iterator:
        if len(entries) >= cfg.max_list_entries:
            truncated = True
            break
        try:
            rel = str(item.relative_to(base))
            st = item.stat()
            entries.append({
                "name": rel,
                "type": "dir" if item.is_dir() else "file",
                "size": st.st_size,
            })
        except (OSError, ValueError):
            continue

    return {
        "path": path,
        "entries": entries,
        "truncated": truncated,
    }


async def ws_read_file(
    *,
    cfg: WorkspaceConfig,
    path: str,
    offset: int = 0,
    limit: int | None = None,
    workspace_id: str = "default",
) -> dict[str, Any]:
    """Read the contents of a file in the workspace."""
    resolved = _resolve_path(workspace_id, path)
    if not resolved.is_file():
        raise ValueError(f"File not found: {path}")

    size = resolved.stat().st_size
    if offset == 0 and limit is None and size > cfg.max_read_bytes:
        raise ValueError(
            f"File too large ({size} bytes, max {cfg.max_read_bytes}). "
            "Use offset/limit to read a portion."
        )

    text = resolved.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines(keepends=True)
    total_lines = len(lines)

    if offset or limit is not None:
        end = (offset + limit) if limit is not None else None
        lines = lines[offset:end]

    content = "".join(lines)
    return {
        "path": path,
        "content": content,
        "total_lines": total_lines,
        "lines_returned": len(lines),
        "size": size,
    }


async def ws_write_file(
    *,
    cfg: WorkspaceConfig,
    path: str,
    content: str,
    workspace_id: str = "default",
) -> dict[str, Any]:
    """Write or create a file in the workspace."""
    encoded = content.encode("utf-8")
    if len(encoded) > cfg.max_write_bytes:
        raise ValueError(
            f"Content too large ({len(encoded)} bytes, max {cfg.max_write_bytes})"
        )

    resolved = _resolve_path(workspace_id, path)
    created = not resolved.exists()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_bytes(encoded)

    return {
        "path": path,
        "size": len(encoded),
        "created": created,
    }


async def ws_update_file(
    *,
    cfg: WorkspaceConfig,
    path: str,
    old_string: str,
    new_string: str,
    replace_all: bool = False,
    workspace_id: str = "default",
) -> dict[str, Any]:
    """Find and replace text within a workspace file."""
    resolved = _resolve_path(workspace_id, path)
    if not resolved.is_file():
        raise ValueError(f"File not found: {path}")

    original = resolved.read_text(encoding="utf-8", errors="replace")
    if old_string not in original:
        raise ValueError(f"old_string not found in {path}")

    if replace_all:
        updated = original.replace(old_string, new_string)
        count = original.count(old_string)
    else:
        updated = original.replace(old_string, new_string, 1)
        count = 1

    resolved.write_text(updated, encoding="utf-8")
    diff = "".join(difflib.unified_diff(
        original.splitlines(keepends=True),
        updated.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
    ))
    return {
        "path": path,
        "replacements": count,
        "diff": diff,
    }


async def ws_exec(
    *,
    cfg: WorkspaceConfig,
    command: str,
    timeout: int | None = None,
    workspace_id: str = "default",
) -> dict[str, Any]:
    """Run a shell command in the workspace directory."""
    effective_timeout = min(
        max(timeout or cfg.exec_timeout_default, 1),
        cfg.exec_timeout_max,
    )
    cwd = _base_dir(workspace_id)
    timed_out = False

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=effective_timeout,
        )
    except asyncio.TimeoutError:
        timed_out = True
        proc.kill()  # type: ignore[possibly-undefined]
        stdout_bytes, stderr_bytes = await proc.communicate()  # type: ignore[possibly-undefined]

    max_out = cfg.max_exec_output_bytes
    stdout = stdout_bytes[:max_out].decode("utf-8", errors="replace")
    stderr = stderr_bytes[:max_out].decode("utf-8", errors="replace")

    return {
        "command": command,
        "exit_code": proc.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "timed_out": timed_out,
    }


async def build_report(
    *,
    cfg: WorkspaceConfig,
    html: str | None = None,
    html_path: str | None = None,
    output_path: str = "report.html",
    workspace_id: str = "default",
    **_: Any,
) -> dict[str, Any]:
    """Build an HTML report and save it to the workspace with a Word (.docx) export."""
    if not html and not html_path:
        raise ValueError("Provide either 'html' (raw HTML string) or 'html_path' (path to HTML file)")
    if html and html_path:
        raise ValueError("Provide only one of 'html' or 'html_path', not both")

    if html_path:
        resolved_input = _resolve_path(workspace_id, html_path)
        if not resolved_input.is_file():
            raise ValueError(f"HTML file not found: {html_path}")
        html = resolved_input.read_text(encoding="utf-8")

    # Ensure output ends with .html
    if not output_path.endswith(".html"):
        output_path = output_path.rsplit(".", 1)[0] + ".html"

    resolved_html = _resolve_path(workspace_id, output_path)
    resolved_html.parent.mkdir(parents=True, exist_ok=True)
    resolved_html.write_text(html, encoding="utf-8")

    # Generate .docx alongside
    docx_path = output_path.rsplit(".", 1)[0] + ".docx"
    resolved_docx = _resolve_path(workspace_id, docx_path)

    def _convert_docx() -> None:
        from html4docx import HtmlToDocx
        parser = HtmlToDocx()
        parser.parse_html_string(html)
        parser.doc.save(str(resolved_docx))

    try:
        await asyncio.to_thread(_convert_docx)
    except Exception:
        # DOCX generation is best-effort; don't fail the whole tool
        pass

    result: dict[str, Any] = {
        "html_path": str(resolved_html),
        "size": resolved_html.stat().st_size,
        "created": True,
    }
    if resolved_docx.exists():
        result["docx_path"] = str(resolved_docx)

    return result


async def report_add_section(
    *,
    cfg: WorkspaceConfig,
    section_type: str,
    data: dict[str, Any],
    report_path: str = "report.html",
    title: str = "Analysis Report",
    workspace_id: str = "default",
    **_: Any,
) -> dict[str, Any]:
    """Append a designed section to a live HTML report.

    This is the presentation layer counterpart to notebooks: notebooks do the
    computation, while this tool builds the readable report surface as findings
    emerge.
    """
    if not report_path.endswith(".html"):
        report_path = report_path.rsplit(".", 1)[0] + ".html"

    resolved = _resolve_path(workspace_id, report_path)
    resolved.parent.mkdir(parents=True, exist_ok=True)

    typed_section = _typed_report_section(section_type, data)
    section_html = _render_report_section(section_type, data, typed_section)
    if resolved.exists():
        doc = resolved.read_text(encoding="utf-8")
        if _REPORT_SECTION_END in doc:
            doc = doc.replace(_REPORT_SECTION_END, section_html + "\n" + _REPORT_SECTION_END, 1)
        else:
            doc += "\n" + section_html
    else:
        doc = _report_shell(title=title, first_section=section_html)

    resolved.write_text(doc, encoding="utf-8")
    return {
        "type": "report",
        "html_path": str(resolved),
        "section_type": section_type,
        "section": typed_section,
        "title": title,
        "size": resolved.stat().st_size,
        "updated": True,
    }


def _report_shell(*, title: str, first_section: str) -> str:
    safe_title = html_lib.escape(title)
    plotly_script = _plotly_script_tag()
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{safe_title}</title>
  {plotly_script}
  <style>
    :root {{
      color-scheme: light dark;
      --dc-bg: #f7f8fb;
      --dc-surface: #ffffff;
      --dc-surface-raised: #ffffff;
      --dc-surface-muted: #fbfcfe;
      --dc-ink: #111827;
      --dc-muted: #667085;
      --dc-line: #e5e7eb;
      --dc-accent: #2563eb;
      --dc-accent-soft: #e8f0ff;
      --dc-good: #15803d;
      --dc-warn: #b45309;
      --dc-danger: #b91c1c;
      --dc-shadow: 0 1px 2px rgba(16, 24, 40, 0.06);
      --bg: var(--dc-bg);
      --paper: var(--dc-surface);
      --ink: var(--dc-ink);
      --muted: var(--dc-muted);
      --line: var(--dc-line);
      --accent: var(--dc-accent);
      --accent-soft: var(--dc-accent-soft);
      --good: var(--dc-good);
      --warn: var(--dc-warn);
      --radius: 10px;
    }}
    :root[data-theme="dark"] {{
      --dc-bg: #0f141b;
      --dc-surface: #171d26;
      --dc-surface-raised: #1f2733;
      --dc-surface-muted: #141a22;
      --dc-ink: #f2f5f8;
      --dc-muted: #a5afbd;
      --dc-line: #303846;
      --dc-accent: #7aa7ff;
      --dc-accent-soft: #1b2b46;
      --dc-good: #6dd58c;
      --dc-warn: #f3bd63;
      --dc-danger: #ff8b8b;
      --dc-shadow: none;
      --good: var(--dc-good);
      --warn: var(--dc-warn);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font: 14px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, sans-serif;
    }}
    .r-page {{ max-width: 1040px; margin: 0 auto; padding: 28px 22px 40px; }}
    .r-hero {{
      background: var(--dc-surface);
      color: var(--dc-ink);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 30px;
      margin-bottom: 18px;
      box-shadow: var(--dc-shadow);
    }}
    .r-kicker {{ font-size: 12px; text-transform: uppercase; letter-spacing: 0; color: var(--accent); font-weight: 700; }}
    .r-hero h1 {{ margin: 8px 0 8px; font-size: 34px; line-height: 1.08; letter-spacing: 0; }}
    .r-hero p {{ max-width: 760px; margin: 0; color: var(--muted); font-size: 15px; }}
    .r-section {{
      background: var(--paper);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 18px;
      margin: 14px 0;
      box-shadow: var(--dc-shadow);
    }}
    .r-section h2, .r-section h3 {{ margin: 0 0 10px; line-height: 1.18; letter-spacing: 0; }}
    .r-section h2 {{ font-size: 21px; }}
    .r-section h3 {{ font-size: 16px; color: var(--muted); font-weight: 650; }}
    .r-grid {{ display: grid; gap: 12px; }}
    .r-grid.cols-2 {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    .r-metrics {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; }}
    .r-metric {{ border: 1px solid var(--line); border-radius: 8px; padding: 14px; background: var(--dc-surface-muted); }}
    .r-metric-label {{ font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0; font-weight: 700; }}
    .r-metric-value {{ font-size: 30px; font-weight: 760; margin-top: 4px; line-height: 1.1; }}
    .r-metric-delta {{ font-size: 12px; margin-top: 6px; color: var(--muted); }}
    .r-metric-delta.up {{ color: var(--good); }}
    .r-metric-delta.down {{ color: var(--dc-danger); }}
    .r-callout {{ border-left: 4px solid var(--accent); background: var(--accent-soft); padding: 13px 14px; border-radius: 8px; }}
    .r-findings {{ display: grid; gap: 10px; padding: 0; margin: 0; list-style: none; }}
    .r-finding {{ padding: 12px 14px; border: 1px solid var(--line); border-radius: 8px; background: var(--dc-surface-raised); }}
    .r-chart-target {{ width: 100%; min-height: 390px; }}
    .r-caption {{ color: var(--muted); font-size: 12px; margin: 8px 2px 0; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ padding: 9px 10px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }}
    th {{ color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0; }}
    @media (max-width: 720px) {{
      .r-page {{ padding: 16px 12px 28px; }}
      .r-hero {{ padding: 22px; }}
      .r-hero h1 {{ font-size: 26px; }}
      .r-grid.cols-2 {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <main class="r-page">
    {_REPORT_SECTION_START}
{first_section}
    {_REPORT_SECTION_END}
  </main>
</body>
</html>
"""


def _plotly_script_tag() -> str:
    """Declare the Plotly dependency without inlining or reaching for a CDN.

    Published artifacts receive the real Plotly bundle from the artifact runtime
    under a per-response nonce. The tiny fallback keeps raw workspace previews
    intelligible without competing with the artifact runtime when it is present.
    """
    return """<script data-dc-runtime="plotly">
window.Plotly = window.Plotly || {
  newPlot: function(target) {
    var el = typeof target === "string" ? document.getElementById(target) : target;
    if (el) {
      el.innerHTML = '<div class="r-caption" style="padding:18px;border:1px solid var(--line);border-radius:8px">Plotly is loaded by the DataClaw artifact runtime; chart data is embedded in the report source.</div>';
    }
  },
  react: function(target, data, layout, config) {
    return this.newPlot(target, data, layout, config);
  },
  purge: function() {}
};
</script>"""


def _typed_report_section(section_type: str, data: dict[str, Any]) -> dict[str, Any]:
    return normalize_section(section_type, data)


def _section_attrs(typed: dict[str, Any]) -> str:
    return artifact_section_attrs(typed)


def _section_meta_script(typed: dict[str, Any]) -> str:
    return artifact_section_meta_script(typed)


def _render_report_section(section_type: str, data: dict[str, Any], typed: dict[str, Any] | None = None) -> str:
    typed = typed or _typed_report_section(section_type, data)
    st = str(typed.get("kind") or section_type).strip().lower()
    attrs = _section_attrs(typed)
    meta = _section_meta_script(typed)
    if st == "header":
        title = _esc(data.get("title", "Analysis Report"))
        kicker = _esc(data.get("kicker", "Dataclaw report"))
        subtitle = _esc(data.get("subtitle", data.get("summary", "")))
        return f"""    <section class="r-hero" {attrs}>
      <div class="r-kicker">{kicker}</div>
      <h1>{title}</h1>
      {f'<p>{subtitle}</p>' if subtitle else ''}
      {meta}
    </section>"""

    if st == "metric_row":
        metrics = data.get("metrics", [])
        cards = []
        for m in metrics if isinstance(metrics, list) else []:
            if not isinstance(m, dict):
                continue
            trend = _esc(m.get("trend", ""))
            cards.append(f"""<div class="r-metric">
        <div class="r-metric-label">{_esc(m.get("label", ""))}</div>
        <div class="r-metric-value">{_esc(m.get("value", ""))}{f'<span style="font-size:13px;color:var(--muted);margin-left:5px">{_esc(m.get("unit", ""))}</span>' if m.get("unit") else ''}</div>
        {f'<div class="r-metric-delta {trend}">{_esc(m.get("delta", ""))}</div>' if m.get("delta") else ''}
      </div>""")
        return f"""    <section class="r-section" {attrs}>
      {f'<h2>{_esc(data.get("title", ""))}</h2>' if data.get("title") else ''}
      <div class="r-metrics">{''.join(cards)}</div>
      {meta}
    </section>"""

    if st == "chart":
        chart_id = f"chart-{uuid.uuid4().hex[:10]}"
        figure = data.get("figure")
        if not figure and data.get("figure_json"):
            figure = json.loads(str(data["figure_json"]))
        if not isinstance(figure, dict):
            raise ValueError("chart section requires 'figure' dict or 'figure_json'")
        figure_json = json.dumps(figure, default=str).replace("</", "<\\/")
        title = _esc(data.get("title", figure.get("layout", {}).get("title", {}).get("text", "Chart") if isinstance(figure.get("layout"), dict) else "Chart"))
        caption = _esc(data.get("caption", ""))
        return f"""    <section class="r-section" {attrs}>
      <h2>{title}</h2>
      <div id="{chart_id}" class="r-chart-target"></div>
      {f'<p class="r-caption">{caption}</p>' if caption else ''}
      <script>
        (function() {{
          var fig = {figure_json};
          Plotly.newPlot("{chart_id}", fig.data || [], fig.layout || {{}}, {{responsive: true, displaylogo: false}});
        }})();
      </script>
      {meta}
    </section>"""

    if st == "findings":
        items = data.get("items", data.get("findings", []))
        lis = "".join(f'<li class="r-finding">{_esc(str(item))}</li>' for item in (items if isinstance(items, list) else []))
        return f"""    <section class="r-section" {attrs}>
      <h2>{_esc(data.get("title", "Key findings"))}</h2>
      <ul class="r-findings">{lis}</ul>
      {meta}
    </section>"""

    if st in {"callout", "text"}:
        title = _esc(data.get("title", "Note"))
        body = _paragraphs(data.get("body", data.get("text", "")))
        class_name = "r-callout" if st == "callout" else ""
        return f"""    <section class="r-section" {attrs}>
      <div class="{class_name}">
        <h2>{title}</h2>
        {body}
      </div>
      {meta}
    </section>"""

    if st == "table":
        columns = data.get("columns", [])
        rows = data.get("rows", [])
        if not isinstance(columns, list) or not isinstance(rows, list):
            raise ValueError("table section requires list 'columns' and list 'rows'")
        head = "".join(f"<th>{_esc(str(c))}</th>" for c in columns)
        body_rows = []
        max_rows = int(data.get("max_rows", 20) or 20)
        max_bytes = int(data.get("max_bytes", TABLE_PREVIEW_MAX_BYTES) or TABLE_PREVIEW_MAX_BYTES)
        used_bytes = 0
        truncated = len(rows) > max_rows
        for row in rows[:max_rows]:
            if isinstance(row, dict):
                cells = [_esc(row.get(c, "")) for c in columns]
            else:
                cells = [_esc(v) for v in (row if isinstance(row, list) else [])]
            row_html = "<tr>" + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>"
            row_bytes = len(row_html.encode("utf-8"))
            if used_bytes + row_bytes > max_bytes:
                truncated = True
                break
            body_rows.append(row_html)
            used_bytes += row_bytes
        typed["payload"]["rows_rendered"] = len(body_rows)
        typed["payload"]["truncated"] = truncated
        meta = _section_meta_script(typed)
        note = '<p class="r-caption">Table preview truncated; source data remains in the notebook/workspace.</p>' if truncated else ''
        return f"""    <section class="r-section" {attrs}>
      <h2>{_esc(data.get("title", "Table"))}</h2>
      <table><thead><tr>{head}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>
      {note}
      {meta}
    </section>"""

    raise ValueError(f"Unsupported report section_type: {section_type}")


def _esc(value: Any) -> str:
    return html_lib.escape(clean_text(value))


def _paragraphs(value: Any) -> str:
    text = clean_text(value)
    parts = [p.strip() for p in text.split("\n\n") if p.strip()]
    return "".join(f"<p>{_esc(p)}</p>" for p in parts)


async def display_image(
    *,
    cfg: WorkspaceConfig,
    path: str,
    caption: str = "",
    title: str = "",
    workspace_id: str = "default",
) -> dict[str, Any]:
    """Display an image file to the user in the chat."""
    base = _base_dir(workspace_id)
    raw = Path(path).expanduser()
    file_path = raw.resolve() if raw.is_absolute() else (base / raw).resolve()

    if not file_path.exists() or not file_path.is_file():
        raise ValueError(f"Image file not found: {path}")
    if file_path.suffix.lower() not in _IMAGE_EXTENSIONS:
        raise ValueError(
            f"Unsupported image format: {file_path.suffix}. "
            f"Supported: {', '.join(sorted(_IMAGE_EXTENSIONS))}"
        )

    return {
        "path": str(file_path),
        "title": title or file_path.name,
        "caption": caption,
        "displayed": True,
    }
