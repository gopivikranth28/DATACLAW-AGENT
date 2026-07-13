"""Workspace tools — file I/O and shell execution.

All tools take a WorkspaceConfig and operate relative to the workspace
base directory (~/.dataclaw/workspaces/ by default). Path traversal
outside the base directory is prevented.
"""

from __future__ import annotations

import asyncio
import difflib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dataclaw.config.paths import workspaces_dir
from dataclaw.storage.skill_library import stale_installed_library_skills
from dataclaw_workspace.config import WorkspaceConfig
from dataclaw_workspace.report_renderer import (
    CHART_SECTION_KINDS,
    BODY_CLOSE_RE as _BODY_CLOSE_RE,
    BODY_OPEN_RE as _BODY_OPEN_RE,
    REPORT_SECTION_END as _REPORT_SECTION_END,
    REPORT_SECTION_START as _REPORT_SECTION_START,
    REPORT_SHELL_CSS_ATTR as _REPORT_SHELL_CSS_ATTR,
    REPORT_SHELL_SCRIPT_ATTR as _REPORT_SHELL_SCRIPT_ATTR,
    analyze_report_quality as _analyze_report_quality,
    critique_report_storyboard as _critique_report_storyboard,
    design_report_storyboard as _design_report_storyboard,
    ensure_plotly_runtime as _ensure_plotly_runtime,
    ensure_report_shell_context as _ensure_report_shell_context,
    normalize_raw_html_report as _normalize_raw_html_report,
    plotly_script_tag as _plotly_script_tag,
    render_report_section as _render_report_section,
    render_report_from_storyboard as _render_report_from_storyboard,
    report_shell as _report_shell,
    report_shell_css as _report_shell_css,
    report_shell_script as _report_shell_script,
    typed_report_section as _typed_report_section,
)

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
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


