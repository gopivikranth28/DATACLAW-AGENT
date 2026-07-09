"""Report renderer for DataClaw workspace reports."""

from __future__ import annotations

import html as html_lib
import json
import re
import uuid
from typing import Any

from dataclaw_artifacts.sections import (
    TABLE_PREVIEW_MAX_BYTES,
    clean_text,
    normalize_section,
    section_attrs as artifact_section_attrs,
    section_meta_script as artifact_section_meta_script,
)
from dataclaw_artifacts.wrapper import plotly_runtime_js

REPORT_SECTION_START = "<!-- DATACLAW_REPORT_SECTIONS_START -->"
REPORT_SECTION_END = "<!-- DATACLAW_REPORT_SECTIONS_END -->"
REPORT_SHELL_CSS_ATTR = 'data-dc-report-shell-css'
REPORT_SHELL_SCRIPT_ATTR = 'data-dc-report-shell-script'
BODY_OPEN_RE = re.compile(r"(<body\b[^>]*>)", re.IGNORECASE)
BODY_CLOSE_RE = re.compile(r"</body\s*>", re.IGNORECASE)


__all__ = [
    "REPORT_SECTION_END",
    "REPORT_SECTION_START",
    "ensure_plotly_runtime",
    "ensure_report_shell_context",
    "plotly_script_tag",
    "render_report_section",
    "report_shell",
    "report_shell_css",
    "report_shell_script",
    "typed_report_section",
]


def report_shell(*, title: str, first_section: str, include_plotly: bool = False) -> str:
    safe_title = html_lib.escape(title)
    plotly_script = plotly_script_tag() if include_plotly else ""
    shell_css = report_shell_css()
    shell_script = report_shell_script()
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{safe_title}</title>
  {plotly_script}
  <style {REPORT_SHELL_CSS_ATTR}>
{shell_css}
  </style>
</head>
<body>
  <div class="r-progress" aria-hidden="true"><span></span></div>
  <nav class="r-story-nav" aria-label="Report sections"></nav>
  <main class="r-page">
    {REPORT_SECTION_START}
{first_section}
    {REPORT_SECTION_END}
  </main>
  <script {REPORT_SHELL_SCRIPT_ATTR}>
{shell_script}
  </script>
</body>
</html>
"""


def report_shell_css() -> str:
    return """
