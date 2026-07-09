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
PLOTLY_RUNTIME_RE = re.compile(
    r"<script\b(?=[^>]*\bdata-dc-runtime=(['\"])plotly\1)[^>]*>.*?</script>",
    re.IGNORECASE | re.DOTALL,
)


__all__ = [
    "CHART_SECTION_KINDS",
    "REPORT_SECTION_END",
    "REPORT_SECTION_START",
    "analyze_report_quality",
    "design_report_storyboard",
    "ensure_plotly_runtime",
    "ensure_report_shell_context",
    "plotly_script_tag",
    "render_report_section",
    "render_report_from_storyboard",
    "report_shell",
    "report_shell_css",
    "report_shell_script",
    "typed_report_section",
]

CHART_SECTION_KINDS = {"chart", "chart_interpretation", "filterable_chart", "chart_table_explorer"}
INTERACTIVE_SECTION_KINDS = {"filterable_chart", "interactive_table", "selector_panel", "chart_table_explorer"}
STORY_SECTION_KINDS = {
    "findings",
    "insight_grid",
    "narrative_band",
    "methodology_block",
    "evidence_rail",
    "ledger_timeline",
    "chart_interpretation",
    "hypothesis_ledger",
    "evidence_trace",
    "filterable_chart",
    "interactive_table",
    "selector_panel",
    "chart_table_explorer",
    "entity_card_grid",
}
REPORT_QUALITY_MAX_BYTES = 1_500_000


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
.r-section[data-dc-section="chart"], .r-section[data-dc-section="chart_interpretation"], .r-section[data-dc-section="filterable_chart"], .r-section[data-dc-section="chart_table_explorer"], .r-section[data-dc-section="interactive_table"] { background: linear-gradient(180deg, var(--dc-surface), var(--dc-surface-muted)); }
.r-section[data-dc-section="narrative_band"] { background: linear-gradient(135deg, color-mix(in srgb, var(--dc-accent) 8%, var(--dc-surface)), var(--dc-surface)); border-left: 4px solid color-mix(in srgb, var(--dc-accent) 55%, var(--line)); }
.r-section[data-dc-section="methodology_block"] { background: color-mix(in srgb, var(--dc-accent-2) 5%, var(--dc-surface)); }
.r-section[data-dc-section="hypothesis_ledger"], .r-section[data-dc-section="evidence_trace"], .r-section[data-dc-section="ledger_timeline"], .r-section[data-dc-section="evidence_rail"] {
  border-left: 4px solid color-mix(in srgb, var(--dc-accent-2) 55%, var(--line));
}
.r-narrative-band { max-width: 820px; display: grid; gap: 12px; }
.r-narrative-band p { margin: 0; font-size: 15px; }
.r-methodology-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 12px; }
.r-method-card { border: 1px solid var(--line); border-radius: 12px; padding: 13px 14px; background: var(--dc-surface-raised); }
.r-method-card h3 { margin: 0 0 6px; color: var(--ink); }
.r-chart-story-grid, .r-evidence-layout { display: grid; grid-template-columns: minmax(0, 1fr) minmax(240px, 320px); gap: 18px; align-items: start; }
.r-chart-main { min-width: 0; }
.r-interpretation-panel, .r-evidence-rail { border: 1px solid var(--line); border-radius: 12px; padding: 14px; background: var(--dc-surface-raised); }
.r-interpretation-panel h3, .r-evidence-rail h3 { margin: 0 0 8px; color: var(--ink); font-size: 15px; }
.r-interpretation-panel p { margin: 0 0 8px; }
.r-evidence-rail { display: grid; gap: 10px; }
.r-evidence-rail.compact .r-ledger-item { padding: 10px 11px; border-left-width: 2px; }
.r-timeline { position: relative; display: grid; gap: 12px; padding-left: 20px; }
.r-timeline::before { content: ""; position: absolute; left: 6px; top: 6px; bottom: 6px; width: 2px; background: color-mix(in srgb, var(--dc-accent-2) 35%, var(--line)); }
.r-timeline-item { position: relative; border: 1px solid var(--line); border-radius: 12px; padding: 12px 14px; background: var(--dc-surface-raised); }
.r-timeline-item::before { content: ""; position: absolute; left: -19px; top: 16px; width: 10px; height: 10px; border-radius: 999px; background: var(--dc-accent-2); border: 2px solid var(--dc-surface); }
.r-timeline-top { display: flex; gap: 8px; justify-content: space-between; align-items: start; flex-wrap: wrap; }
.r-timeline-time { color: var(--muted); font-size: 12px; }
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
.r-interactive-shell { display: grid; gap: 14px; }
.r-control-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: end;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: color-mix(in srgb, var(--dc-surface-muted) 78%, var(--dc-surface));
}
.r-control { display: grid; gap: 4px; min-width: 150px; }
.r-control label, .r-table-meta { color: var(--muted); font-size: 11px; font-weight: 720; letter-spacing: 0; text-transform: uppercase; }
.r-control select, .r-table-tools input {
  width: 100%;
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 8px 10px;
  background: var(--dc-surface);
  color: var(--ink);
  font: inherit;
}
.r-explorer-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(280px, 380px); gap: 16px; align-items: start; }
.r-table-tools { display: flex; justify-content: space-between; gap: 10px; align-items: center; margin-bottom: 8px; flex-wrap: wrap; }
.r-table-tools input { max-width: 260px; }
.r-interactive-table-wrap { width: 100%; overflow: auto; border: 1px solid var(--line); border-radius: 12px; background: var(--dc-surface); }
.r-interactive-table th { cursor: pointer; user-select: none; white-space: nowrap; }
.r-interactive-table tbody tr:hover { background: color-mix(in srgb, var(--dc-accent-soft) 42%, transparent); }
.r-pagination { display: flex; gap: 8px; justify-content: flex-end; align-items: center; margin-top: 8px; color: var(--muted); font-size: 12px; }
.r-pagination button {
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 6px 10px;
  background: var(--dc-surface);
  color: var(--ink);
  cursor: pointer;
}
.r-pagination button:disabled { opacity: .45; cursor: default; }
.r-selector-panel { display: grid; gap: 14px; }
.r-entity-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 12px; }
.r-entity-card { border: 1px solid var(--line); border-radius: 12px; padding: 14px; background: var(--dc-surface-raised); }
.r-entity-card h3 { margin: 7px 0 6px; color: var(--ink); }
.r-entity-metrics { display: grid; gap: 6px; margin-top: 10px; }
.r-entity-metric { display: flex; justify-content: space-between; gap: 10px; border-top: 1px solid var(--line); padding-top: 6px; color: var(--muted); font-size: 12px; }
.r-entity-metric strong { color: var(--ink); text-align: right; }
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
  .r-grid.cols-2, .r-chart-story-grid, .r-evidence-layout, .r-explorer-grid { grid-template-columns: 1fr; }
  .r-interpretation-panel, .r-evidence-rail { position: static; }
}
"""


def report_shell_script() -> str:
    return """