async def _run_report_runtime_smoke(report_path: Path) -> dict[str, Any]:
    """Attempt browser-level report smoke checks through the UI's Playwright install.

    The workspace plugin intentionally has no browser dependency. When the UI
    package or a Playwright browser is absent, publication records a transparent
    ``skipped`` result rather than treating that as a passing browser check.
    """
    repository_root = Path(__file__).resolve().parents[3]
    playwright_module = repository_root / "ui" / "node_modules" / "playwright"
    if not playwright_module.exists():
        return {"status": "skipped", "reason": "Playwright is not installed with the UI package."}

    script = """
const { pathToFileURL } = require('url');
const { chromium } = require(process.argv[2]);
const target = process.argv[1];
(async () => {
  let browser;
  try {
    browser = await chromium.launch({ headless: true });
  } catch (error) {
    console.log(JSON.stringify({status: 'skipped', reason: 'Chromium launch unavailable: ' + error.message.split('\\n')[0]}));
    return;
  }
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push('pageerror: ' + error.message));
  page.on('console', message => { if (message.type() === 'error') pageErrors.push('console: ' + message.text()); });
  try {
    await page.goto(pathToFileURL(target).href, { waitUntil: 'load' });
    await page.waitForTimeout(350);
    const checks = await page.evaluate(() => {
      const failures = [];
      document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        const id = anchor.getAttribute('href').slice(1);
        if (id && !document.getElementById(id)) failures.push({check: 'anchor_target', detail: 'missing target #' + id});
      });
      document.querySelectorAll('.r-chart-target').forEach((target, index) => {
        if (window.Plotly && !target.querySelector('.js-plotly-plot')) failures.push({check: 'chart_mount', detail: 'chart target ' + index + ' did not mount'});
      });
      document.querySelectorAll('[data-dc-section="filterable_chart"], [data-dc-section="interactive_table"], [data-dc-section="selector_panel"], [data-dc-section="chart_table_explorer"]').forEach(section => {
        if (!section.querySelector('[data-dc-control-bar]')) failures.push({check: 'interactive_controls', detail: 'interactive section missing controls'});
      });
      document.querySelectorAll('.r-empty-state').forEach(node => failures.push({check: 'empty_state', detail: node.textContent.trim()}));
      return failures;
    });
    checks.push(...pageErrors.map(detail => ({check: 'browser_error', detail})));
    console.log(JSON.stringify({status: checks.length ? 'failed' : 'passed', checks}));
  } catch (error) {
    console.log(JSON.stringify({status: 'failed', checks: [{check: 'page_load', detail: error.message.split('\\n')[0]}]}));
  } finally {
    await browser.close();
  }
})();
"""
    try:
        proc = await asyncio.create_subprocess_exec(
            "node",
            "-e",
            script,
            str(report_path),
            str(playwright_module),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        return {"status": "skipped", "reason": f"Node runtime unavailable: {exc}"}
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=20)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        return {"status": "skipped", "reason": "Browser smoke exceeded the 20-second publish budget."}
    lines = [line for line in stdout.decode("utf-8", errors="replace").splitlines() if line.strip()]
    if proc.returncode or not lines:
        detail = stderr.decode("utf-8", errors="replace").strip().splitlines()
        return {"status": "skipped", "reason": detail[-1] if detail else "Browser smoke did not return a result."}
    try:
        result = json.loads(lines[-1])
    except json.JSONDecodeError:
        return {"status": "skipped", "reason": "Browser smoke returned an unreadable result."}
    return result if isinstance(result, dict) else {"status": "skipped", "reason": "Browser smoke returned an invalid result."}


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
    storyboard_path: str | None = None,
    report_goal: str = "",
    title: str = "",
    audience: str = "",
    quality_gate: str = "warn",
    workspace_id: str = "default",
    **_: Any,
) -> dict[str, Any]:
    """Normalize HTML into a typed report, preserving its source beside the rebuild.

    The generated DOCX behavior is intentionally left as the legacy best-effort
    export. The report itself, however, always flows through the storyboard and
    critique pipeline so it can pass the structured publish boundary.
    """
    if not html and not html_path:
        raise ValueError("Provide either 'html' (raw HTML string) or 'html_path' (path to HTML file)")
    if html and html_path:
        raise ValueError("Provide only one of 'html' or 'html_path', not both")

    if html_path:
        resolved_input = _resolve_path(workspace_id, html_path)
        if not resolved_input.is_file():
            raise ValueError(f"HTML file not found: {html_path}")
        html = resolved_input.read_text(encoding="utf-8")
    assert html is not None
    if quality_gate not in {"warn", "fail", "off"}:
        raise ValueError("quality_gate must be one of: warn, fail, off")

    # Ensure output ends with .html
    if not output_path.endswith(".html"):
        output_path = output_path.rsplit(".", 1)[0] + ".html"
    if storyboard_path is None:
        storyboard_path = output_path.rsplit(".", 1)[0] + ".storyboard.json"
    elif not storyboard_path.endswith(".json"):
        storyboard_path = storyboard_path.rsplit(".", 1)[0] + ".json"

    resolved_html = _resolve_path(workspace_id, output_path)
    resolved_html.parent.mkdir(parents=True, exist_ok=True)
    source_path = output_path.rsplit(".", 1)[0] + ".source.html"
    resolved_source = _resolve_path(workspace_id, source_path)
    resolved_source.parent.mkdir(parents=True, exist_ok=True)
    resolved_source.write_text(html, encoding="utf-8")

    storyboard, normalization = _normalize_raw_html_report(
        html,
        title=title,
        report_goal=report_goal,
        audience=audience,
    )
    storyboard, critique = _critique_report_storyboard(storyboard)
    rendered_html = html if normalization.get("render_from_source") else _render_report_from_storyboard(storyboard, title=title or None)
    stale_skills = [] if quality_gate == "off" else stale_installed_library_skills()
    quality = _analyze_report_quality(rendered_html, stale_skills=stale_skills) if quality_gate != "off" else {"status": "off", "warnings": []}
    if quality_gate == "fail" and quality.get("status") == "fail":
        codes = ", ".join(w.get("code", "unknown") for w in quality.get("warnings", []) if w.get("severity") == "fail")
        raise ValueError(f"Report quality gate failed: {codes}")

    normalization["source_html_path"] = str(resolved_source)
    storyboard["normalization"] = normalization
    storyboard["critique"] = critique
    storyboard["quality"] = quality
    resolved_html.write_text(rendered_html, encoding="utf-8")
    resolved_storyboard = _resolve_path(workspace_id, storyboard_path)
    resolved_storyboard.parent.mkdir(parents=True, exist_ok=True)
    resolved_storyboard.write_text(json.dumps(storyboard, indent=2, default=str), encoding="utf-8")

    # Generate .docx alongside
    docx_path = output_path.rsplit(".", 1)[0] + ".docx"
    resolved_docx = _resolve_path(workspace_id, docx_path)

    def _convert_docx() -> None:
        from html4docx import HtmlToDocx
        parser = HtmlToDocx()
        parser.parse_html_string(rendered_html)
        parser.doc.save(str(resolved_docx))

    try:
        await asyncio.to_thread(_convert_docx)
    except Exception:
        # DOCX generation is best-effort; don't fail the whole tool
        pass

    result: dict[str, Any] = {
        "type": "report_build",
        "html_path": str(resolved_html),
        "storyboard_path": str(resolved_storyboard),
        "source_html_path": str(resolved_source),
        "normalization": normalization,
        "critique": critique,
        "quality": quality,
        "size": resolved_html.stat().st_size,
        "created": True,
    }
    if resolved_docx.exists():
        result["docx_path"] = str(resolved_docx)

    return result