:root {
  color-scheme: light dark;
  --dc-bg: #eef2f6;
  --dc-surface: #ffffff;
  --dc-surface-raised: #ffffff;
  --dc-surface-muted: #f8fafc;
  --dc-ink: #111827;
  --dc-muted: #667085;
  --dc-line: #d9e1ea;
  --dc-accent: #2563eb;
  --dc-accent-2: #0f766e;
  --dc-accent-3: #c2410c;
  --dc-accent-soft: #e8f0ff;
  --dc-good: #15803d;
  --dc-warn: #b45309;
  --dc-danger: #b91c1c;
  --dc-shadow: 0 18px 45px rgba(15, 23, 42, 0.10);
  --dc-shadow-soft: 0 7px 22px rgba(15, 23, 42, 0.07);
  --bg: var(--dc-bg);
  --paper: var(--dc-surface);
  --ink: var(--dc-ink);
  --muted: var(--dc-muted);
  --line: var(--dc-line);
  --accent: var(--dc-accent);
  --accent-soft: var(--dc-accent-soft);
  --good: var(--dc-good);
  --warn: var(--dc-warn);
}
:root[data-theme="dark"] {
  --dc-bg: #0f141b;
  --dc-surface: #171d26;
  --dc-surface-raised: #1f2733;
  --dc-surface-muted: #141a22;
  --dc-ink: #f2f5f8;
  --dc-muted: #a5afbd;
  --dc-line: #303846;
  --dc-accent: #7aa7ff;
  --dc-accent-2: #5eead4;
  --dc-accent-3: #fdba74;
  --dc-accent-soft: #1b2b46;
  --dc-good: #6dd58c;
  --dc-warn: #f3bd63;
  --dc-danger: #ff8b8b;
  --dc-shadow: none;
  --dc-shadow-soft: none;
  --good: var(--dc-good);
  --warn: var(--dc-warn);
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0;
  background:
    linear-gradient(180deg, rgba(37, 99, 235, 0.10), rgba(15, 118, 110, 0.04) 320px, transparent 580px),
    var(--bg);
  color: var(--ink);
  font: 14px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, sans-serif;
}
.r-progress { position: fixed; inset: 0 0 auto; height: 3px; background: transparent; z-index: 30; }
.r-progress span { display: block; height: 100%; width: 0; background: linear-gradient(90deg, var(--dc-accent), var(--dc-accent-2), var(--dc-accent-3)); transition: width .18s ease; }
.r-story-nav {
  position: sticky;
  top: 0;
  z-index: 20;
  display: none;
  gap: 8px;
  align-items: center;
  overflow-x: auto;
  padding: 10px max(16px, calc((100vw - 1100px) / 2 + 18px));
  background: color-mix(in srgb, var(--dc-surface) 88%, transparent);
  border-bottom: 1px solid var(--line);
  backdrop-filter: blur(12px);
}
.r-story-nav.ready { display: flex; }
.r-story-nav a {
  flex: 0 0 auto;
  max-width: 210px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 6px 11px;
  color: var(--muted);
  background: var(--dc-surface-muted);
  font-size: 12px;
  text-decoration: none;
  transition: color .16s ease, background .16s ease, border-color .16s ease, transform .16s ease;
}
.r-story-nav a.active, .r-story-nav a:hover {
  color: var(--ink);
  border-color: color-mix(in srgb, var(--dc-accent) 45%, var(--line));
  background: var(--accent-soft);
  transform: translateY(-1px);
}
.r-page { max-width: 1100px; margin: 0 auto; padding: 30px 22px 48px; }
.r-hero {
  position: relative;
  overflow: hidden;
  background: linear-gradient(135deg, rgba(37, 99, 235, 0.16), rgba(15, 118, 110, 0.14)), var(--dc-surface);
  color: var(--dc-ink);
  border: 1px solid color-mix(in srgb, var(--dc-accent) 18%, var(--line));
  border-radius: 18px;
  padding: 38px;
  margin-bottom: 20px;
  box-shadow: var(--dc-shadow);
}
.r-hero::after {
  content: "";
  position: absolute;
  right: 26px;
  bottom: 24px;
  width: 140px;
  height: 140px;
  border: 1px solid color-mix(in srgb, var(--dc-accent-2) 30%, transparent);
  transform: rotate(12deg);
  opacity: .45;
  pointer-events: none;
}
.r-kicker { font-size: 12px; text-transform: uppercase; letter-spacing: .08em; color: var(--accent); font-weight: 760; }
.r-hero h1 { position: relative; margin: 8px 0 10px; max-width: 850px; font-size: clamp(30px, 5vw, 54px); line-height: 1.02; letter-spacing: 0; }
.r-hero p { position: relative; max-width: 790px; margin: 0; color: var(--muted); font-size: 16px; }
.r-section {
  position: relative;
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: 16px;
  padding: 22px;
  margin: 18px 0;
  box-shadow: var(--dc-shadow-soft);
  transform: translateY(8px);
  opacity: .96;
  transition: transform .24s ease, opacity .24s ease, box-shadow .24s ease, border-color .24s ease;
}
.r-section.in-view, .r-hero.in-view { transform: translateY(0); opacity: 1; }
.r-section:focus-within, .r-section:hover {
  border-color: color-mix(in srgb, var(--dc-accent) 26%, var(--line));
  box-shadow: var(--dc-shadow);
}
.r-section::before {
  content: counter(story-step, decimal-leading-zero);
  counter-increment: story-step;
  position: absolute;
  top: 18px;
  right: 20px;
  color: color-mix(in srgb, var(--dc-accent) 52%, var(--line));
  font-size: 12px;
  font-weight: 760;
}
main { counter-reset: story-step; }
.r-section h2, .r-section h3 { margin: 0 0 10px; line-height: 1.18; letter-spacing: 0; }
.r-section h2 { padding-right: 54px; font-size: 23px; }
.r-section h3 { font-size: 16px; color: var(--muted); font-weight: 650; }
.r-section-dek { max-width: 760px; margin: 0 0 12px; color: var(--muted); font-size: 14px; }
.r-section-context { display: grid; gap: 10px; margin: 0 0 14px; }
.r-pill-row { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
.r-method-note {
  border-left: 3px solid var(--dc-accent-2);
  background: color-mix(in srgb, var(--dc-accent-2) 8%, var(--dc-surface-muted));
  padding: 10px 12px;
  border-radius: 0 12px 12px 0;
  color: var(--ink);
}
.r-method-note strong { display: block; font-size: 11px; text-transform: uppercase; letter-spacing: 0; color: var(--muted); margin-bottom: 3px; }
.r-method-note p { margin: 0; color: var(--ink); }
.r-bullets { display: grid; gap: 7px; margin: 0; padding: 0; list-style: none; }
.r-bullets li { position: relative; padding-left: 18px; color: var(--ink); }
.r-bullets li::before { content: ""; position: absolute; left: 2px; top: .72em; width: 6px; height: 6px; border-radius: 999px; background: var(--accent); }
.r-grid { display: grid; gap: 12px; }
.r-grid.cols-2 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.r-section[data-dc-section="metric_row"], .r-section[data-dc-section="insight_grid"] {
  background: transparent;
  border-color: transparent;
  box-shadow: none;
  padding: 6px 0;
}
.r-section[data-dc-section="metric_row"]::before, .r-section[data-dc-section="insight_grid"]::before { display: none; }
.r-section[data-dc-section="chart"] { background: linear-gradient(180deg, var(--dc-surface), var(--dc-surface-muted)); }
.r-section[data-dc-section="hypothesis_ledger"], .r-section[data-dc-section="evidence_trace"] {
  border-left: 4px solid color-mix(in srgb, var(--dc-accent-2) 55%, var(--line));
}
.r-metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }
.r-metric { border: 1px solid var(--line); border-radius: 12px; padding: 15px; background: linear-gradient(180deg, var(--dc-surface-raised), var(--dc-surface-muted)); }
.r-metric-label { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0; font-weight: 700; }
.r-metric-value { font-size: 32px; font-weight: 780; margin-top: 4px; line-height: 1.1; color: var(--dc-accent-2); }
.r-metric-delta { font-size: 12px; margin-top: 6px; color: var(--muted); }
.r-metric-delta.up { color: var(--good); }
.r-metric-delta.down { color: var(--dc-danger); }
.r-callout { border-left: 4px solid var(--accent); background: var(--accent-soft); padding: 15px 16px; border-radius: 12px; }
.r-findings { display: grid; gap: 10px; padding: 0; margin: 0; list-style: none; }
.r-finding { padding: 13px 15px; border: 1px solid var(--line); border-radius: 12px; background: var(--dc-surface-raised); }
.r-finding-title { font-weight: 720; margin-bottom: 4px; color: var(--ink); }
.r-finding-detail { margin: 0; color: var(--ink); }
.r-finding-meta { margin: 6px 0 0; color: var(--muted); font-size: 12px; }
.r-insight-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 12px; }
.r-insight-card {
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 15px;
  background: linear-gradient(180deg, var(--dc-surface-raised), var(--dc-surface-muted));
  box-shadow: var(--dc-shadow-soft);
}
.r-chip { display: inline-flex; align-items: center; border-radius: 999px; padding: 2px 8px; font-size: 11px; font-weight: 720; background: var(--accent-soft); color: var(--accent); }
.r-chip.good { background: color-mix(in srgb, var(--dc-good) 14%, transparent); color: var(--dc-good); }
.r-chip.warn { background: color-mix(in srgb, var(--dc-warn) 16%, transparent); color: var(--dc-warn); }
.r-chip.danger { background: color-mix(in srgb, var(--dc-danger) 14%, transparent); color: var(--dc-danger); }
.r-chip.neutral { background: var(--dc-surface-muted); color: var(--muted); border: 1px solid var(--line); }
.r-insight-card h3, .r-step h3, .r-compare-card h3 { margin: 8px 0 6px; color: var(--ink); font-size: 16px; }
.r-insight-card p, .r-step p, .r-compare-card p { margin: 0; }
.r-meta-row { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 10px; color: var(--muted); font-size: 12px; }
.r-steps { display: grid; gap: 11px; }
.r-step { display: grid; grid-template-columns: auto 1fr; gap: 12px; align-items: start; }
.r-step-num { width: 30px; height: 30px; border-radius: 999px; display: inline-flex; align-items: center; justify-content: center; background: var(--accent-soft); color: var(--accent); font-weight: 780; font-size: 12px; }
.r-comparison { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }
.r-compare-card { border: 1px solid var(--line); border-radius: 14px; background: var(--dc-surface-muted); padding: 15px; }
.r-compare-metric { display: flex; justify-content: space-between; gap: 12px; padding: 7px 0; border-top: 1px solid var(--line); font-size: 13px; }
.r-compare-metric:first-of-type { border-top: 0; }
.r-compare-value { font-weight: 760; color: var(--ink); text-align: right; }
.r-checks { display: grid; gap: 8px; }
.r-check { display: grid; grid-template-columns: auto 1fr auto; gap: 10px; align-items: start; border: 1px solid var(--line); border-radius: 12px; padding: 11px 12px; background: var(--dc-surface-muted); }
.r-check-dot { width: 10px; height: 10px; border-radius: 999px; margin-top: 5px; background: var(--muted); }
.r-check.pass .r-check-dot, .r-check.good .r-check-dot { background: var(--dc-good); }
.r-check.warning .r-check-dot, .r-check.warn .r-check-dot { background: var(--dc-warn); }
.r-check.fail .r-check-dot, .r-check.blocked .r-check-dot, .r-check.error .r-check-dot, .r-check.danger .r-check-dot { background: var(--dc-danger); }
.r-check-title { font-weight: 720; color: var(--ink); }
.r-ledger { display: grid; gap: 10px; position: relative; }
.r-ledger-item { border: 1px solid var(--line); border-left: 3px solid var(--dc-accent-2); border-radius: 12px; padding: 12px 14px; background: var(--dc-surface-raised); }
.r-ledger-top { display: flex; gap: 8px; justify-content: space-between; align-items: start; flex-wrap: wrap; }
.r-evidence-ref { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; color: var(--muted); }
.r-chart-target { width: 100%; min-height: 390px; }
.r-caption { color: var(--muted); font-size: 12px; margin: 8px 2px 0; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { padding: 9px 10px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }
th { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0; }
@media (prefers-reduced-motion: reduce) {
  html { scroll-behavior: auto; }
  .r-section, .r-story-nav a, .r-progress span { transition: none; }
}
@media (max-width: 720px) {
  .r-story-nav { padding: 8px 12px; }
  .r-page { padding: 16px 12px 28px; }
  .r-hero { padding: 24px; border-radius: 14px; }
  .r-hero h1 { font-size: 26px; }
  .r-grid.cols-2 { grid-template-columns: 1fr; }
}
"""


def report_shell_script() -> str:
    return """
(function() {
  var sections = Array.prototype.slice.call(document.querySelectorAll('.r-hero, .r-section'));
  var nav = document.querySelector('.r-story-nav');
  var progress = document.querySelector('.r-progress span');
  if (!sections.length) return;
  sections.forEach(function(section, index) {
    if (!section.id) {
      var rawId = section.getAttribute('data-dc-section-id') || ('story-' + index);
      var baseId = rawId.replace(/[^A-Za-z0-9_-]/g, '-');
      var candidate = baseId || ('story-' + index);
      var suffix = 2;
      while (document.getElementById(candidate)) {
        candidate = baseId + '-' + suffix;
        suffix += 1;
      }
      section.id = candidate;
    }
    var heading = section.querySelector('h1, h2, h3');
    var label = heading ? heading.textContent.trim() : 'Section ' + (index + 1);
    if (nav && sections.length > 1) {
      var link = document.createElement('a');
      link.href = '#' + section.id;
      link.textContent = label;
      link.dataset.target = section.id;
      nav.appendChild(link);
    }
  });
  if (nav && nav.children.length > 1) nav.classList.add('ready');
  var navLinks = nav ? Array.prototype.slice.call(nav.querySelectorAll('a')) : [];
  var markActive = function(id) {
    navLinks.forEach(function(link) {
      link.classList.toggle('active', link.dataset.target === id);
    });
  };
  if ('IntersectionObserver' in window) {
    var observer = new IntersectionObserver(function(entries) {
      entries.forEach(function(entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add('in-view');
          markActive(entry.target.id);
        }
      });
    }, { rootMargin: '-18% 0px -62% 0px', threshold: 0.01 });
    sections.forEach(function(section) { observer.observe(section); });
  } else {
    sections.forEach(function(section) { section.classList.add('in-view'); });
  }
  var updateProgress = function() {
    if (!progress) return;
    var doc = document.documentElement;
    var max = Math.max(1, doc.scrollHeight - window.innerHeight);
    var pct = Math.min(100, Math.max(0, (window.scrollY / max) * 100));
    progress.style.width = pct + '%';
  };
  window.addEventListener('scroll', updateProgress, { passive: true });
  updateProgress();
})();
"""


def plotly_script_tag() -> str:
    """Embed the local Plotly dependency for raw workspace report files.

    Published artifacts strip this workspace runtime during validation and
    receive the artifact runtime under a per-response nonce. Raw reports opened
    from ``file://`` still need the runtime inline so downloaded HTML renders.
    """
    return f"""<script data-dc-runtime="plotly">
{plotly_runtime_js()}
</script>"""


def ensure_plotly_runtime(doc: str) -> str:
    if 'data-dc-runtime="plotly"' in doc:
        return doc
    runtime = plotly_script_tag()
    if "</head>" in doc:
        return doc.replace("</head>", f"  {runtime}\n</head>", 1)
    return runtime + "\n" + doc


def ensure_report_shell_context(doc: str) -> str:
    """Upgrade existing report HTML with the current shell CSS/JS affordances."""
    migrated = doc
    if REPORT_SHELL_CSS_ATTR not in migrated and ".r-story-nav" not in migrated:
        style = f"  <style {REPORT_SHELL_CSS_ATTR}>\n{report_shell_css()}\n  </style>\n"
        if "</head>" in migrated:
            migrated = migrated.replace("</head>", style + "</head>", 1)
        else:
            migrated = style + migrated

    controls = '  <div class="r-progress" aria-hidden="true"><span></span></div>\n  <nav class="r-story-nav" aria-label="Report sections"></nav>\n'
    if 'class="r-progress"' not in migrated:
        migrated = _insert_after_body_open(migrated, controls)
    if 'class="r-story-nav"' not in migrated:
        migrated = _insert_after_body_open(migrated, '  <nav class="r-story-nav" aria-label="Report sections"></nav>\n')

    script_present = (
        REPORT_SHELL_SCRIPT_ATTR in migrated
        or "document.querySelectorAll('.r-hero, .r-section')" in migrated
    )
    if not script_present:
        script = f"  <script {REPORT_SHELL_SCRIPT_ATTR}>\n{report_shell_script()}\n  </script>"
        if BODY_CLOSE_RE.search(migrated):
            migrated = BODY_CLOSE_RE.sub(script + r"\g<0>", migrated, count=1)
        else:
            migrated += "\n" + script
    return migrated


def _insert_after_body_open(doc: str, html: str) -> str:
    if BODY_OPEN_RE.search(doc):
        return BODY_OPEN_RE.sub(r"\g<1>\n" + html, doc, count=1)
    return html + doc


def typed_report_section(section_type: str, data: dict[str, Any]) -> dict[str, Any]:
    return normalize_section(section_type, data)


def _section_attrs(typed: dict[str, Any]) -> str:
    return artifact_section_attrs(typed)


def _section_meta_script(typed: dict[str, Any]) -> str:
    return artifact_section_meta_script(typed)


def render_report_section(section_type: str, data: dict[str, Any], typed: dict[str, Any] | None = None) -> str:
    typed = typed or typed_report_section(section_type, data)
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
      {_section_context(data)}
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
      {_section_context({k: v for k, v in data.items() if k != "caption"})}
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
        lis = "".join(_render_finding_item(item) for item in (items if isinstance(items, list) else []))
        return f"""    <section class="r-section" {attrs}>
      <h2>{_esc(data.get("title", "Key findings"))}</h2>
      {_section_context(data)}
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
      {_section_context(data)}
      <table><thead><tr>{head}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>
      {note}
      {meta}
    </section>"""

    if st == "insight_grid":
        items = data.get("items", data.get("insights", []))
        if not isinstance(items, list):
            raise ValueError("insight_grid section requires list 'items' or 'insights'")
        cards = "".join(_render_insight_card(item) for item in items)
        return f"""    <section class="r-section" {attrs}>
      <h2>{_esc(data.get("title", "Structured insights"))}</h2>
      {_section_context(data)}
      <div class="r-insight-grid">{cards}</div>
      {meta}
    </section>"""

    if st == "explanation":
        steps = data.get("steps", data.get("points", []))
        if steps is None:
            steps = []
        if not isinstance(steps, list):
            raise ValueError("explanation section requires list 'steps' or 'points'")
        body = _paragraphs(data.get("body", data.get("summary", "")))
        rendered_steps = "".join(_render_explanation_step(step, i) for i, step in enumerate(steps))
        return f"""    <section class="r-section" {attrs}>
      <h2>{_esc(data.get("title", "How to read this analysis"))}</h2>
      {_section_context(data)}
      {body}
      {f'<div class="r-steps">{rendered_steps}</div>' if rendered_steps else ''}
      {meta}
    </section>"""

    if st == "comparison":
        groups = data.get("groups", data.get("items", []))
        metrics = data.get("metrics", [])
        if not isinstance(groups, list):
            raise ValueError("comparison section requires list 'groups' or 'items'")
        if metrics and not isinstance(metrics, list):
            raise ValueError("comparison section 'metrics' must be a list")
        cards = "".join(_render_comparison_group(group, metrics) for group in groups)
        return f"""    <section class="r-section" {attrs}>
      <h2>{_esc(data.get("title", "Comparison"))}</h2>
      {_section_context(data)}
      <div class="r-comparison">{cards}</div>
      {meta}
    </section>"""

    if st == "checklist":
        checks = data.get("checks", data.get("items", []))
        if not isinstance(checks, list):
            raise ValueError("checklist section requires list 'checks' or 'items'")
        rows = "".join(_render_check_item(check) for check in checks)
        return f"""    <section class="r-section" {attrs}>
      <h2>{_esc(data.get("title", "Validation checklist"))}</h2>
      {_section_context(data)}
      <div class="r-checks">{rows}</div>
      {meta}
    </section>"""

    if st == "hypothesis_ledger":
        hypotheses = data.get("hypotheses", data.get("items", []))
        if not isinstance(hypotheses, list):
            raise ValueError("hypothesis_ledger section requires list 'hypotheses' or 'items'")
        rows = "".join(_render_hypothesis_item(item) for item in hypotheses)
        return f"""    <section class="r-section" {attrs}>
      <h2>{_esc(data.get("title", "Hypothesis ledger"))}</h2>
      {_section_context(data)}
      <div class="r-ledger">{rows}</div>
      {meta}
    </section>"""

    if st == "evidence_trace":
        items = data.get("evidence", data.get("items", []))
        if not isinstance(items, list):
            raise ValueError("evidence_trace section requires list 'evidence' or 'items'")
        rows = "".join(_render_evidence_item(item) for item in items)
        return f"""    <section class="r-section" {attrs}>
      <h2>{_esc(data.get("title", "Evidence trace"))}</h2>
      {_section_context(data)}
      <div class="r-ledger">{rows}</div>
      {meta}
    </section>"""

    raise ValueError(f"Unsupported report section_type: {section_type}")


def _esc(value: Any) -> str:
    return html_lib.escape(clean_text(value))


def _render_pill_row(values: Any) -> str:
    pills = []
    for value in _as_list(values):
        if isinstance(value, dict):
            label = value.get("label") or value.get("name") or value.get("value") or value.get("text")
            status = value.get("status") or value.get("state") or label
            pills.append(_chip(label, _status_class(status)))
        else:
            pills.append(_chip(value, "neutral"))
    rendered = "".join(pills)
    return f'<div class="r-pill-row">{rendered}</div>' if rendered else ""


def _render_bullet_list(values: Any) -> str:
    items = []
    for value in _as_list(values):
        if isinstance(value, dict):
            text = value.get("text") or value.get("label") or value.get("value") or value.get("title")
        else:
            text = value
        if clean_text(text):
            items.append(f"<li>{_esc(text)}</li>")
    return f'<ul class="r-bullets">{"".join(items)}</ul>' if items else ""


def _section_context(data: dict[str, Any]) -> str:
    parts: list[str] = []
    caption = clean_text(data.get("caption") or "")
    if caption:
        parts.append(f'<p class="r-section-dek">{_esc(caption)}</p>')
    pills = data.get("pills") or data.get("tags") or data.get("labels")
    if pills:
        parts.append(_render_pill_row(pills))
    methodology = data.get("methodology") or data.get("method") or data.get("approach")
    if methodology:
        parts.append(f'<div class="r-method-note"><strong>Method</strong>{_paragraphs(methodology)}</div>')
    bullets = data.get("bullets") or data.get("key_points") or data.get("takeaways")
    if bullets:
        parts.append(_render_bullet_list(bullets))
    rendered = "".join(part for part in parts if part)
    return f'<div class="r-section-context">{rendered}</div>' if rendered else ""


def _chip(text: Any, class_name: str = "") -> str:
    label = _esc(text)
    if not label:
        return ""
    klass = f"r-chip {class_name}".strip()
    return f'<span class="{klass}">{label}</span>'


def _status_class(value: Any) -> str:
    status = clean_text(value).lower()
    if status in {"pass", "passed", "ready", "validated", "confirmed", "active", "complete", "completed"}:
        return "good"
    if status in {"warning", "warn", "caveat", "unknown", "medium", "unresolved", "needs_review"}:
        return "warn"
    if status in {"fail", "failed", "blocked", "blocker", "error", "implausible"}:
        return "danger"
    return "neutral"


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _item_title(item: dict[str, Any], fallback: str = "Insight") -> str:
    return clean_text(
        item.get("title")
        or item.get("headline")
        or item.get("statement")
        or item.get("name")
        or fallback
    )


def _item_detail(item: dict[str, Any]) -> str:
    return clean_text(
        item.get("summary")
        or item.get("detail")
        or item.get("description")
        or item.get("rationale")
        or item.get("text")
        or item.get("body")
        or ""
    )


def _render_insight_card(item: Any) -> str:
    if not isinstance(item, dict):
        return f'<article class="r-insight-card"><p>{_esc(item)}</p></article>'
    status = item.get("severity") or item.get("disposition") or item.get("status") or item.get("confidence")
    chips = [
        _chip(status, _status_class(status)),
        _chip(item.get("confidence"), "neutral") if item.get("confidence") and item.get("confidence") != status else "",
        _chip(item.get("finding_id"), "neutral"),
        _chip(item.get("hypothesis_id"), "neutral"),
    ]
    evidence = item.get("evidence")
    caveat = item.get("caveat") or item.get("limitation")
    next_action = item.get("next_action") or item.get("action")
    bullets = _render_bullet_list(item.get("bullets") or item.get("points") or item.get("supporting_points"))
    method = item.get("method") or item.get("methodology")
    return f"""<article class="r-insight-card">
      <div class="r-meta-row">{''.join(chips)}</div>
      <h3>{_esc(_item_title(item))}</h3>
      {f'<p>{_esc(_item_detail(item))}</p>' if _item_detail(item) else ''}
      {bullets}
      {f'<p class="r-finding-meta"><strong>Method:</strong> {_esc(method)}</p>' if method else ''}
      {f'<p class="r-finding-meta"><strong>Evidence:</strong> {_esc(evidence)}</p>' if evidence else ''}
      {f'<p class="r-finding-meta"><strong>Caveat:</strong> {_esc(caveat)}</p>' if caveat else ''}
      {f'<p class="r-finding-meta"><strong>Next:</strong> {_esc(next_action)}</p>' if next_action else ''}
    </article>"""


def _render_explanation_step(step: Any, index: int) -> str:
    if not isinstance(step, dict):
        return f"""<div class="r-step">
      <span class="r-step-num">{index + 1}</span>
      <div><p>{_esc(step)}</p></div>
    </div>"""
    title = _item_title(step, f"Step {index + 1}")
    detail = _item_detail(step)
    evidence = step.get("evidence") or step.get("evidence_ref")
    return f"""<div class="r-step">
      <span class="r-step-num">{index + 1}</span>
      <div>
        <h3>{_esc(title)}</h3>
        {f'<p>{_esc(detail)}</p>' if detail else ''}
        {f'<p class="r-finding-meta"><strong>Evidence:</strong> {_esc(evidence)}</p>' if evidence else ''}
      </div>
    </div>"""


def _render_comparison_group(group: Any, metrics: list[Any]) -> str:
    if not isinstance(group, dict):
        return f'<article class="r-compare-card"><h3>{_esc(group)}</h3></article>'
    title = _item_title(group, "Group")
    detail = _item_detail(group)
    bullets = _render_bullet_list(group.get("bullets") or group.get("points") or group.get("takeaways"))
    group_metrics = group.get("metrics")
    rows = []
    if isinstance(group_metrics, dict):
        rows = [(str(k), v) for k, v in group_metrics.items()]
    elif isinstance(group_metrics, list):
        for metric in group_metrics:
            if isinstance(metric, dict):
                rows.append((clean_text(metric.get("label") or metric.get("name") or metric.get("key")), metric.get("value", "")))
            else:
                rows.append(("", metric))
    elif metrics:
        values = group.get("values") if isinstance(group.get("values"), dict) else group
        for metric in metrics:
            if isinstance(metric, dict):
                key = clean_text(metric.get("key") or metric.get("name") or metric.get("label"))
                label = clean_text(metric.get("label") or key)
            else:
                key = clean_text(metric)
                label = key
            rows.append((label, values.get(key, "") if isinstance(values, dict) else ""))
    rendered = "".join(
        f'<div class="r-compare-metric"><span>{_esc(label)}</span><span class="r-compare-value">{_esc(value)}</span></div>'
        for label, value in rows
        if label or value not in ("", None)
    )
    return f"""<article class="r-compare-card">
      <h3>{_esc(title)}</h3>
      {f'<p class="r-caption">{_esc(detail)}</p>' if detail else ''}
      {bullets}
      {rendered}
    </article>"""


def _render_check_item(check: Any) -> str:
    if not isinstance(check, dict):
        return f'<div class="r-check"><span class="r-check-dot"></span><div><div class="r-check-title">{_esc(check)}</div></div></div>'
    status = check.get("status") or check.get("state") or ""
    status_class = _status_class(status)
    title = _item_title(check, "Check")
    detail = _item_detail(check)
    evidence = check.get("evidence") or check.get("evidence_ref")
    return f"""<div class="r-check {status_class}">
      <span class="r-check-dot"></span>
      <div>
        <div class="r-check-title">{_esc(title)}</div>
        {f'<p class="r-finding-meta">{_esc(detail)}</p>' if detail else ''}
        {f'<p class="r-evidence-ref">{_esc(evidence)}</p>' if evidence else ''}
      </div>
      {_chip(status, status_class)}
    </div>"""


def _render_hypothesis_item(item: Any) -> str:
    if not isinstance(item, dict):
        return f'<article class="r-ledger-item"><p>{_esc(item)}</p></article>'
    status = item.get("status") or item.get("disposition") or "open"
    linked = ", ".join(clean_text(v) for v in _as_list(item.get("linked_finding_ids") or item.get("finding_ids")) if clean_text(v))
    covers = ", ".join(clean_text(v) for v in _as_list(item.get("covers_checks")) if clean_text(v))
    bullets = _render_bullet_list(item.get("bullets") or item.get("tests") or item.get("next_steps"))
    return f"""<article class="r-ledger-item">
      <div class="r-ledger-top">
        <strong>{_esc(_item_title(item, "Hypothesis"))}</strong>
        <span>{_chip(status, _status_class(status))}{_chip(item.get("priority"), "neutral")}</span>
      </div>
      {f'<p class="r-finding-meta">{_esc(_item_detail(item))}</p>' if _item_detail(item) else ''}
      {bullets}
      {f'<p class="r-evidence-ref">Hypothesis: {_esc(item.get("hypothesis_id") or item.get("id"))}</p>' if item.get("hypothesis_id") or item.get("id") else ''}
      {f'<p class="r-evidence-ref">Findings: {_esc(linked)}</p>' if linked else ''}
      {f'<p class="r-evidence-ref">Checks: {_esc(covers)}</p>' if covers else ''}
    </article>"""


def _render_evidence_item(item: Any) -> str:
    if not isinstance(item, dict):
        return f'<article class="r-ledger-item"><p>{_esc(item)}</p></article>'
    kind = item.get("kind") or item.get("type") or "evidence"
    ref = item.get("ref") or item.get("cell_id") or item.get("artifact_id") or item.get("finding_id") or item.get("path")
    status = item.get("status") or ("stale" if item.get("stale") else "active")
    bullets = _render_bullet_list(item.get("bullets") or item.get("checks") or item.get("notes"))
    return f"""<article class="r-ledger-item">
      <div class="r-ledger-top">
        <strong>{_esc(_item_title(item, clean_text(kind).replace("_", " ").title()))}</strong>
        <span>{_chip(kind, "neutral")}{_chip(status, _status_class(status))}</span>
      </div>
      {f'<p class="r-finding-meta">{_esc(_item_detail(item))}</p>' if _item_detail(item) else ''}
      {bullets}
      {f'<p class="r-evidence-ref">{_esc(ref)}</p>' if ref else ''}
    </article>"""


def _render_finding_item(item: Any) -> str:
    if not isinstance(item, dict):
        return f'<li class="r-finding">{_esc(item)}</li>'

    title = item.get("title") or item.get("headline") or item.get("finding") or item.get("name")
    detail = (
        item.get("detail")
        or item.get("summary")
        or item.get("description")
        or item.get("text")
        or item.get("body")
    )
    evidence = item.get("evidence")
    caveat = item.get("caveat") or item.get("limitation")
    bullets = _render_bullet_list(item.get("bullets") or item.get("points"))

    if not title and not detail:
        parts = []
        for key, value in item.items():
            if value in (None, ""):
                continue
            label = str(key).replace("_", " ").title()
            parts.append(f'<p class="r-finding-meta"><strong>{_esc(label)}:</strong> {_esc(value)}</p>')
        body = "".join(parts) or '<p class="r-finding-detail">No finding text provided.</p>'
        return f'<li class="r-finding">{body}</li>'

    title_html = f'<div class="r-finding-title">{_esc(title)}</div>' if title else ""
    detail_html = f'<p class="r-finding-detail">{_esc(detail)}</p>' if detail else ""
    evidence_html = f'<p class="r-finding-meta"><strong>Evidence:</strong> {_esc(evidence)}</p>' if evidence else ""
    caveat_html = f'<p class="r-finding-meta"><strong>Caveat:</strong> {_esc(caveat)}</p>' if caveat else ""
    return f'<li class="r-finding">{title_html}{detail_html}{bullets}{evidence_html}{caveat_html}</li>'


def _paragraphs(value: Any) -> str:
    text = clean_text(value)
    parts = [p.strip() for p in text.split("\n\n") if p.strip()]
    return "".join(f"<p>{_esc(p)}</p>" for p in parts)