(function() {
  function text(value) {
    return value === null || value === undefined ? '' : String(value);
  }
  function esc(value) {
    return text(value).replace(/[&<>"']/g, function(ch) {
      return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[ch];
    });
  }
  function cell(row, key) {
    return row && row[key] !== undefined && row[key] !== null ? row[key] : '';
  }
  function columnsFrom(rows, columns) {
    if (Array.isArray(columns) && columns.length) {
      return columns.map(function(col) {
        if (typeof col === 'string') return {key: col, label: col};
        return {key: text(col.key || col.name || col.label), label: text(col.label || col.name || col.key)};
      }).filter(function(col) { return col.key; });
    }
    var seen = {};
    var cols = [];
    (rows || []).forEach(function(row) {
      if (!row || typeof row !== 'object' || Array.isArray(row)) return;
      Object.keys(row).forEach(function(key) {
        if (!seen[key]) {
          seen[key] = true;
          cols.push({key: key, label: key.replace(/_/g, ' ')});
        }
      });
    });
    return cols;
  }
  function uniqueOptions(rows, key) {
    var seen = {};
    var options = [];
    (rows || []).forEach(function(row) {
      var value = text(cell(row, key));
      if (value && !seen[value]) {
        seen[value] = true;
        options.push({value: value, label: value});
      }
    });
    return options.sort(function(a, b) { return a.label.localeCompare(b.label); });
  }
  function normalizeFilters(filters, rows) {
    return (Array.isArray(filters) ? filters : []).map(function(filter) {
      if (typeof filter === 'string') filter = {key: filter, label: filter};
      var key = text(filter.key || filter.name || filter.field);
      if (!key) return null;
      var opts = Array.isArray(filter.options) ? filter.options.map(function(option) {
        if (option && typeof option === 'object') return {value: text(option.value || option.key || option.label), label: text(option.label || option.value || option.key)};
        return {value: text(option), label: text(option)};
      }) : uniqueOptions(rows, key);
      return {key: key, label: text(filter.label || key.replace(/_/g, ' ')), options: opts};
    }).filter(Boolean);
  }
  function buildControls(container, filters, rows, onChange) {
    var normalized = normalizeFilters(filters, rows);
    if (!container || !normalized.length) return function() { return {}; };
    container.innerHTML = '';
    normalized.forEach(function(filter) {
      var wrap = document.createElement('div');
      wrap.className = 'r-control';
      var label = document.createElement('label');
      label.textContent = filter.label;
      var select = document.createElement('select');
      select.setAttribute('data-dc-filter-key', filter.key);
      var all = document.createElement('option');
      all.value = '';
      all.textContent = 'All ' + filter.label;
      select.appendChild(all);
      filter.options.forEach(function(option) {
        var item = document.createElement('option');
        item.value = option.value;
        item.textContent = option.label;
        select.appendChild(item);
      });
      select.addEventListener('change', onChange);
      wrap.appendChild(label);
      wrap.appendChild(select);
      container.appendChild(wrap);
    });
    return function() {
      var values = {};
      Array.prototype.slice.call(container.querySelectorAll('select[data-dc-filter-key]')).forEach(function(select) {
        values[select.getAttribute('data-dc-filter-key')] = select.value;
      });
      return values;
    };
  }
  function applyFilters(rows, values) {
    var keys = Object.keys(values || {}).filter(function(key) { return values[key]; });
    if (!keys.length) return rows || [];
    return (rows || []).filter(function(row) {
      return keys.every(function(key) { return text(cell(row, key)) === values[key]; });
    });
  }
  function matchSearch(row, query, columns) {
    if (!query) return true;
    var haystack = columns.map(function(col) { return text(cell(row, col.key)); }).join(' ').toLowerCase();
    return haystack.indexOf(query.toLowerCase()) !== -1;
  }
  function renderChart(target, chart, rows) {
    if (!target || !window.Plotly) return;
    chart = chart || {};
    rows = rows || [];
    var xKey = chart.x || chart.x_key || 'x';
    var yKey = chart.y || chart.y_key || 'y';
    var colorKey = chart.color || chart.group || chart.series;
    var type = chart.type || 'bar';
    var grouped = {};
    function ensureGroup(name) {
      if (!grouped[name]) grouped[name] = {x: [], y: [], text: [], name: name, type: type};
      return grouped[name];
    }
    rows.forEach(function(row) {
      var name = colorKey ? text(cell(row, colorKey)) || 'Series' : chart.name || 'Series';
      var trace = ensureGroup(name);
      trace.x.push(cell(row, xKey));
      trace.y.push(cell(row, yKey));
      trace.text.push(text(row && (row.label || row.name) || ''));
    });
    var traces = Object.keys(grouped).map(function(key) {
      var trace = grouped[key];
      if (type === 'scatter') trace.mode = chart.mode || 'markers';
      return trace;
    });
    var layout = Object.assign({
      margin: {l: 46, r: 18, t: chart.title ? 34 : 16, b: 46},
      title: chart.title ? {text: chart.title} : undefined,
      xaxis: {title: chart.x_label || xKey},
      yaxis: {title: chart.y_label || yKey},
      paper_bgcolor: 'rgba(0,0,0,0)',
      plot_bgcolor: 'rgba(0,0,0,0)'
    }, chart.layout || {});
    Plotly.react(target, traces, layout, {responsive: true, displaylogo: false});
  }
  function initTable(root, config, rowsProvider) {
    var baseRows = config.rows || config.records || [];
    var cols = columnsFrom(baseRows, config.columns);
    var pageSize = Number(config.page_size || config.pageSize || 20);
    var state = {page: 1, sortKey: '', sortDir: 1, search: ''};
    var controls = root.querySelector('[data-dc-control-bar]');
    var getFilters = buildControls(controls, config.filters || config.controls || [], baseRows, function() { state.page = 1; render(); });
    var target = root.querySelector('[data-dc-interactive-table]');
    var tools = root.querySelector('[data-dc-table-tools]');
    var pager = root.querySelector('[data-dc-pagination]');
    if (tools && config.search !== false && config.enable_search !== false) {
      var input = document.createElement('input');
      input.type = 'search';
      input.placeholder = config.search_placeholder || 'Search table';
      input.addEventListener('input', function() { state.search = input.value; state.page = 1; render(); });
      tools.appendChild(input);
    }
    function activeRows() {
      var rows = typeof rowsProvider === 'function' ? rowsProvider() : baseRows;
      rows = applyFilters(rows, getFilters()).filter(function(row) { return matchSearch(row, state.search, cols); });
      if (state.sortKey) {
        rows = rows.slice().sort(function(a, b) {
          var av = cell(a, state.sortKey);
          var bv = cell(b, state.sortKey);
          var an = Number(av);
          var bn = Number(bv);
          if (!Number.isNaN(an) && !Number.isNaN(bn)) return (an - bn) * state.sortDir;
          return text(av).localeCompare(text(bv), undefined, {numeric: true}) * state.sortDir;
        });
      }
      return rows;
    }
    function render() {
      if (!target) return;
      var rows = activeRows();
      var pages = Math.max(1, Math.ceil(rows.length / pageSize));
      state.page = Math.min(state.page, pages);
      var start = (state.page - 1) * pageSize;
      var shown = rows.slice(start, start + pageSize);
      var head = '<thead><tr>' + cols.map(function(col) {
        var marker = state.sortKey === col.key ? (state.sortDir === 1 ? ' asc' : ' desc') : '';
        return '<th data-key="' + esc(col.key) + '">' + esc(col.label) + marker + '</th>';
      }).join('') + '</tr></thead>';
      var body = '<tbody>' + shown.map(function(row) {
        return '<tr>' + cols.map(function(col) { return '<td>' + esc(cell(row, col.key)) + '</td>'; }).join('') + '</tr>';
      }).join('') + '</tbody>';
      target.innerHTML = '<table class="r-interactive-table">' + head + body + '</table>';
      Array.prototype.slice.call(target.querySelectorAll('th[data-key]')).forEach(function(th) {
        th.addEventListener('click', function() {
          var key = th.getAttribute('data-key');
          state.sortDir = state.sortKey === key ? state.sortDir * -1 : 1;
          state.sortKey = key;
          render();
        });
      });
      if (tools) {
        var meta = tools.querySelector('.r-table-meta');
        if (!meta) {
          meta = document.createElement('span');
          meta.className = 'r-table-meta';
          tools.insertBefore(meta, tools.firstChild);
        }
        meta.textContent = rows.length + ' rows';
      }
      if (pager) {
        var end = Math.min(rows.length, start + pageSize);
        pager.innerHTML = '<button type="button" data-prev>Prev</button><span>Showing ' + (rows.length ? start + 1 : 0) + '-' + end + ' of ' + rows.length + '</span><button type="button" data-next>Next</button>';
        var prev = pager.querySelector('[data-prev]');
        var next = pager.querySelector('[data-next]');
        prev.disabled = state.page <= 1;
        next.disabled = state.page >= pages;
        prev.addEventListener('click', function() { state.page -= 1; render(); });
        next.addEventListener('click', function() { state.page += 1; render(); });
      }
    }
    render();
    return render;
  }
  window.DataClawReport = window.DataClawReport || {};
  window.DataClawReport.initInteractiveTable = function(id, config) {
    var root = document.getElementById(id);
    if (root) initTable(root, config || {});
  };
  window.DataClawReport.initFilterableChart = function(id, config) {
    var root = document.getElementById(id);
    if (!root) return;
    var records = config.records || config.rows || [];
    var target = root.querySelector('[data-dc-chart-target]');
    var getFilters = buildControls(root.querySelector('[data-dc-control-bar]'), config.filters || config.controls || [], records, update);
    function update() {
      renderChart(target, config.chart || {}, applyFilters(records, getFilters()));
    }
    update();
  };
  window.DataClawReport.initChartTableExplorer = function(id, config) {
    var root = document.getElementById(id);
    if (!root) return;
    var records = config.records || config.rows || [];
    var target = root.querySelector('[data-dc-chart-target]');
    var getFilters = buildControls(root.querySelector('[data-dc-control-bar]'), config.filters || config.controls || [], records, update);
    function currentRows() { return applyFilters(records, getFilters()); }
    var tableRender = initTable(root, Object.assign({}, config, {rows: records, filters: []}), currentRows);
    function update() {
      renderChart(target, config.chart || {}, currentRows());
      if (tableRender) tableRender();
    }
    update();
  };
  window.DataClawReport.initSelectorPanel = function(id, config) {
    var root = document.getElementById(id);
    if (!root) return;
    var items = config.items || config.options || [];
    var cards = Array.prototype.slice.call(root.querySelectorAll('[data-dc-selector-card]'));
    var getFilters = buildControls(root.querySelector('[data-dc-control-bar]'), config.controls || config.filters || [], items, update);
    function update() {
      var visible = {};
      applyFilters(items, getFilters()).forEach(function(item, index) {
        visible[text(item.id || item.key || item.name || index)] = true;
      });
      cards.forEach(function(card) {
        card.style.display = visible[card.getAttribute('data-dc-selector-card')] ? '' : 'none';
      });
    }
    update();
  };
  function runQueuedInteractive(item) {
    if (!item || !window.DataClawReport[item.fn]) return;
    window.DataClawReport[item.fn](item.id, item.config || {});
  }
  (window.__DataClawReportQueue || []).forEach(runQueuedInteractive);
  window.__DataClawReportQueue = {push: runQueuedInteractive};
  function initStoryShell() {
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
  }
  initStoryShell();
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
    style = f"  <style {REPORT_SHELL_CSS_ATTR}>\n{report_shell_css()}\n  </style>\n"
    if REPORT_SHELL_CSS_ATTR in migrated:
        migrated = re.sub(
            r"<style[^>]*data-dc-report-shell-css[^>]*>.*?</style>\s*",
            style,
            migrated,
            count=1,
            flags=re.IGNORECASE | re.DOTALL,
        )
    else:
        if "</head>" in migrated:
            migrated = migrated.replace("</head>", style + "</head>", 1)
        else:
            migrated = style + migrated

    controls = '  <div class="r-progress" aria-hidden="true"><span></span></div>\n  <nav class="r-story-nav" aria-label="Report sections"></nav>\n'
    if 'class="r-progress"' not in migrated:
        migrated = _insert_after_body_open(migrated, controls)
    if 'class="r-story-nav"' not in migrated:
        migrated = _insert_after_body_open(migrated, '  <nav class="r-story-nav" aria-label="Report sections"></nav>\n')

    script = f"  <script {REPORT_SHELL_SCRIPT_ATTR}>\n{report_shell_script()}\n  </script>"
    if REPORT_SHELL_SCRIPT_ATTR in migrated:
        migrated = re.sub(
            r"<script[^>]*data-dc-report-shell-script[^>]*>.*?</script>",
            script,
            migrated,
            count=1,
            flags=re.IGNORECASE | re.DOTALL,
        )
    elif "document.querySelectorAll('.r-hero, .r-section')" in migrated:
        migrated = re.sub(
            r"<script\b[^>]*>(?:(?!</script>).)*document\.querySelectorAll\('\.r-hero,\s*\.r-section'\)(?:(?!</script>).)*</script>",
            script,
            migrated,
            count=1,
            flags=re.IGNORECASE | re.DOTALL,
        )
    else:
        if BODY_CLOSE_RE.search(migrated):
            migrated = BODY_CLOSE_RE.sub(script + r"\g<0>", migrated, count=1)
        else:
            migrated += "\n" + script
    return migrated


def analyze_report_quality(
    doc: str,
    *,
    stale_skills: list[dict[str, Any]] | None = None,
    max_bytes: int = REPORT_QUALITY_MAX_BYTES,
) -> dict[str, Any]:
    """Inspect the typed section metadata embedded in a workspace report."""
    sections = _extract_section_meta(doc)
    warnings: list[dict[str, Any]] = []

    def warn(code: str, message: str, *, severity: str = "warn", details: dict[str, Any] | None = None) -> None:
        warnings.append({
            "code": code,
            "severity": severity,
            "message": message,
            "details": details or {},
        })

    total_size = len(doc.encode("utf-8"))
    payload_size = len(PLOTLY_RUNTIME_RE.sub("", doc).encode("utf-8"))
    if payload_size > max_bytes:
        warn(
            "oversized_report",
            f"Report payload HTML is {payload_size} bytes; reduce embedded raw HTML/data before publishing.",
            severity="fail",
            details={"bytes": payload_size, "total_bytes": total_size, "max_bytes": max_bytes},
        )

    if stale_skills:
        warn(
            "stale_installed_skills",
            "Installed library skills are stale versus bundled skill-library instructions.",
            severity="fail",
            details={"skills": stale_skills},
        )

    kinds = [clean_text(section.get("kind") or "") for section in sections]
    plain_chart_count = kinds.count("chart")
    chart_like_count = sum(1 for kind in kinds if kind in CHART_SECTION_KINDS)
    story_count = sum(1 for kind in kinds if kind in STORY_SECTION_KINDS and kind != "chart")
    interactive_count = sum(1 for kind in kinds if kind in INTERACTIVE_SECTION_KINDS)
    primary_insight_count = 0
    for section in sections:
        kind = clean_text(section.get("kind") or "")
        payload = section.get("payload") if isinstance(section.get("payload"), dict) else {}
        if kind in {"findings", "insight_grid"} and isinstance(payload.get("items"), list) and payload.get("items"):
            primary_insight_count += 1

    run = 0
    longest_run = 0
    for kind in kinds:
        if kind == "chart":
            run += 1
            longest_run = max(longest_run, run)
        else:
            run = 0
    if longest_run >= 3:
        warn(
            "consecutive_plain_charts",
            "Report contains three or more consecutive plain chart sections; use chart_interpretation or an explorer to keep evidence and meaning together.",
            severity="fail",
            details={"longest_run": longest_run},
        )
    if plain_chart_count >= 4 and interactive_count == 0 and "chart_interpretation" not in kinds:
        warn(
            "chart_dump",
            "Report is dominated by plain charts without interpretation or interactive explorer sections.",
            severity="fail",
            details={"plain_chart_count": plain_chart_count, "interactive_count": interactive_count},
        )
    if len(kinds) >= 4 and story_count == 0:
        warn(
            "missing_insight_sections",
            "Report has multiple sections but no findings, insight grid, narrative band, methodology, evidence, or explorer layer.",
            severity="fail",
            details={"section_count": len(kinds)},
        )
    if len(kinds) >= 4 and primary_insight_count == 0:
        warn(
            "missing_primary_insights",
            "Report has multiple sections but no findings or insight grid carrying completed insight items.",
            severity="fail",
            details={"section_count": len(kinds)},
        )
    if len(kinds) >= 6 and chart_like_count >= 3 and interactive_count == 0:
        warn(
            "missing_interactive_explorer",
            "Analytical report has several charts but no interactive table, selector, filterable chart, or chart-table explorer.",
            severity="fail",
            details={"chart_like_count": chart_like_count},
        )

    for section in sections:
        kind = clean_text(section.get("kind") or "")
        payload = section.get("payload") if isinstance(section.get("payload"), dict) else {}
        if kind in {"table", "interactive_table"} and not clean_text(section.get("caption") or ""):
            warn(
                "missing_table_caption",
                "Table section is missing a caption that explains grain, filters, or interpretation.",
                details={"section_id": section.get("section_id"), "kind": kind},
            )
        if kind in {"findings", "insight_grid", "hypothesis_ledger", "evidence_trace", "evidence_rail"}:
            items = payload.get("items", [])
            if isinstance(items, list) and items and not any(_item_has_evidence_id(item) for item in items if isinstance(item, dict)):
                warn(
                    "missing_evidence_ids",
                    "Insight/evidence section has items but no finding_id, hypothesis_id, or evidence reference in metadata.",
                    details={"section_id": section.get("section_id"), "kind": kind},
                )
        if kind == "chart_interpretation" and payload.get("has_interpretation") and not payload.get("evidence_count"):
            warn(
                "chart_interpretation_missing_evidence",
                "Chart interpretation has a narrative conclusion but no evidence refs.",
                details={"section_id": section.get("section_id")},
            )

    status = "pass"
    if any(w["severity"] == "fail" for w in warnings):
        status = "fail"
    elif warnings:
        status = "warn"

    return {
        "status": status,
        "section_count": len(sections),
        "plain_chart_count": plain_chart_count,
        "interactive_count": interactive_count,
        "story_count": story_count,
        "warnings": warnings,
    }


def _extract_section_meta(doc: str) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    for match in re.finditer(r"<script[^>]*data-dc-section-meta[^>]*>(.*?)</script>", doc, re.IGNORECASE | re.DOTALL):
        try:
            parsed = json.loads(match.group(1))
        except Exception:
            continue
        if isinstance(parsed, dict):
            sections.append(parsed)
    return sections


def _item_has_evidence_id(item: dict[str, Any]) -> bool:
    return any(clean_text(item.get(key) or "") for key in ("finding_id", "hypothesis_id", "evidence", "ref", "cell_id", "artifact_id"))


def _insert_after_body_open(doc: str, html: str) -> str:
    if BODY_OPEN_RE.search(doc):
        return BODY_OPEN_RE.sub(r"\g<1>\n" + html, doc, count=1)
    return html + doc


def typed_report_section(section_type: str, data: dict[str, Any]) -> dict[str, Any]:
    return normalize_section(section_type, data)


def design_report_storyboard(
    *,
    report_goal: str,
    insights: list[dict[str, Any]],
    analyses: list[dict[str, Any]] | None = None,
    audience: str = "",
    title: str = "Analysis Report",
    requirements: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a cohesive report plan from completed insights and analysis assets."""
    requirements = requirements or {}
    analyses = analyses or []
    clean_goal = clean_text(report_goal or title)
    clean_audience = clean_text(audience or requirements.get("audience") or "decision-maker")
    normalized_insights = [item for item in insights if isinstance(item, dict)]
    normalized_analyses = [item for item in analyses if isinstance(item, dict)]
    if not normalized_insights:
        raise ValueError(
            "report_design_report requires at least one completed insight; use report_add_section for low-level drafts."
        )
    section_plan: list[dict[str, Any]] = []

    def add(section_type: str, role: str, rationale: str, data: dict[str, Any]) -> None:
        data = dict(data)
        data.setdefault("semantic_key", role)
        section_plan.append({
            "section_type": section_type,
            "layout_role": role,
            "rationale": rationale,
            "data": data,
        })

    add("header", "opening_context", "Frame the goal and audience before evidence.", {
        "title": title,
        "subtitle": clean_goal,
        "kicker": requirements.get("kicker", "DataClaw report"),
    })

    metrics = _storyboard_metrics(normalized_insights, normalized_analyses, requirements)
    if metrics:
        add("metric_row", "executive_kpis", "Lead with 2-5 numbers that anchor the rest of the report.", {
            "title": requirements.get("metrics_title", "Headline metrics"),
            "metrics": metrics[:5],
        })

    readout = _storyboard_readout(clean_goal, normalized_insights)
    add("narrative_band", "executive_readout", "State the answer before the reader reaches supporting evidence.", {
        "title": requirements.get("readout_title", "Executive readout"),
        "summary": readout,
        "bullets": [clean_text(item.get("title") or item.get("headline") or item.get("finding") or "") for item in normalized_insights[:3] if clean_text(item.get("title") or item.get("headline") or item.get("finding") or "")],
    })

    if normalized_insights:
        add("insight_grid", "primary_insights", "Separate the material conclusions from the notebook execution trail.", {
            "title": requirements.get("insights_title", "Primary insights"),
            "caption": "Findings promoted from completed analysis with evidence, caveats, and next actions where available.",
            "items": [_storyboard_insight_item(item, i) for i, item in enumerate(normalized_insights[:7])],
        })

    for index, analysis in enumerate(normalized_analyses):
        planned = _storyboard_section_from_analysis(analysis, index)
        if planned:
            add(planned["section_type"], planned["layout_role"], planned["rationale"], planned["data"])

    methodology = requirements.get("methodology") or requirements.get("methods") or _collect_named_items(normalized_analyses, "methodology")
    if methodology:
        methods = methodology if isinstance(methodology, list) else [{"title": "Analysis method", "detail": methodology}]
        add("methodology_block", "methodology", "Show grain, denominator, validation, and assumptions after the evidence.", {
            "title": requirements.get("methodology_title", "Methodology"),
            "methods": methods,
            "checks": requirements.get("checks", []),
        })

    hypotheses = requirements.get("hypotheses", [])
    if isinstance(hypotheses, list) and hypotheses:
        add("hypothesis_ledger", "hypothesis_dispositions", "Show how the analysis moved from open questions to dispositions.", {
            "title": requirements.get("hypothesis_title", "Hypothesis ledger"),
            "hypotheses": hypotheses,
        })

    evidence = _storyboard_evidence(normalized_insights, normalized_analyses)
    if evidence:
        add("evidence_trace", "evidence_trace", "Make report claims traceable back to notebook cells, filters, and artifacts.", {
            "title": requirements.get("evidence_title", "Evidence trace"),
            "evidence": evidence,
        })

    interaction_plan = _storyboard_interactions(section_plan)
    storyboard_steps = [
        {"phase": "readout", "purpose": "Answer the report goal in one screen.", "sections": ["opening_context", "executive_kpis", "executive_readout"]},
        {"phase": "insights", "purpose": "Promote only decision-changing findings.", "sections": ["primary_insights"]},
        {"phase": "evidence", "purpose": "Pair visuals, controls, tables, and interpretation.", "sections": [item["layout_role"] for item in section_plan if item["layout_role"].startswith("analysis_")]},
        {"phase": "trust", "purpose": "Close with methodology, hypothesis dispositions, and evidence trace.", "sections": ["methodology", "hypothesis_dispositions", "evidence_trace"]},
    ]

    return {
        "storyboard_schema": 1,
        "title": title,
        "report_goal": clean_goal,
        "audience": clean_audience,
        "designer": {
            "mode": "whole_report",
            "note": "Render from this storyboard after analysis is complete; do not rely on incremental report-cell appends for the final artifact.",
        },
        "storyboard": storyboard_steps,
        "layout_plan": _storyboard_layout(section_plan),
        "interaction_plan": interaction_plan,
        "data_contract": {
            "policy": "Embed aggregate, ranked, or sampled payloads only. Do not fetch live data or embed raw full datasets.",
            "interactive_section_kinds": sorted(INTERACTIVE_SECTION_KINDS),
        },
        "quality_plan": {
            "gate": "run before publish",
            "checks": [
                "stale_installed_skills",
                "consecutive_plain_charts",
                "chart_dump",
                "missing_insight_sections",
                "missing_evidence_ids",
                "missing_table_caption",
                "oversized_report",
                "missing_interactive_explorer",
            ],
        },
        "section_plan": section_plan,
    }


def render_report_from_storyboard(storyboard: dict[str, Any], *, title: str | None = None) -> str:
    """Render all storyboard sections in one pass."""
    section_plan = storyboard.get("section_plan", [])
    if not isinstance(section_plan, list) or not section_plan:
        raise ValueError("storyboard requires non-empty list 'section_plan'")

    html_sections: list[str] = []
    include_plotly = False
    for index, planned in enumerate(section_plan):
        if not isinstance(planned, dict):
            continue
        section_type = clean_text(planned.get("section_type") or planned.get("kind") or "")
        data = planned.get("data") if isinstance(planned.get("data"), dict) else {}
        if not section_type:
            raise ValueError(f"storyboard section {index} is missing section_type")
        data = dict(data)
        data.setdefault("semantic_key", planned.get("layout_role") or f"section-{index}")
        typed = typed_report_section(section_type, data)
        include_plotly = include_plotly or typed.get("kind") in CHART_SECTION_KINDS
        html_sections.append(render_report_section(section_type, data, typed))

    return report_shell(
        title=title or clean_text(storyboard.get("title") or "Analysis Report"),
        first_section="\n".join(html_sections),
        include_plotly=include_plotly,
    )


def _storyboard_metrics(
    insights: list[dict[str, Any]],
    analyses: list[dict[str, Any]],
    requirements: dict[str, Any],
) -> list[dict[str, Any]]:
    metrics: list[dict[str, Any]] = []
    sources: list[Any] = [requirements.get("metrics")]
    sources.extend(item.get("metrics") for item in insights)
    sources.extend(item.get("metrics") for item in analyses)
    for source in sources:
        if isinstance(source, dict):
            for key, value in source.items():
                metrics.append({"label": clean_text(key).replace("_", " ").title(), "value": value})
        elif isinstance(source, list):
            for metric in source:
                if isinstance(metric, dict):
                    label = metric.get("label") or metric.get("name") or metric.get("key")
                    if label and metric.get("value") not in (None, ""):
                        metrics.append(metric)
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for metric in metrics:
        key = clean_text(metric.get("label") or metric.get("name") or metric.get("key") or "")
        if key and key not in seen:
            seen.add(key)
            unique.append(metric)
    return unique


def _storyboard_readout(goal: str, insights: list[dict[str, Any]]) -> str:
    if not insights:
        return goal
    lead = _item_title(insights[0], "Primary finding")
    detail = _item_detail(insights[0])
    if detail:
        return f"{goal}\n\nPrimary readout: {lead}. {detail}"
    return f"{goal}\n\nPrimary readout: {lead}."


def _storyboard_insight_item(item: dict[str, Any], index: int) -> dict[str, Any]:
    copied = dict(item)
    copied.setdefault("title", _item_title(item, f"Insight {index + 1}"))
    if _item_detail(item):
        copied.setdefault("detail", _item_detail(item))
    copied.setdefault("status", item.get("status") or item.get("severity") or item.get("confidence") or "reviewed")
    return copied


def _collect_named_items(items: list[dict[str, Any]], key: str) -> list[Any]:
    out: list[Any] = []
    for item in items:
        value = item.get(key)
        if isinstance(value, list):
            out.extend(value)
        elif value:
            out.append(value)
    return out


def _storyboard_section_from_analysis(analysis: dict[str, Any], index: int) -> dict[str, Any] | None:
    explicit = clean_text(analysis.get("section_type") or analysis.get("kind") or "")
    data = analysis.get("data") if isinstance(analysis.get("data"), dict) else dict(analysis)
    data.setdefault("title", analysis.get("title") or f"Analysis {index + 1}")
    data.setdefault("caption", analysis.get("caption") or analysis.get("summary") or "")

    if explicit in STORY_SECTION_KINDS or explicit in CHART_SECTION_KINDS or explicit in {"table", "callout", "text"}:
        return {
            "section_type": explicit,
            "layout_role": f"analysis_{index + 1}_{explicit}",
            "rationale": "Use the explicit section type chosen by the report designer.",
            "data": data,
        }

    records = data.get("records", data.get("rows"))
    chart = data.get("chart")
    if isinstance(records, list) and isinstance(chart, dict):
        filters = data.get("filters", data.get("controls", []))
        section_type = "chart_table_explorer" if data.get("columns") or filters or len(records) > 6 else "filterable_chart"
        data.setdefault("filters", filters)
        data.setdefault("columns", data.get("columns") or _columns_from_records(records)[:8])
        return {
            "section_type": section_type,
            "layout_role": f"analysis_{index + 1}_{section_type}",
            "rationale": "Pair an aggregate chart with the controls/table needed to inspect the evidence.",
            "data": data,
        }

    if isinstance(data.get("rows"), list) and isinstance(data.get("columns"), list):
        return {
            "section_type": "interactive_table",
            "layout_role": f"analysis_{index + 1}_interactive_table",
            "rationale": "Use an interactive table for lookup, sorting, and exact values.",
            "data": data,
        }

    if isinstance(data.get("figure"), dict) or data.get("figure_json"):
        return {
            "section_type": "chart_interpretation",
            "layout_role": f"analysis_{index + 1}_chart_interpretation",
            "rationale": "Attach interpretation, caveats, and evidence beside the chart.",
            "data": data,
        }

    if isinstance(data.get("items"), list) or isinstance(data.get("entities"), list):
        return {
            "section_type": "entity_card_grid",
            "layout_role": f"analysis_{index + 1}_entity_cards",
            "rationale": "Summarize entities/archetypes as cards instead of burying them in prose.",
            "data": data,
        }

    return None


def _columns_from_records(records: list[Any]) -> list[str]:
    columns: list[str] = []
    seen: set[str] = set()
    for row in records:
        if not isinstance(row, dict):
            continue
        for key in row:
            clean_key = clean_text(key)
            if clean_key and clean_key not in seen:
                seen.add(clean_key)
                columns.append(clean_key)
    return columns


def _storyboard_evidence(insights: list[dict[str, Any]], analyses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for source in [*insights, *analyses]:
        for key in ("evidence", "evidence_refs"):
            value = source.get(key)
            for item in _as_list(value):
                if isinstance(item, dict):
                    evidence.append(dict(item))
                elif clean_text(item):
                    evidence.append({"kind": "evidence_ref", "ref": clean_text(item), "summary": _item_title(source, "Evidence")})
        if source.get("finding_id") or source.get("hypothesis_id"):
            evidence.append({
                "kind": "finding",
                "finding_id": source.get("finding_id", ""),
                "hypothesis_id": source.get("hypothesis_id", ""),
                "summary": _item_title(source, "Finding"),
            })
    return evidence[:40]


def _storyboard_interactions(section_plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    interactions: list[dict[str, Any]] = []
    for item in section_plan:
        section_type = item.get("section_type")
        data = item.get("data") if isinstance(item.get("data"), dict) else {}
        if section_type in INTERACTIVE_SECTION_KINDS:
            interactions.append({
                "section": item.get("layout_role"),
                "section_type": section_type,
                "controls": data.get("filters", data.get("controls", [])),
                "behavior": "Client-side filtering over embedded aggregate JSON; no live fetches.",
            })
    return interactions


def _storyboard_layout(section_plan: list[dict[str, Any]]) -> list[dict[str, str]]:
    layout: list[dict[str, str]] = []
    for item in section_plan:
        section_type = clean_text(item.get("section_type") or "")
        role = clean_text(item.get("layout_role") or section_type)
        if section_type in {"chart_interpretation", "chart_table_explorer", "filterable_chart"}:
            pattern = "chart plus interpretation rail"
        elif section_type in {"interactive_table", "selector_panel"}:
            pattern = "controls adjacent to evidence"
        elif section_type == "entity_card_grid":
            pattern = "card grid"
        elif section_type in {"methodology_block", "evidence_trace", "hypothesis_ledger"}:
            pattern = "trust and provenance block"
        else:
            pattern = "narrative band"
        layout.append({"section": role, "section_type": section_type, "layout_pattern": pattern})
    return layout


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

    if st == "chart_interpretation":
        chart_id = f"chart-{uuid.uuid4().hex[:10]}"
        figure = data.get("figure")
        if not figure and data.get("figure_json"):
            figure = json.loads(str(data["figure_json"]))
        if not isinstance(figure, dict):
            raise ValueError("chart_interpretation section requires 'figure' dict or 'figure_json'")
        figure_json = json.dumps(figure, default=str).replace("</", "<\\/")
        title = _esc(data.get("title", figure.get("layout", {}).get("title", {}).get("text", "Chart") if isinstance(figure.get("layout"), dict) else "Chart"))
        caption = _esc(data.get("caption", ""))
        interpretation = clean_text(data.get("interpretation") or data.get("insight") or data.get("summary") or "")
        caveat = clean_text(data.get("caveat") or data.get("limitation") or "")
        next_action = clean_text(data.get("next_action") or data.get("action") or "")
        evidence = data.get("evidence", data.get("evidence_refs", []))
        rail = _render_evidence_rail(evidence, title="Evidence") if isinstance(evidence, list) and evidence else ""
        return f"""    <section class="r-section" {attrs}>
      <h2>{title}</h2>
      {_section_context({k: v for k, v in data.items() if k not in {"caption", "summary", "interpretation", "insight", "evidence", "evidence_refs"}})}
      <div class="r-chart-story-grid">
        <div class="r-chart-main">
          <div id="{chart_id}" class="r-chart-target"></div>
          {f'<p class="r-caption">{caption}</p>' if caption else ''}
        </div>
        <aside class="r-interpretation-panel">
          <h3>Interpretation</h3>
          {f'<p>{_esc(interpretation)}</p>' if interpretation else ''}
          {f'<p class="r-finding-meta"><strong>Caveat:</strong> {_esc(caveat)}</p>' if caveat else ''}
          {f'<p class="r-finding-meta"><strong>Next:</strong> {_esc(next_action)}</p>' if next_action else ''}
          {rail}
        </aside>
      </div>
      <script>
        (function() {{
          var fig = {figure_json};
          Plotly.newPlot("{chart_id}", fig.data || [], fig.layout || {{}}, {{responsive: true, displaylogo: false}});
        }})();
      </script>
      {meta}
    </section>"""

    if st == "filterable_chart":
        shell_id = f"interactive-{uuid.uuid4().hex[:10]}"
        title = _esc(data.get("title", "Filterable chart"))
        records = data.get("records", data.get("rows", []))
        if not isinstance(records, list):
            raise ValueError("filterable_chart section requires list 'records' or 'rows'")
        chart = data.get("chart", {})
        if not isinstance(chart, dict):
            raise ValueError("filterable_chart section requires dict 'chart'")
        config = _json_for_script({
            "records": records,
            "chart": chart,
            "filters": data.get("filters", data.get("controls", [])),
        })
        interpretation = clean_text(data.get("interpretation") or data.get("insight") or data.get("summary") or "")
        caveat = clean_text(data.get("caveat") or data.get("limitation") or "")
        return f"""    <section class="r-section" {attrs}>
      <h2>{title}</h2>
      {_section_context({k: v for k, v in data.items() if k not in {"records", "rows", "chart", "filters", "controls", "summary", "interpretation", "insight"}})}
      <div id="{shell_id}" class="r-interactive-shell">
        <div class="r-control-bar" data-dc-control-bar></div>
        <div class="r-chart-story-grid">
          <div class="r-chart-main"><div class="r-chart-target" data-dc-chart-target></div></div>
          <aside class="r-interpretation-panel">
            <h3>Interpretation</h3>
            {f'<p>{_esc(interpretation)}</p>' if interpretation else '<p class="r-finding-meta">Use the controls to compare the embedded aggregate slices.</p>'}
            {f'<p class="r-finding-meta"><strong>Caveat:</strong> {_esc(caveat)}</p>' if caveat else ''}
          </aside>
        </div>
      </div>
      <script>(window.__DataClawReportQueue=window.__DataClawReportQueue||[]).push({{fn:"initFilterableChart",id:"{shell_id}",config:{config}}});</script>
      {meta}
    </section>"""

    if st == "interactive_table":
        shell_id = f"interactive-{uuid.uuid4().hex[:10]}"
        rows = data.get("rows", [])
        if not isinstance(rows, list):
            raise ValueError("interactive_table section requires list 'rows'")
        config = _json_for_script({
            "rows": rows,
            "columns": data.get("columns", []),
            "filters": data.get("filters", data.get("controls", [])),
            "page_size": data.get("page_size", data.get("pageSize", 20)),
            "search": data.get("search", data.get("enable_search", True)),
        })
        return f"""    <section class="r-section" {attrs}>
      <h2>{_esc(data.get("title", "Interactive table"))}</h2>
      {_section_context(data)}
      <div id="{shell_id}" class="r-interactive-shell">
        <div class="r-control-bar" data-dc-control-bar></div>
        <div class="r-table-tools" data-dc-table-tools></div>
        <div class="r-interactive-table-wrap" data-dc-interactive-table></div>
        <div class="r-pagination" data-dc-pagination></div>
      </div>
      <script>(window.__DataClawReportQueue=window.__DataClawReportQueue||[]).push({{fn:"initInteractiveTable",id:"{shell_id}",config:{config}}});</script>
      {meta}
    </section>"""

    if st == "chart_table_explorer":
        shell_id = f"interactive-{uuid.uuid4().hex[:10]}"
        records = data.get("records", data.get("rows", []))
        if not isinstance(records, list):
            raise ValueError("chart_table_explorer section requires list 'records' or 'rows'")
        chart = data.get("chart", {})
        if not isinstance(chart, dict):
            raise ValueError("chart_table_explorer section requires dict 'chart'")
        config = _json_for_script({
            "records": records,
            "chart": chart,
            "columns": data.get("columns", []),
            "filters": data.get("filters", data.get("controls", [])),
            "page_size": data.get("page_size", data.get("pageSize", 12)),
            "search": data.get("search", data.get("enable_search", True)),
        })
        interpretation = clean_text(data.get("interpretation") or data.get("insight") or data.get("summary") or "")
        evidence = data.get("evidence", data.get("evidence_refs", []))
        rail = _render_evidence_rail(evidence, title="Evidence") if isinstance(evidence, list) and evidence else ""
        return f"""    <section class="r-section" {attrs}>
      <h2>{_esc(data.get("title", "Chart and table explorer"))}</h2>
      {_section_context({k: v for k, v in data.items() if k not in {"records", "rows", "chart", "columns", "filters", "controls", "summary", "interpretation", "insight", "evidence", "evidence_refs"}})}
      <div id="{shell_id}" class="r-interactive-shell">
        <div class="r-control-bar" data-dc-control-bar></div>
        <div class="r-explorer-grid">
          <div>
            <div class="r-chart-target" data-dc-chart-target></div>
            <div class="r-table-tools" data-dc-table-tools></div>
            <div class="r-interactive-table-wrap" data-dc-interactive-table></div>
            <div class="r-pagination" data-dc-pagination></div>
          </div>
          <aside class="r-interpretation-panel">
            <h3>Interpretation</h3>
            {f'<p>{_esc(interpretation)}</p>' if interpretation else '<p class="r-finding-meta">Select a slice to inspect the evidence behind the chart.</p>'}
            {rail}
          </aside>
        </div>
      </div>
      <script>(window.__DataClawReportQueue=window.__DataClawReportQueue||[]).push({{fn:"initChartTableExplorer",id:"{shell_id}",config:{config}}});</script>
      {meta}
    </section>"""

    if st == "selector_panel":
        shell_id = f"interactive-{uuid.uuid4().hex[:10]}"
        items = data.get("items", data.get("options", []))
        if items is None:
            items = []
        if not isinstance(items, list):
            raise ValueError("selector_panel section requires list 'items' or 'options'")
        config = _json_for_script({
            "items": items,
            "controls": data.get("controls", data.get("filters", [])),
        })
        cards = "".join(_render_entity_card(item, index, selector=True) for index, item in enumerate(items))
        return f"""    <section class="r-section" {attrs}>
      <h2>{_esc(data.get("title", "Selector panel"))}</h2>
      {_section_context(data)}
      <div id="{shell_id}" class="r-selector-panel">
        <div class="r-control-bar" data-dc-control-bar></div>
        <div class="r-entity-grid">{cards}</div>
      </div>
      <script>(window.__DataClawReportQueue=window.__DataClawReportQueue||[]).push({{fn:"initSelectorPanel",id:"{shell_id}",config:{config}}});</script>
      {meta}
    </section>"""

    if st == "entity_card_grid":
        items = data.get("items", data.get("entities", []))
        if not isinstance(items, list):
            raise ValueError("entity_card_grid section requires list 'items' or 'entities'")
        cards = "".join(_render_entity_card(item, index) for index, item in enumerate(items))
        return f"""    <section class="r-section" {attrs}>
      <h2>{_esc(data.get("title", "Entity cards"))}</h2>
      {_section_context(data)}
      <div class="r-entity-grid">{cards}</div>
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

    if st == "narrative_band":
        body = _paragraphs(data.get("body", data.get("text", data.get("summary", ""))))
        return f"""    <section class="r-section" {attrs}>
      <div class="r-narrative-band">
        <h2>{_esc(data.get("title", "Narrative"))}</h2>
        {_section_context(data)}
        {body}
      </div>
      {meta}
    </section>"""

    if st == "methodology_block":
        methods = data.get("methods", data.get("steps", data.get("items", [])))
        if methods is None:
            methods = []
        if not isinstance(methods, list):
            raise ValueError("methodology_block section requires list 'methods', 'steps', or 'items'")
        cards = "".join(_render_method_card(method, i) for i, method in enumerate(methods))
        body = _paragraphs(data.get("body", data.get("summary", "")))
        checks = data.get("checks", [])
        check_rows = ""
        if checks:
            if not isinstance(checks, list):
                raise ValueError("methodology_block section 'checks' must be a list")
            check_rows = f'<div class="r-checks">{"".join(_render_check_item(check) for check in checks)}</div>'
        return f"""    <section class="r-section" {attrs}>
      <h2>{_esc(data.get("title", "Methodology"))}</h2>
      {_section_context(data)}
      {body}
      {f'<div class="r-methodology-grid">{cards}</div>' if cards else ''}
      {check_rows}
      {meta}
    </section>"""

    if st == "evidence_rail":
        items = data.get("evidence", data.get("items", []))
        if not isinstance(items, list):
            raise ValueError("evidence_rail section requires list 'evidence' or 'items'")
        return f"""    <section class="r-section" {attrs}>
      <div class="r-evidence-layout">
        <div>
          <h2>{_esc(data.get("title", "Evidence"))}</h2>
          {_section_context(data)}
          {_paragraphs(data.get("body", data.get("summary", "")))}
        </div>
        {_render_evidence_rail(items, title=data.get("rail_title", "Evidence"))}
      </div>
      {meta}
    </section>"""

    if st == "ledger_timeline":
        events = data.get("events", data.get("timeline", data.get("items", [])))
        if not isinstance(events, list):
            raise ValueError("ledger_timeline section requires list 'events', 'timeline', or 'items'")
        rows = "".join(_render_timeline_item(item, i) for i, item in enumerate(events))
        return f"""    <section class="r-section" {attrs}>
      <h2>{_esc(data.get("title", "Timeline"))}</h2>
      {_section_context(data)}
      <div class="r-timeline">{rows}</div>
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


def _json_for_script(value: Any) -> str:
    return json.dumps(value, default=str).replace("</", "<\\/")


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


def _selector_key(item: Any, index: int) -> str:
    if isinstance(item, dict):
        return clean_text(item.get("id") or item.get("key") or item.get("name") or index)
    return clean_text(index)


def _render_entity_card(item: Any, index: int, *, selector: bool = False) -> str:
    selector_attr = f' data-dc-selector-card="{_esc(_selector_key(item, index))}"' if selector else ""
    if not isinstance(item, dict):
        return f'<article class="r-entity-card"{selector_attr}><h3>{_esc(item)}</h3></article>'
    title = _item_title(item, f"Entity {index + 1}")
    detail = _item_detail(item)
    status = item.get("status") or item.get("state") or item.get("segment") or item.get("archetype")
    chips = "".join([
        _chip(status, _status_class(status)),
        _chip(item.get("confidence"), "neutral"),
        _chip(item.get("team"), "neutral"),
        _chip(item.get("position"), "neutral"),
    ])
    metrics = item.get("metrics")
    metric_rows: list[tuple[str, Any]] = []
    if isinstance(metrics, dict):
        metric_rows = [(clean_text(key).replace("_", " ").title(), value) for key, value in metrics.items()]
    elif isinstance(metrics, list):
        for metric in metrics:
            if isinstance(metric, dict):
                label = clean_text(metric.get("label") or metric.get("name") or metric.get("key"))
                metric_rows.append((label, metric.get("value", "")))
    else:
        for key in ("score", "rank", "value", "projection", "similarity"):
            if item.get(key) not in (None, ""):
                metric_rows.append((key.replace("_", " ").title(), item.get(key)))
    rendered_metrics = "".join(
        f'<div class="r-entity-metric"><span>{_esc(label)}</span><strong>{_esc(value)}</strong></div>'
        for label, value in metric_rows
        if label or value not in (None, "")
    )
    bullets = _render_bullet_list(item.get("bullets") or item.get("traits") or item.get("points"))
    return f"""<article class="r-entity-card"{selector_attr}>
      <div class="r-meta-row">{chips}</div>
      <h3>{_esc(title)}</h3>
      {f'<p>{_esc(detail)}</p>' if detail else ''}
      {bullets}
      {f'<div class="r-entity-metrics">{rendered_metrics}</div>' if rendered_metrics else ''}
    </article>"""


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


def _render_method_card(method: Any, index: int) -> str:
    if not isinstance(method, dict):
        return f'<article class="r-method-card"><h3>Step {index + 1}</h3><p>{_esc(method)}</p></article>'
    title = _item_title(method, f"Step {index + 1}")
    detail = _item_detail(method)
    evidence = method.get("evidence") or method.get("evidence_ref")
    return f"""<article class="r-method-card">
      <div class="r-meta-row">{_chip(method.get("status"), _status_class(method.get("status")))}{_chip(method.get("owner"), "neutral")}</div>
      <h3>{_esc(title)}</h3>
      {f'<p>{_esc(detail)}</p>' if detail else ''}
      {f'<p class="r-evidence-ref">{_esc(evidence)}</p>' if evidence else ''}
    </article>"""


def _render_evidence_rail(items: list[Any], *, title: Any = "Evidence") -> str:
    rows = "".join(_render_evidence_item(item) for item in items)
    return f"""<aside class="r-evidence-rail compact">
      <h3>{_esc(title)}</h3>
      {rows}
    </aside>"""


def _render_timeline_item(item: Any, index: int) -> str:
    if not isinstance(item, dict):
        return f'<article class="r-timeline-item"><div class="r-timeline-top"><strong>{index + 1}</strong></div><p>{_esc(item)}</p></article>'
    status = item.get("status") or item.get("state") or item.get("disposition")
    title = _item_title(item, f"Event {index + 1}")
    detail = _item_detail(item)
    time = item.get("time") or item.get("timestamp") or item.get("phase") or item.get("loop_index")
    evidence = item.get("evidence") or item.get("evidence_ref") or item.get("finding_id") or item.get("hypothesis_id")
    return f"""<article class="r-timeline-item">
      <div class="r-timeline-top">
        <strong>{_esc(title)}</strong>
        <span>{_chip(status, _status_class(status))}</span>
      </div>
      {f'<div class="r-timeline-time">{_esc(time)}</div>' if time else ''}
      {f'<p class="r-finding-meta">{_esc(detail)}</p>' if detail else ''}
      {f'<p class="r-evidence-ref">{_esc(evidence)}</p>' if evidence else ''}
    </article>"""


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