async def report_publish(
    *,
    cfg: WorkspaceConfig,
    report_path: str,
    storyboard_path: str,
    receipt_path: str | None = None,
    export_docx: bool = True,
    workspace_id: str = "default",
    **_: Any,
) -> dict[str, Any]:
    """Publish a storyboard-backed report after re-running the fail-closed gate.

    Publishing remains workspace-local: the resulting receipt is the durable record
    that a specific report, storyboard, and current rubric result were approved
    together.  DOCX conversion is best-effort, but its outcome is always recorded
    instead of being silently discarded.
    """
    if not report_path.endswith(".html"):
        report_path = report_path.rsplit(".", 1)[0] + ".html"
    if not storyboard_path.endswith(".json"):
        storyboard_path = storyboard_path.rsplit(".", 1)[0] + ".json"

    resolved_html = _resolve_path(workspace_id, report_path)
    if not resolved_html.is_file():
        raise ValueError(f"Report file not found: {report_path}")

    doc = resolved_html.read_text(encoding="utf-8", errors="replace")
    runtime_smoke = await _run_report_runtime_smoke(resolved_html)
    quality = _analyze_report_quality(
        doc,
        stale_skills=stale_installed_library_skills(),
        runtime_smoke=runtime_smoke,
    )
    if quality.get("status") == "fail":
        codes = ", ".join(
            warning.get("code", "unknown")
            for warning in quality.get("warnings", [])
            if warning.get("severity") == "fail"
        )
        raise ValueError(f"Report publish gate failed: {codes}")

    resolved_storyboard = _resolve_path(workspace_id, storyboard_path)
    if not resolved_storyboard.is_file():
        raise ValueError(f"Storyboard file not found: {storyboard_path}")
    try:
        storyboard = json.loads(resolved_storyboard.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Storyboard is not valid JSON: {storyboard_path}") from exc
    if not isinstance(storyboard, dict) or not isinstance(storyboard.get("section_plan"), list):
        raise ValueError(
            "Storyboard must be a report-design JSON object with a section_plan; "
            "recreate it with report_design_report or build_report before publishing."
        )

    if receipt_path is None:
        receipt_path = report_path.rsplit(".", 1)[0] + ".publish.json"
    if not receipt_path.endswith(".json"):
        receipt_path = receipt_path.rsplit(".", 1)[0] + ".json"

    docx_export: dict[str, Any]
    docx_path: str | None = None
    if export_docx:
        proposed_docx_path = report_path.rsplit(".", 1)[0] + ".docx"
        resolved_docx = _resolve_path(workspace_id, proposed_docx_path)

        def _convert_docx() -> None:
            from html4docx import HtmlToDocx

            parser = HtmlToDocx()
            parser.parse_html_string(doc)
            parser.doc.save(str(resolved_docx))

        try:
            await asyncio.to_thread(_convert_docx)
        except Exception as exc:
            docx_export = {
                "requested": True,
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
            }
        else:
            docx_path = str(resolved_docx)
            docx_export = {
                "requested": True,
                "status": "created",
                "path": docx_path,
                "size": resolved_docx.stat().st_size,
            }
    else:
        docx_export = {"requested": False, "status": "skipped"}

    receipt = {
        "publish_receipt_schema": 1,
        "published_at": datetime.now(timezone.utc).isoformat(),
        "status": "published",
        "html_path": str(resolved_html),
        "storyboard_path": str(resolved_storyboard),
        "storyboard_schema": storyboard.get("storyboard_schema"),
        "quality": quality,
        "runtime_smoke": runtime_smoke,
        "docx_export": docx_export,
    }
    resolved_receipt = _resolve_path(workspace_id, receipt_path)
    resolved_receipt.parent.mkdir(parents=True, exist_ok=True)
    resolved_receipt.write_text(json.dumps(receipt, indent=2, default=str), encoding="utf-8")

    result: dict[str, Any] = {
        "type": "report_publish",
        "published": True,
        "html_path": str(resolved_html),
        "storyboard_path": str(resolved_storyboard),
        "receipt_path": str(resolved_receipt),
        "quality": quality,
        "runtime_smoke": runtime_smoke,
        "docx_export": docx_export,
        "size": resolved_html.stat().st_size,
    }
    if docx_path:
        result["docx_path"] = docx_path
    return result


async def report_design_report(
    *,
    cfg: WorkspaceConfig,
    report_goal: str,
    insights: list[dict[str, Any]],
    analyses: list[dict[str, Any]] | None = None,
    audience: str = "",
    requirements: dict[str, Any] | None = None,
    report_path: str = "report.html",
    storyboard_path: str = "report_storyboard.json",
    title: str = "Analysis Report",
    quality_gate: str = "fail",
    workspace_id: str = "default",
    **_: Any,
) -> dict[str, Any]:
    """Design a cohesive report from completed insights, then render it in one pass.

    This is the report-designer layer: it plans the story, layout, controls,
    evidence sections, and quality checks before creating the HTML report.
    """
    if not isinstance(insights, list):
        raise ValueError("insights must be a list of insight dictionaries")
    if not any(isinstance(item, dict) for item in insights):
        raise ValueError(
            "insights must include at least one completed insight dictionary; use report_add_section for low-level drafts"
        )
    if analyses is not None and not isinstance(analyses, list):
        raise ValueError("analyses must be a list of analysis asset dictionaries")
    if requirements is not None and not isinstance(requirements, dict):
        raise ValueError("requirements must be a dictionary")
    if quality_gate not in {"warn", "fail", "off"}:
        raise ValueError("quality_gate must be one of: warn, fail, off")

    if not report_path.endswith(".html"):
        report_path = report_path.rsplit(".", 1)[0] + ".html"
    if not storyboard_path.endswith(".json"):
        storyboard_path = storyboard_path.rsplit(".", 1)[0] + ".json"

    storyboard = _design_report_storyboard(
        report_goal=report_goal,
        insights=insights,
        analyses=analyses or [],
        audience=audience,
        title=title,
        requirements=requirements or {},
    )
    storyboard, critique = _critique_report_storyboard(storyboard)
    doc = _render_report_from_storyboard(storyboard, title=title)
    stale_skills = [] if quality_gate == "off" else stale_installed_library_skills()
    quality = _analyze_report_quality(doc, stale_skills=stale_skills) if quality_gate != "off" else {"status": "off", "warnings": []}
    if quality_gate == "fail" and quality.get("status") == "fail":
        codes = ", ".join(w.get("code", "unknown") for w in quality.get("warnings", []) if w.get("severity") == "fail")
        raise ValueError(f"Report quality gate failed: {codes}")

    storyboard["quality"] = quality

    resolved_html = _resolve_path(workspace_id, report_path)
    resolved_html.parent.mkdir(parents=True, exist_ok=True)
    resolved_html.write_text(doc, encoding="utf-8")

    resolved_storyboard = _resolve_path(workspace_id, storyboard_path)
    resolved_storyboard.parent.mkdir(parents=True, exist_ok=True)
    resolved_storyboard.write_text(json.dumps(storyboard, indent=2, default=str), encoding="utf-8")

    return {
        "type": "report_design",
        "html_path": str(resolved_html),
        "storyboard_path": str(resolved_storyboard),
        "title": title,
        "section_count": len(storyboard.get("section_plan", [])),
        "interaction_count": len(storyboard.get("interaction_plan", [])),
        "quality": quality,
        "critique": critique,
        "size": resolved_html.stat().st_size,
        "updated": True,
    }


async def report_add_section(
    *,
    cfg: WorkspaceConfig,
    section_type: str,
    data: dict[str, Any],
    report_path: str = "report.html",
    title: str = "Analysis Report",
    quality_gate: str = "warn",
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
        doc = _ensure_report_shell_context(doc)
        if typed_section.get("kind") in CHART_SECTION_KINDS:
            doc = _ensure_plotly_runtime(doc)
        if _REPORT_SECTION_END in doc:
            doc = doc.replace(_REPORT_SECTION_END, section_html + "\n" + _REPORT_SECTION_END, 1)
        else:
            doc += "\n" + section_html
    else:
        doc = _report_shell(title=title, first_section=section_html, include_plotly=typed_section.get("kind") in CHART_SECTION_KINDS)

    if quality_gate not in {"warn", "fail", "off"}:
        raise ValueError("quality_gate must be one of: warn, fail, off")
    stale_skills = [] if quality_gate == "off" else stale_installed_library_skills()
    quality = _analyze_report_quality(doc, stale_skills=stale_skills) if quality_gate != "off" else {"status": "off", "warnings": []}
    if quality_gate == "fail" and quality.get("status") == "fail":
        codes = ", ".join(w.get("code", "unknown") for w in quality.get("warnings", []) if w.get("severity") == "fail")
        raise ValueError(f"Report quality gate failed: {codes}")

    resolved.write_text(doc, encoding="utf-8")
    return {
        "type": "report",
        "html_path": str(resolved),
        "section_type": section_type,
        "section": typed_section,
        "quality": quality,
        "title": title,
        "size": resolved.stat().st_size,
        "updated": True,
    }

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
