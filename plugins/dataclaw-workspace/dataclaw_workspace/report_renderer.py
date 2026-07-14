"""Report renderer for DataClaw workspace reports."""

from __future__ import annotations

import copy
import hashlib
import html as html_lib
import json
import re
import uuid
from html.parser import HTMLParser
from typing import Any

from dataclaw_artifacts.sections import (
    TABLE_PREVIEW_MAX_BYTES,
    clean_text,
    normalize_section,
    section_attrs as artifact_section_attrs,
    section_meta_script as artifact_section_meta_script,
)
from dataclaw_artifacts.wrapper import plotly_runtime_js

from dataclaw_workspace.report_rubric import (
    live_criterion_ids,
    rubric_criteria,
    rubric_thresholds,
    rubric_version,
)

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
    "build_evidence_registry",
    "critique_report_storyboard",
    "design_report_storyboard",
    "ensure_plotly_runtime",
    "ensure_report_shell_context",
    "plotly_script_tag",
    "normalize_raw_html_report",
    "render_report_section",
    "render_report_from_storyboard",
    "report_shell",
    "report_shell_css",
    "report_shell_script",
    "review_storyboard_design",
    "review_storyboard_analysis",
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
# The rubric is the single source of truth for gate thresholds; this constant is
# kept as the public name for the payload cap (docs reference it by name).
REPORT_QUALITY_MAX_BYTES = rubric_thresholds()["max_payload_bytes"]


def report_shell(
    *,
    title: str,
    first_section: str,
    include_plotly: bool = False,
    evidence_registry: dict[str, Any] | None = None,
) -> str:
    safe_title = html_lib.escape(title)
    plotly_script = plotly_script_tag() if include_plotly else ""
    shell_css = report_shell_css()
    shell_script = report_shell_script()
    registry_script = _evidence_registry_script(evidence_registry)
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
    {registry_script}
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
  --dc-cat-1: #2563eb;
  --dc-cat-2: #0f766e;
  --dc-cat-3: #c2410c;
  --dc-cat-4: #7c3aed;
  --dc-cat-5: #be185d;
  --dc-cat-6: #4d7c0f;
  --dc-cat-7: #0369a1;
  --dc-cat-8: #a16207;
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
  --dc-cat-1: #7aa7ff;
  --dc-cat-2: #5eead4;
  --dc-cat-3: #fdba74;
  --dc-cat-4: #c4b5fd;
  --dc-cat-5: #f9a8d4;
  --dc-cat-6: #bef264;
  --dc-cat-7: #7dd3fc;
  --dc-cat-8: #fde047;
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
.r-story-nav-head { display: none; }
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
.r-story-nav a .r-nav-num { display: none; }
@media (min-width: 1240px) {
  .r-story-nav {
    position: fixed;
    inset: 0 auto 0 0;
    width: 224px;
    flex-direction: column;
    align-items: stretch;
    gap: 2px;
    overflow-y: auto;
    overflow-x: hidden;
    padding: 26px 14px 26px 18px;
    border-bottom: 0;
    border-right: 1px solid var(--line);
    background: color-mix(in srgb, var(--dc-surface) 65%, var(--dc-bg));
    backdrop-filter: none;
  }
  .r-story-nav-head {
    display: block;
    font-size: 11px;
    font-weight: 760;
    text-transform: uppercase;
    letter-spacing: .08em;
    color: var(--muted);
    padding: 0 10px 10px;
  }
  .r-story-nav a {
    max-width: none;
    display: flex;
    align-items: baseline;
    gap: 8px;
    border: 0;
    border-left: 2px solid transparent;
    border-radius: 8px;
    background: transparent;
    padding: 7px 10px;
    font-size: 12.5px;
    line-height: 1.3;
    white-space: normal;
  }
  .r-story-nav a .r-nav-num {
    display: inline;
    flex: 0 0 auto;
    font-size: 10px;
    font-weight: 760;
    color: color-mix(in srgb, var(--dc-accent) 60%, var(--muted));
    font-variant-numeric: tabular-nums;
  }
  .r-story-nav a.active, .r-story-nav a:hover {
    background: var(--accent-soft);
    border-left-color: var(--dc-accent);
    color: var(--ink);
    transform: none;
  }
  body.has-rail .r-page { margin: 0 auto 0 max(224px, calc((100vw - 1100px) / 2)); }
}
.r-page { max-width: 1100px; margin: 0 auto; padding: 30px 22px 48px; }
.sr-only, .r-section h2.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }
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
.r-hero-subtitle { margin-bottom: 8px !important; }
.r-hero-abstract { font-size: 17px !important; line-height: 1.5; }
.r-hero-scope { display: block; margin-bottom: 7px; color: inherit; font-size: 13px; font-weight: 700; letter-spacing: .01em; }
.r-hero.is-editorial-dark {
  background: radial-gradient(circle at 87% 18%, rgba(45, 212, 191, .26), transparent 32%), linear-gradient(135deg, #0f172a, #312e81 58%, #0f766e);
  color: #f8fafc;
  border-color: transparent;
  padding: 50px 42px 62px;
}
.r-hero.is-editorial-dark .r-kicker { color: #99f6e4; }
.r-hero.is-editorial-dark h1 { color: #fff; }
.r-hero.is-editorial-dark .r-hero-subtitle, .r-hero.is-editorial-dark .r-hero-abstract { color: rgba(241, 245, 249, .88); }
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
.r-data-note { margin: 0; padding: 9px 11px; border-left: 3px solid var(--dc-accent-3); border-radius: 0 10px 10px 0; background: color-mix(in srgb, var(--dc-accent-3) 7%, var(--dc-surface-muted)); color: var(--muted); font-size: 12px; }
.r-adjacent-insights { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 10px; margin-top: 2px; }
.r-adjacent-insights .r-insight-card { padding: 12px; box-shadow: none; }
.r-adjacent-insights .r-insight-card h3 { font-size: 14px; }
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
.r-hero + .r-section.is-floating-kpis {
  position: relative;
  z-index: 2;
  margin: -42px 22px 20px;
  padding: 0;
}
.r-hero + .r-section.is-floating-kpis .r-metrics { padding: 0; }
.r-hero + .r-section.is-floating-kpis .r-metric {
  background: linear-gradient(180deg, rgba(255,255,255,.98), var(--dc-surface-raised));
  box-shadow: 0 12px 28px rgba(15, 23, 42, .14);
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
.r-control-bar:empty { display: none; }
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
.r-control select:focus-visible, .r-table-tools input:focus-visible, .r-pagination button:focus-visible, .r-sort-button:focus-visible, .r-control-reset:focus-visible, .r-entity-card[data-dc-selector-card]:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--dc-accent) 72%, transparent);
  outline-offset: 2px;
}
.r-control-actions { display: flex; gap: 8px; align-items: center; align-self: end; margin-left: auto; flex-wrap: wrap; }
.r-control-summary { color: var(--muted); font-size: 12px; }
.r-control-reset {
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 7px 10px;
  background: var(--dc-surface);
  color: var(--ink);
  cursor: pointer;
  font: inherit;
}
.r-empty-state {
  border: 1px dashed var(--line);
  border-radius: 12px;
  padding: 18px;
  color: var(--muted);
  background: color-mix(in srgb, var(--dc-surface-muted) 80%, transparent);
  text-align: center;
}
.r-explorer-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(280px, 380px); gap: 16px; align-items: start; }
.r-diagnostic-pair { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; margin: 18px 0; }
.r-diagnostic-pair .r-section { height: 100%; margin: 0; }
.r-table-tools { display: flex; justify-content: space-between; gap: 10px; align-items: center; margin-bottom: 8px; flex-wrap: wrap; }
.r-table-tools input { max-width: 260px; }
.r-interactive-table-wrap { width: 100%; overflow: auto; border: 1px solid var(--line); border-radius: 12px; background: var(--dc-surface); }
.r-interactive-table th { cursor: pointer; user-select: none; white-space: nowrap; }
.r-sort-button { all: unset; display: inline-flex; align-items: center; gap: 5px; cursor: pointer; color: inherit; }
.r-sort-indicator { color: var(--accent); font-size: 10px; min-width: 1em; }
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
.r-entity-card[data-dc-selector-card] { cursor: pointer; transition: border-color .16s ease, box-shadow .16s ease, transform .16s ease; }
.r-entity-card[data-dc-selector-card]:hover { transform: translateY(-1px); border-color: color-mix(in srgb, var(--dc-accent) 34%, var(--line)); }
.r-entity-card.is-selected { border-color: color-mix(in srgb, var(--dc-accent) 65%, var(--line)); box-shadow: 0 0 0 3px color-mix(in srgb, var(--dc-accent) 14%, transparent); }
.r-entity-card h3 { margin: 7px 0 6px; color: var(--ink); }
.r-entity-metrics { display: grid; gap: 6px; margin-top: 10px; }
.r-entity-metric { display: flex; justify-content: space-between; gap: 10px; border-top: 1px solid var(--line); padding-top: 6px; color: var(--muted); font-size: 12px; }
.r-entity-metric strong { color: var(--ink); text-align: right; }
.r-selection-detail { border: 1px solid var(--line); border-radius: 12px; padding: 14px; background: var(--dc-surface-raised); }
.r-selection-detail h3 { margin: 0 0 6px; color: var(--ink); }
.r-caption { color: var(--muted); font-size: 12px; margin: 8px 2px 0; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { padding: 9px 10px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }
th { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0; }
th.num, td.num { text-align: right; font-variant-numeric: tabular-nums; }
.r-section-kicker {
  font-size: 11px;
  font-weight: 760;
  text-transform: uppercase;
  letter-spacing: .08em;
  color: var(--accent);
  margin: 0 0 6px;
}
.r-section.is-hero {
  padding: 30px 28px;
  border-color: color-mix(in srgb, var(--dc-accent) 30%, var(--line));
  background: linear-gradient(160deg, color-mix(in srgb, var(--dc-accent) 7%, var(--dc-surface)), var(--dc-surface) 55%);
  box-shadow: var(--dc-shadow);
}
.r-section.is-hero h2 { font-size: 28px; }
.r-section.is-hero .r-chart-target { min-height: 470px; }
.r-section.is-narrow { max-width: 860px; margin-left: auto; margin-right: auto; }
.r-section.is-report-epilogue {
  max-width: 900px;
  margin: 30px auto 0;
  border-left-color: color-mix(in srgb, var(--dc-accent-3) 65%, var(--line));
  box-shadow: none;
  background: color-mix(in srgb, var(--dc-accent-3) 6%, var(--dc-surface));
}
.r-conclusion {
  margin: 10px 2px 0;
  padding-left: 12px;
  border-left: 3px solid var(--dc-accent);
  color: var(--ink);
  font-size: 14px;
  font-weight: 600;
}
.r-evidence-chips { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; margin-top: 8px; }
.r-evidence-chips-label { font-size: 10px; font-weight: 760; text-transform: uppercase; letter-spacing: .06em; color: var(--muted); }
.r-evidence-chip { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 10.5px; font-weight: 560; text-decoration: none; }
a.r-evidence-chip:hover { border-color: color-mix(in srgb, var(--dc-accent) 45%, var(--line)); color: var(--accent); }
.r-supports-link {
  display: inline-block;
  margin-top: 10px;
  font-size: 12px;
  font-weight: 660;
  color: var(--accent);
  text-decoration: none;
}
.r-supports-link:hover { text-decoration: underline; }
.r-insight-card.good { border-top: 3px solid var(--dc-good); }
.r-insight-card.warn { border-top: 3px solid var(--dc-warn); }
.r-insight-card.danger { border-top: 3px solid var(--dc-danger); }
.r-insight-card.neutral { border-top: 3px solid color-mix(in srgb, var(--dc-accent) 55%, var(--line)); }
.r-entity-card { border-top: 3px solid var(--card-accent, transparent); position: relative; }
.r-entity-count {
  position: absolute;
  top: 12px;
  right: 12px;
  font-size: 11px;
  font-weight: 760;
  color: var(--muted);
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 2px 8px;
  background: var(--dc-surface-muted);
}
.r-entity-metric { position: relative; }
.r-metric-bar { flex: 1 1 auto; align-self: center; height: 5px; margin: 0 10px; border-radius: 999px; background: color-mix(in srgb, var(--line) 55%, transparent); overflow: hidden; }
.r-metric-bar span { display: block; height: 100%; border-radius: 999px; background: var(--card-accent, var(--dc-accent)); }
.r-spark { display: block; margin-top: 8px; width: 100%; height: 34px; }
.r-spark polyline { fill: none; stroke: var(--dc-accent); stroke-width: 2; }
.r-spark polygon { fill: color-mix(in srgb, var(--dc-accent) 12%, transparent); stroke: none; }
@media (prefers-reduced-motion: reduce) {
  html { scroll-behavior: auto; }
  .r-section, .r-story-nav a, .r-progress span { transition: none; }
}
@media (max-width: 720px) {
  .r-story-nav { padding: 8px 12px; }
  .r-page { padding: 16px 12px 28px; }
  .r-hero { padding: 24px; border-radius: 14px; }
  .r-hero h1 { font-size: 26px; }
  .r-grid.cols-2, .r-chart-story-grid, .r-evidence-layout, .r-explorer-grid, .r-diagnostic-pair { grid-template-columns: 1fr; }
  .r-hero.is-editorial-dark { padding: 34px 24px 48px; }
  .r-hero + .r-section.is-floating-kpis { margin: -28px 10px 18px; }
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
  function slugId(value, prefix) {
    var base = text(value).trim().replace(/[^A-Za-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '');
    return (prefix || 'dc') + '-' + (base || Math.random().toString(36).slice(2, 8));
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
  function normalizeTableRows(rows, columns) {
    if (!Array.isArray(rows)) return [];
    var cols = columnsFrom([], columns);
    if (!cols.length) return rows;
    return rows.map(function(row) {
      if (!Array.isArray(row)) return row;
      var normalized = {};
      cols.forEach(function(col, index) { normalized[col.key] = row[index]; });
      return normalized;
    });
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
    if (!container) return function() { return {}; };
    if (!normalized.length) return function() { return {}; };
    container.innerHTML = '';
    var selects = [];
    normalized.forEach(function(filter) {
      var wrap = document.createElement('div');
      wrap.className = 'r-control';
      var label = document.createElement('label');
      var selectId = slugId(filter.key + '-' + Math.random().toString(36).slice(2, 8), 'filter');
      label.setAttribute('for', selectId);
      label.textContent = filter.label;
      var select = document.createElement('select');
      select.id = selectId;
      select.name = filter.key;
      select.setAttribute('aria-label', filter.label);
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
      select.addEventListener('change', function() {
        updateSummary();
        if (typeof onChange === 'function') onChange();
      });
      selects.push(select);
      wrap.appendChild(label);
      wrap.appendChild(select);
      container.appendChild(wrap);
    });
    var actions = document.createElement('div');
    actions.className = 'r-control-actions';
    var summary = document.createElement('span');
    summary.className = 'r-control-summary';
    summary.setAttribute('aria-live', 'polite');
    var reset = document.createElement('button');
    reset.type = 'button';
    reset.className = 'r-control-reset';
    reset.textContent = 'Reset filters';
    reset.addEventListener('click', function() {
      selects.forEach(function(select) { select.value = ''; });
      updateSummary();
      if (typeof onChange === 'function') onChange();
    });
    actions.appendChild(summary);
    actions.appendChild(reset);
    container.appendChild(actions);
    function getValues() {
      var values = {};
      selects.forEach(function(select) {
        values[select.getAttribute('data-dc-filter-key')] = select.value;
      });
      return values;
    }
    function updateSummary() {
      var active = selects.filter(function(select) { return select.value; }).length;
      summary.textContent = active ? active + ' active filter' + (active === 1 ? '' : 's') : 'All records';
      reset.disabled = active === 0;
    }
    updateSummary();
    return getValues;
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
  function cssVar(name, fallback) {
    var value = getComputedStyle(document.documentElement).getPropertyValue(name);
    return (value && value.trim()) || fallback || '';
  }
  function chartColorway() {
    var colors = [];
    for (var i = 1; i <= 8; i++) {
      var color = cssVar('--dc-cat-' + i);
      if (color) colors.push(color);
    }
    if (!colors.length) {
      colors = [cssVar('--dc-accent', '#2563eb'), cssVar('--dc-accent-2', '#0f766e'), cssVar('--dc-accent-3', '#c2410c')];
    }
    return colors;
  }
  var CHART_FONT = '-apple-system, BlinkMacSystemFont, "Segoe UI", Inter, sans-serif';
  function mergeDeep(base, over) {
    var out = {};
    Object.keys(base || {}).forEach(function(key) { out[key] = base[key]; });
    Object.keys(over || {}).forEach(function(key) {
      var value = over[key];
      if (value && typeof value === 'object' && !Array.isArray(value) && out[key] && typeof out[key] === 'object' && !Array.isArray(out[key])) {
        out[key] = mergeDeep(out[key], value);
      } else {
        out[key] = value;
      }
    });
    return out;
  }
  function themeAxis(axis) {
    var line = cssVar('--dc-line', '#d9e1ea');
    var muted = cssVar('--dc-muted', '#667085');
    axis = axis || {};
    axis.gridcolor = line;
    axis.zerolinecolor = line;
    axis.linecolor = line;
    axis.tickcolor = line;
    axis.tickfont = mergeDeep({color: muted}, axis.tickfont || {});
    axis.tickfont.color = muted;
    if (axis.automargin === undefined) axis.automargin = true;
    if (axis.title && typeof axis.title === 'string') axis.title = {text: axis.title};
    axis.title = mergeDeep({font: {color: muted}}, axis.title || {});
    axis.title.font = mergeDeep(axis.title.font || {}, {color: muted});
    return axis;
  }
  function applyChartTheme(layout) {
    layout = layout || {};
    delete layout.template;
    var ink = cssVar('--dc-ink', '#111827');
    layout.colorway = layout.colorway || chartColorway();
    layout.font = mergeDeep({size: 12.5}, layout.font || {});
    layout.font.family = CHART_FONT;
    layout.font.color = ink;
    layout.paper_bgcolor = 'rgba(0,0,0,0)';
    layout.plot_bgcolor = 'rgba(0,0,0,0)';
    Object.keys(layout).forEach(function(key) {
      if (/^[xy]axis[0-9]*$/.test(key)) layout[key] = themeAxis(layout[key]);
    });
    layout.xaxis = themeAxis(layout.xaxis);
    layout.yaxis = themeAxis(layout.yaxis);
    layout.legend = mergeDeep({font: {color: ink}, bgcolor: 'rgba(0,0,0,0)'}, layout.legend || {});
    layout.legend.font = mergeDeep(layout.legend.font || {}, {color: ink});
    if (layout.title && typeof layout.title === 'string') layout.title = {text: layout.title};
    if (layout.title) {
      layout.title = mergeDeep({font: {color: ink, size: 15}}, layout.title);
      layout.title.font.color = ink;
    }
    if (!layout.margin) layout.margin = {l: 52, r: 18, t: layout.title ? 40 : 18, b: 50};
    layout.hoverlabel = mergeDeep({font: {family: CHART_FONT}}, layout.hoverlabel || {});
    return layout;
  }
  var chartRegistry = [];
  function registerChartRender(target, render) {
    for (var i = 0; i < chartRegistry.length; i++) {
      if (chartRegistry[i].target === target) {
        chartRegistry[i].render = render;
        return;
      }
    }
    chartRegistry.push({target: target, render: render});
  }
  function rethemeCharts() {
    chartRegistry.forEach(function(entry) {
      if (document.body.contains(entry.target)) entry.render();
    });
  }
  if (window.MutationObserver) {
    new MutationObserver(rethemeCharts).observe(document.documentElement, {attributes: true, attributeFilter: ['data-theme']});
  }
  if (window.matchMedia) {
    try { window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', rethemeCharts); } catch (err) {}
  }
  function renderFigure(target, fig) {
    if (!target) return;
    if (!window.Plotly) {
      target.innerHTML = '<div class="r-empty-state">Chart runtime unavailable.</div>';
      return;
    }
    var layout = applyChartTheme(JSON.parse(JSON.stringify((fig && fig.layout) || {})));
    Plotly.react(target, (fig && fig.data) || [], layout, {responsive: true, displaylogo: false});
    registerChartRender(target, function() { renderFigure(target, fig); });
  }
  function coerceNumber(value) {
    if (typeof value === 'number') return Number.isFinite(value) ? value : null;
    var n = Number(text(value).replace(/,/g, ''));
    return Number.isFinite(n) ? n : null;
  }
  function aggregateValues(values, how) {
    var nums = values.map(coerceNumber).filter(function(v) { return v !== null; });
    if (how === 'count') return values.length;
    if (!nums.length) return values.length ? values[values.length - 1] : null;
    var sum = nums.reduce(function(a, b) { return a + b; }, 0);
    if (how === 'mean') return sum / nums.length;
    if (how === 'max') return Math.max.apply(null, nums);
    if (how === 'min') return Math.min.apply(null, nums);
    return sum;
  }
  function referenceShapes(chart) {
    var shapes = [];
    var annotations = [];
    var accent = cssVar('--dc-accent-3', '#c2410c');
    var muted = cssVar('--dc-muted', '#667085');
    (Array.isArray(chart.reference_lines) ? chart.reference_lines : []).forEach(function(rl) {
      if (!rl || rl.value === undefined || rl.value === null) return;
      var shape = {type: 'line', line: {dash: 'dot', width: 1.6, color: rl.color || accent}};
      if (rl.axis === 'x') {
        shape.x0 = rl.value; shape.x1 = rl.value; shape.yref = 'paper'; shape.y0 = 0; shape.y1 = 1;
        if (rl.label) annotations.push({text: rl.label, x: rl.value, yref: 'paper', y: 1, yanchor: 'bottom', showarrow: false, font: {size: 11, color: muted}});
      } else {
        shape.y0 = rl.value; shape.y1 = rl.value; shape.xref = 'paper'; shape.x0 = 0; shape.x1 = 1;
        if (rl.label) annotations.push({text: rl.label, y: rl.value, xref: 'paper', x: 1, xanchor: 'right', yanchor: 'bottom', showarrow: false, font: {size: 11, color: muted}});
      }
      shapes.push(shape);
    });
    (Array.isArray(chart.annotations) ? chart.annotations : []).forEach(function(note) {
      if (!note || note.text === undefined) return;
      annotations.push({text: text(note.text), x: note.x, y: note.y, showarrow: note.showarrow !== false, arrowhead: 2, arrowsize: 0.8, font: {size: 11}});
    });
    return {shapes: shapes, annotations: annotations};
  }
  function renderChart(target, chart, rows) {
    if (!target) return;
    chart = chart || {};
    rows = rows || [];
    if (!window.Plotly) {
      target.innerHTML = '<div class="r-empty-state">Chart runtime unavailable.</div>';
      return;
    }
    if (!rows.length) {
      if (Plotly.purge) Plotly.purge(target);
      target.innerHTML = '<div class="r-empty-state">No records match the current controls.</div>';
      return;
    }
    if (!target._fullLayout && target.firstChild) target.innerHTML = '';
    var type = chart.type || 'bar';
    var horizontal = type === 'hbar' || chart.orientation === 'h';
    if (type === 'hbar') type = 'bar';
    var xKey = chart.x || chart.x_key || 'x';
    var yKey = chart.y || chart.y_key || 'y';
    var colorKey = chart.color || chart.group || chart.series;
    var traces = [];
    var layout = {};
    if (type === 'heatmap') {
      var zKey = chart.z || chart.value || chart.z_key || 'value';
      var xs = [], ys = [], seenX = {}, seenY = {};
      rows.forEach(function(row) {
        var xv = text(cell(row, xKey));
        var yv = text(cell(row, yKey));
        if (xv && !seenX[xv]) { seenX[xv] = true; xs.push(xv); }
        if (yv && !seenY[yv]) { seenY[yv] = true; ys.push(yv); }
      });
      var z = ys.map(function() { return xs.map(function() { return null; }); });
      rows.forEach(function(row) {
        var xi = xs.indexOf(text(cell(row, xKey)));
        var yi = ys.indexOf(text(cell(row, yKey)));
        if (xi > -1 && yi > -1) z[yi][xi] = coerceNumber(cell(row, zKey));
      });
      var flat = [];
      z.forEach(function(rowVals) { rowVals.forEach(function(v) { if (v !== null) flat.push(v); }); });
      var zMin = Math.min.apply(null, flat);
      var zMax = Math.max.apply(null, flat);
      var diverging = flat.length > 0 && zMin < 0 && zMax > 0;
      var scale = chart.colorscale;
      if (!scale) {
        scale = diverging
          ? [[0, cssVar('--dc-accent', '#2563eb')], [0.5, cssVar('--dc-surface-muted', '#f8fafc')], [1, cssVar('--dc-accent-3', '#c2410c')]]
          : [[0, cssVar('--dc-surface-muted', '#f8fafc')], [1, cssVar('--dc-accent', '#2563eb')]];
      }
      var heatTrace = {
        type: 'heatmap', x: xs, y: ys, z: z, hoverongaps: false,
        colorscale: scale,
        colorbar: {outlinewidth: 0, thickness: 12}
      };
      if (diverging && !chart.colorscale) heatTrace.zmid = 0;
      traces = [heatTrace];
    } else {
      var grouped = {};
      var order = [];
      rows.forEach(function(row) {
        var name = colorKey ? text(cell(row, colorKey)) || 'Series' : chart.name || 'Series';
        if (!grouped[name]) { grouped[name] = {}; order.push(name); }
        var xv = text(cell(row, xKey));
        if (!grouped[name][xv]) grouped[name][xv] = [];
        grouped[name][xv].push(cell(row, yKey));
      });
      var catTotals = {};
      var cats = [];
      order.forEach(function(name) {
        Object.keys(grouped[name]).forEach(function(xv) {
          if (catTotals[xv] === undefined) { catTotals[xv] = 0; cats.push(xv); }
          var agg = aggregateValues(grouped[name][xv], chart.agg || 'sum');
          var n = coerceNumber(agg);
          if (n !== null) catTotals[xv] += n;
        });
      });
      var sortMode = chart.sort === undefined ? (type === 'bar' ? 'value' : 'none') : chart.sort;
      if (sortMode === true) sortMode = 'value';
      if (sortMode === false) sortMode = 'none';
      if (sortMode === 'value' || sortMode === 'asc' || sortMode === 'desc') {
        var dir = sortMode === 'asc' ? 1 : -1;
        cats.sort(function(a, b) { return (catTotals[a] - catTotals[b]) * dir; });
      } else if (sortMode === 'label') {
        cats.sort(function(a, b) { return a.localeCompare(b, undefined, {numeric: true}); });
      }
      traces = order.map(function(name) {
        var xsOut = [], ysOut = [];
        cats.forEach(function(xv) {
          if (!grouped[name][xv]) return;
          xsOut.push(xv);
          ysOut.push(aggregateValues(grouped[name][xv], chart.agg || 'sum'));
        });
        var trace = {name: name, type: type === 'line' ? 'scatter' : type};
        if (horizontal) {
          trace.x = ysOut; trace.y = xsOut; trace.orientation = 'h';
        } else {
          trace.x = xsOut; trace.y = ysOut;
        }
        if (type === 'scatter') trace.mode = chart.mode || 'markers';
        if (type === 'line') trace.mode = chart.mode || 'lines+markers';
        return trace;
      });
      var catAxis = {categoryorder: 'array', categoryarray: cats};
      var xTitle = chart.x_label || text(xKey).replace(/_/g, ' ');
      var yTitle = chart.y_label || text(yKey).replace(/_/g, ' ');
      if (horizontal) {
        layout.yaxis = mergeDeep(catAxis, {title: xTitle, autorange: 'reversed'});
        layout.xaxis = {title: yTitle};
      } else {
        layout.xaxis = mergeDeep(catAxis, {title: xTitle});
        layout.yaxis = {title: yTitle};
      }
      if (order.length > 1 && type === 'bar') layout.barmode = chart.barmode || 'group';
    }
    if (chart.title) layout.title = {text: chart.title};
    var extras = referenceShapes(chart);
    if (extras.shapes.length) layout.shapes = (layout.shapes || []).concat(extras.shapes);
    if (extras.annotations.length) layout.annotations = (layout.annotations || []).concat(extras.annotations);
    layout = mergeDeep(layout, chart.layout || {});
    Plotly.react(target, traces, applyChartTheme(layout), {responsive: true, displaylogo: false});
    registerChartRender(target, function() { renderChart(target, chart, rows); });
  }
  function initTable(root, config, rowsProvider) {
    var baseRows = normalizeTableRows(config.rows || config.records || [], config.columns);
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
      input.id = slugId('table-search-' + Math.random().toString(36).slice(2, 8), 'search');
      input.type = 'search';
      input.placeholder = config.search_placeholder || 'Search table';
      input.setAttribute('aria-label', config.search_label || 'Search table');
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
    var numericCols = {};
    cols.forEach(function(col) {
      var sample = baseRows.filter(function(row) { return text(cell(row, col.key)) !== ''; });
      numericCols[col.key] = sample.length > 0 && sample.every(function(row) { return coerceNumber(cell(row, col.key)) !== null; });
    });
    function formatCell(value, key) {
      if (!numericCols[key]) return esc(value);
      var n = coerceNumber(value);
      if (n === null) return esc(value);
      return esc(n.toLocaleString(undefined, {maximumFractionDigits: 2}));
    }
    function render() {
      if (!target) return;
      var rows = activeRows();
      var pages = Math.max(1, Math.ceil(rows.length / pageSize));
      state.page = Math.min(state.page, pages);
      var start = (state.page - 1) * pageSize;
      var shown = rows.slice(start, start + pageSize);
      var head = '<thead><tr>' + cols.map(function(col) {
        var sorted = state.sortKey === col.key;
        var ariaSort = sorted ? (state.sortDir === 1 ? 'ascending' : 'descending') : 'none';
        var marker = sorted ? (state.sortDir === 1 ? '▲' : '▼') : '';
        var numClass = numericCols[col.key] ? ' class="num"' : '';
        return '<th scope="col"' + numClass + ' aria-sort="' + ariaSort + '"><button type="button" class="r-sort-button" data-key="' + esc(col.key) + '" aria-label="Sort by ' + esc(col.label) + '">' + esc(col.label) + '<span class="r-sort-indicator" aria-hidden="true">' + marker + '</span></button></th>';
      }).join('') + '</tr></thead>';
      var bodyRows = shown.length
        ? shown.map(function(row) {
            return '<tr>' + cols.map(function(col) {
              var numClass = numericCols[col.key] ? ' class="num"' : '';
              return '<td' + numClass + '>' + formatCell(cell(row, col.key), col.key) + '</td>';
            }).join('') + '</tr>';
          }).join('')
        : '<tr><td colspan="' + Math.max(1, cols.length) + '"><div class="r-empty-state">No matching rows. Adjust filters or search.</div></td></tr>';
      var body = '<tbody>' + bodyRows + '</tbody>';
      target.innerHTML = '<table class="r-interactive-table">' + head + body + '</table>';
      Array.prototype.slice.call(target.querySelectorAll('.r-sort-button[data-key]')).forEach(function(button) {
        button.addEventListener('click', function() {
          var key = button.getAttribute('data-key');
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
        pager.innerHTML = '<button type="button" data-prev aria-label="Previous page">Prev</button><span>Showing ' + (rows.length ? start + 1 : 0) + '-' + end + ' of ' + rows.length + '</span><button type="button" data-next aria-label="Next page">Next</button>';
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
  window.DataClawReport.renderFigureById = function(id, config) {
    var target = document.getElementById(id);
    if (!target) return;
    renderFigure(target, (config && config.figure) || {});
  };
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
  function selectorKey(item, index) {
    if (item && typeof item === 'object') return text(item.id || item.key || item.name || item.title || index);
    return text(index);
  }
  function itemTitle(item, fallback) {
    if (item && typeof item === 'object') return text(item.title || item.headline || item.name || item.label || fallback);
    return text(item || fallback);
  }
  function itemDetail(item) {
    if (!item || typeof item !== 'object') return '';
    return text(item.summary || item.detail || item.description || item.rationale || item.text || '');
  }
  function renderMetricRows(metrics) {
    var rows = [];
    if (metrics && typeof metrics === 'object' && !Array.isArray(metrics)) {
      Object.keys(metrics).forEach(function(key) {
        rows.push({label: key.replace(/_/g, ' '), value: metrics[key]});
      });
    } else if (Array.isArray(metrics)) {
      metrics.forEach(function(metric) {
        if (metric && typeof metric === 'object') rows.push({label: text(metric.label || metric.name || metric.key), value: metric.value});
      });
    }
    return rows.filter(function(row) { return row.label || row.value !== undefined; }).map(function(row) {
      return '<div class="r-entity-metric"><span>' + esc(row.label) + '</span><strong>' + esc(row.value) + '</strong></div>';
    }).join('');
  }
  function renderSelectionDetail(target, item) {
    if (!target) return;
    if (!item) {
      target.innerHTML = '<div class="r-empty-state">No selections match the current controls.</div>';
      return;
    }
    var detail = itemDetail(item);
    var metrics = item && typeof item === 'object' ? renderMetricRows(item.metrics) : '';
    target.innerHTML = '<h3>' + esc(itemTitle(item, 'Selected item')) + '</h3>' +
      (detail ? '<p>' + esc(detail) + '</p>' : '') +
      (metrics ? '<div class="r-entity-metrics">' + metrics + '</div>' : '');
  }
  window.DataClawReport.initSelectorPanel = function(id, config) {
    var root = document.getElementById(id);
    if (!root) return;
    var items = config.items || config.options || [];
    var cards = Array.prototype.slice.call(root.querySelectorAll('[data-dc-selector-card]'));
    var detail = root.querySelector('[data-dc-selection-detail]');
    var keys = items.map(selectorKey);
    var selectedKey = keys[0] || '';
    var getFilters = buildControls(root.querySelector('[data-dc-control-bar]'), config.controls || config.filters || [], items, update);
    cards.forEach(function(card) {
      var key = card.getAttribute('data-dc-selector-card');
      card.setAttribute('role', 'button');
      card.setAttribute('tabindex', '0');
      card.setAttribute('aria-pressed', key === selectedKey ? 'true' : 'false');
      card.addEventListener('click', function() {
        selectedKey = key;
        update();
      });
      card.addEventListener('keydown', function(event) {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          selectedKey = key;
          update();
        }
      });
    });
    function update() {
      var visible = {};
      var filtered = applyFilters(items, getFilters());
      filtered.forEach(function(item) {
        var index = items.indexOf(item);
        visible[keys[index]] = true;
      });
      if (!visible[selectedKey]) selectedKey = filtered.length ? keys[items.indexOf(filtered[0])] : '';
      cards.forEach(function(card) {
        var key = card.getAttribute('data-dc-selector-card');
        var isVisible = !!visible[key];
        var isSelected = key === selectedKey;
        card.style.display = isVisible ? '' : 'none';
        card.classList.toggle('is-selected', isSelected);
        card.setAttribute('aria-pressed', isSelected ? 'true' : 'false');
      });
      var selectedIndex = keys.indexOf(selectedKey);
      renderSelectionDetail(detail, selectedIndex >= 0 ? items[selectedIndex] : null);
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
    });
    var navigationSections = sections.filter(function(section) {
      var heading = section.querySelector('h1, h2, h3');
      return Boolean(heading && heading.textContent.trim());
    });
    navigationSections.forEach(function(section, index) {
      var heading = section.querySelector('h1, h2, h3');
      var label = heading.textContent.trim();
      if (nav && navigationSections.length > 1) {
        var link = document.createElement('a');
        link.href = '#' + section.id;
        var num = document.createElement('span');
        num.className = 'r-nav-num';
        num.textContent = (index < 9 ? '0' : '') + (index + 1);
        link.appendChild(num);
        link.appendChild(document.createTextNode(label));
        link.dataset.target = section.id;
        nav.appendChild(link);
      }
    });
    if (nav && nav.children.length > 1) {
      var head = document.createElement('div');
      head.className = 'r-story-nav-head';
      head.textContent = 'Contents';
      nav.insertBefore(head, nav.firstChild);
      nav.classList.add('ready');
      document.body.classList.add('has-rail');
    }
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
            if (navLinks.some(function(link) { return link.dataset.target === entry.target.id; })) {
              markActive(entry.target.id);
            }
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
    runtime_smoke: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Inspect the typed section metadata embedded in a workspace report.

    Criteria severities, gate thresholds, and live/deferred status come from the
    report rubric (report_rubric.yaml); every result cites the rubric version it
    was judged by. Only ``status: live`` criteria are evaluated — the signal
    checks themselves live here, keyed by criterion id.
    """
    sections = _extract_section_meta(doc)
    warnings: list[dict[str, Any]] = []
    criteria = rubric_criteria()
    thresholds = rubric_thresholds()

    def warn(code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        criterion = criteria.get(code)
        if criterion is None:
            raise KeyError(f"gate check {code!r} has no criterion in the report rubric")
        if criterion["status"] != "live":
            return
        entry: dict[str, Any] = {
            "code": code,
            "severity": criterion["severity"],
            "message": message,
            "details": details or {},
        }
        if criterion.get("replaces"):
            entry["replaces"] = criterion["replaces"]
        warnings.append(entry)

    if not sections:
        warn(
            "unstructured_report",
            "Report contains no typed section metadata; publish structured storyboard output or migrate the report before publishing.",
            details={"required_marker": "data-dc-section-meta"},
        )

    total_size = len(doc.encode("utf-8"))
    payload_size = len(PLOTLY_RUNTIME_RE.sub("", doc).encode("utf-8"))
    if payload_size > max_bytes:
        warn(
            "oversized_report",
            f"Report payload HTML is {payload_size} bytes; reduce embedded raw HTML/data before publishing.",
            details={"bytes": payload_size, "total_bytes": total_size, "max_bytes": max_bytes},
        )

    if stale_skills:
        warn(
            "stale_installed_skills",
            "Installed library skills are stale versus bundled skill-library instructions.",
            details={"skills": stale_skills},
        )

    kinds = [clean_text(section.get("kind") or "") for section in sections]
    plain_chart_count = kinds.count("chart")
    chart_like_count = sum(1 for kind in kinds if kind in CHART_SECTION_KINDS)
    interpreted_chart_count = kinds.count("chart_interpretation")
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
    if longest_run > thresholds["max_consecutive_plain_charts"]:
        warn(
            "consecutive_plain_charts",
            "Report contains three or more consecutive plain chart sections; use chart_interpretation or an explorer to keep evidence and meaning together.",
            details={"longest_run": longest_run},
        )
    if plain_chart_count >= thresholds["plain_chart_dump_min"] and interactive_count == 0 and "chart_interpretation" not in kinds:
        warn(
            "chart_dump",
            "Report is dominated by plain charts without interpretation or interactive explorer sections.",
            details={"plain_chart_count": plain_chart_count, "interactive_count": interactive_count},
        )
    if plain_chart_count >= thresholds["plain_chart_dump_min"] and plain_chart_count > (interactive_count + interpreted_chart_count):
        warn(
            "plain_chart_overuse",
            "Report still relies on too many plain chart sections; convert supporting charts into interpretation or explorer sections.",
            details={
                "plain_chart_count": plain_chart_count,
                "interactive_count": interactive_count,
                "chart_interpretation_count": interpreted_chart_count,
            },
        )
    if len(kinds) >= thresholds["insight_required_min_sections"] and story_count == 0:
        warn(
            "missing_insight_sections",
            "Report has multiple sections but no findings, insight grid, narrative band, methodology, evidence, or explorer layer.",
            details={"section_count": len(kinds)},
        )
    if len(kinds) >= thresholds["insight_required_min_sections"] and primary_insight_count == 0:
        warn(
            "missing_primary_insights",
            "Report has multiple sections but no findings or insight grid carrying completed insight items.",
            details={"section_count": len(kinds)},
        )
    if (
        len(kinds) >= thresholds["explorer_required_min_sections"]
        and chart_like_count >= thresholds["explorer_required_min_charts"]
        and interactive_count == 0
    ):
        warn(
            "missing_interactive_explorer",
            "Analytical report has several charts but no interactive table, selector, filterable chart, or chart-table explorer.",
            details={"chart_like_count": chart_like_count},
        )

    for section in sections:
        kind = clean_text(section.get("kind") or "")
        payload = section.get("payload") if isinstance(section.get("payload"), dict) else {}
        if kind in {"table", "interactive_table"} and not clean_text(section.get("caption") or payload.get("caption") or ""):
            warn(
                "missing_table_caption",
                "Table section is missing a caption that explains grain, filters, or interpretation.",
                details={"section_id": section.get("section_id"), "kind": kind},
            )
        if kind in {"findings", "insight_grid", "hypothesis_ledger", "evidence_trace", "evidence_rail"}:
            items = payload.get("items", [])
            if isinstance(items, list) and items and not any(_item_has_evidence_id(item) for item in items if isinstance(item, dict)):
                warn(
                    "unsourced_claim",
                    "Insight/evidence section has items but no finding_id, hypothesis_id, or evidence reference in metadata.",
                    details={"section_id": section.get("section_id"), "kind": kind},
                )
        if kind == "chart_interpretation" and payload.get("has_interpretation") and not payload.get("evidence_count"):
            warn(
                "chart_interpretation_missing_evidence",
                "Chart interpretation has a narrative conclusion but no evidence refs.",
                details={"section_id": section.get("section_id")},
            )

        if kind in {"chart", "chart_interpretation", "filterable_chart"} and not clean_text(
            payload.get("conclusion") or payload.get("interpretation") or payload.get("insight") or payload.get("summary") or ""
        ):
            warn(
                "chart_missing_conclusion",
                "Chart section has no stated interpretation or conclusion.",
                details={"section_id": section.get("section_id"), "kind": kind},
            )
        if kind not in {"header", "metric_row"} and not clean_text(section.get("caption") or payload.get("caption") or payload.get("dek") or ""):
            warn(
                "missing_section_dek",
                "Section is missing a short dek/caption that explains why it is in the story.",
                details={"section_id": section.get("section_id"), "kind": kind},
            )
        if kind in {"findings", "insight_grid"}:
            items = payload.get("items", payload.get("findings", []))
            if isinstance(items, list) and any(not isinstance(item, dict) for item in items):
                warn(
                    "bare_bullet_findings",
                    "Findings should use typed insight-card items, not bare bullet strings.",
                    details={"section_id": section.get("section_id"), "kind": kind},
                )
            if isinstance(items, list) and any(
                isinstance(item, dict)
                and _evidence_refs_from_value(item.get("evidence") or item.get("evidence_refs"))
                and not clean_text(item.get("evidence_anchor") or "")
                for item in items
            ):
                warn(
                    "unpaired_insights",
                    "Insight carries evidence refs but is not paired to an evidence section anchor.",
                    details={"section_id": section.get("section_id"), "kind": kind},
                )

    registry_document = _extract_evidence_registry_document(doc)
    registry = _extract_evidence_registry(doc)
    registry_references = registry_document.get("references", []) if isinstance(registry_document.get("references", []), list) else []
    unresolved_refs = _unresolved_evidence_refs(sections, registry, registry_references)
    if unresolved_refs:
        warn(
            "evidence_unresolved",
            "One or more evidence references do not resolve to a registered target present in the report bundle.",
            details={"references": unresolved_refs[:20], "count": len(unresolved_refs)},
        )

    if len(sections) >= 2 and "narrative_band" not in kinds:
        warn(
            "missing_narrative_answer",
            "Report has multiple sections but no narrative band answering the primary question up front.",
            details={"section_count": len(sections)},
        )

    theme_failures = _chart_theme_failures(sections)
    if theme_failures:
        warn(
            "chart_theme_defeated",
            "Stored chart styling can defeat the report's token-driven theme and dark-mode re-render.",
            details={"sections": theme_failures},
        )

    external_assets = _external_asset_refs(doc)
    if external_assets:
        warn(
            "not_self_contained",
            "Report references external assets that will not be available in a self-contained artifact.",
            details={"assets": external_assets[:20], "count": len(external_assets)},
        )

    static_smoke_failures = _runtime_smoke_failures(doc, sections)
    smoke_result = runtime_smoke or {
        "status": "static",
        "checks": static_smoke_failures,
    }
    smoke_failures = static_smoke_failures
    if runtime_smoke and runtime_smoke.get("status") == "failed":
        smoke_failures = [
            *static_smoke_failures,
            *[entry for entry in runtime_smoke.get("checks", []) if isinstance(entry, dict)],
        ]
    if runtime_smoke and runtime_smoke.get("status") == "skipped":
        smoke_failures = [
            *static_smoke_failures,
            {"check": "browser_smoke", "detail": clean_text(runtime_smoke.get("reason") or "browser smoke was skipped")},
        ]
    if smoke_failures:
        warn(
            "runtime_smoke_failed",
            "Structural runtime smoke checks found report wiring that cannot initialize correctly.",
            details={"checks": smoke_failures},
        )

    contrast_failures = _contrast_failures(doc)
    if contrast_failures:
        warn(
            "contrast_below_aa",
            "Report color tokens do not meet the configured WCAG-AA text contrast checks.",
            details={"pairs": contrast_failures},
        )

    status = "pass"
    if any(w["severity"] == "fail" for w in warnings):
        status = "fail"
    elif warnings:
        status = "warn"

    return {
        "status": status,
        "rubric_version": rubric_version(),
        "section_count": len(sections),
        "plain_chart_count": plain_chart_count,
        "interactive_count": interactive_count,
        "story_count": story_count,
        "runtime_smoke": smoke_result,
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


def _evidence_registry_script(registry: dict[str, Any] | None) -> str:
    if not registry:
        return ""
    payload = _json_for_script(registry)
    return f'<script type="application/json" data-dc-evidence-registry>{payload}</script>'


def _extract_evidence_registry(doc: str) -> dict[str, dict[str, Any]]:
    parsed = _extract_evidence_registry_document(doc)
    targets = parsed.get("targets", []) if isinstance(parsed, dict) else []
    if not isinstance(targets, list):
        return {}
    registry: dict[str, dict[str, Any]] = {}
    for target in targets:
        if not isinstance(target, dict):
            continue
        ref = clean_text(target.get("id") or target.get("ref") or "")
        if ref:
            registry[ref] = target
    return registry


def _extract_evidence_registry_document(doc: str) -> dict[str, Any]:
    match = re.search(
        r"<script[^>]*data-dc-evidence-registry[^>]*>(.*?)</script>",
        doc,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return {}
    try:
        parsed = json.loads(match.group(1))
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _evidence_refs_from_value(value: Any) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    for entry in _as_list(value):
        if isinstance(entry, dict):
            kind = clean_text(entry.get("kind") or entry.get("type") or "unknown")
            ref = clean_text(
                entry.get("ref")
                or entry.get("cell_id")
                or entry.get("artifact_id")
                or entry.get("finding_id")
                or entry.get("hypothesis_id")
                or entry.get("path")
                or ""
            )
        else:
            kind = "unknown"
            ref = clean_text(entry)
        if ref:
            refs.append({"kind": kind, "ref": ref})
    return refs


def _unresolved_evidence_refs(
    sections: list[dict[str, Any]],
    registry: dict[str, dict[str, Any]],
    registered_references: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    unresolved: list[dict[str, str]] = []
    references = registered_references or []
    if not references:
        for section in sections:
            payload = section.get("payload") if isinstance(section.get("payload"), dict) else {}
            for key in ("evidence", "evidence_refs"):
                references.extend({"section_id": clean_text(section.get("section_id") or ""), **reference} for reference in _evidence_refs_from_value(payload.get(key)))
    for reference in references:
        target = registry.get(reference["ref"])
        target_kind = clean_text(target.get("kind") or target.get("type") or "") if target else ""
        is_external = bool(target and clean_text(target.get("external_url") or target.get("url") or ""))
        is_present = bool(target and target.get("present", True))
        kind_matches = not target_kind or target_kind == reference["kind"] or reference["kind"] == "unknown"
        if not target or not is_present or (not is_external and not kind_matches):
            unresolved.append(dict(reference))
    return unresolved


def build_evidence_registry(storyboard: dict[str, Any]) -> dict[str, Any]:
    """Normalize explicit evidence targets and registered in-report finding targets.

    Only supplied targets and identifiers already present in the report are
    registered. The function never invents a provenance id merely to satisfy a
    quality check.
    """
    supplied = storyboard.get("evidence_registry", {})
    raw_targets = supplied.get("targets", []) if isinstance(supplied, dict) else supplied
    targets: dict[str, dict[str, Any]] = {}
    references: list[dict[str, str]] = []
    for raw in _as_list(raw_targets):
        if not isinstance(raw, dict):
            continue
        ref = clean_text(raw.get("id") or raw.get("ref") or "")
        kind = clean_text(raw.get("kind") or raw.get("type") or "")
        if not ref or not kind:
            continue
        target = dict(raw)
        target["id"] = ref
        target["kind"] = kind
        target.setdefault("present", True)
        targets[ref] = target

    section_plan = storyboard.get("section_plan", [])
    if isinstance(section_plan, list):
        for planned in section_plan:
            data = planned.get("data") if isinstance(planned, dict) and isinstance(planned.get("data"), dict) else {}
            section_id = clean_text(data.get("section_id") or planned.get("layout_role") or "")
            for source in [data, *_as_list(data.get("items")), *_as_list(data.get("findings")), *_as_list(data.get("hypotheses"))]:
                if not isinstance(source, dict):
                    continue
                for key in ("evidence", "evidence_refs"):
                    references.extend({"section_id": section_id, **reference} for reference in _evidence_refs_from_value(source.get(key)))
            item_groups = [data.get("items"), data.get("findings"), data.get("hypotheses")]
            for group in item_groups:
                for item in _as_list(group):
                    if not isinstance(item, dict):
                        continue
                    for key in ("finding_id", "hypothesis_id"):
                        ref = clean_text(item.get(key) or "")
                        if ref and ref not in targets:
                            targets[ref] = {
                                "id": ref,
                                "kind": "finding",
                                "present": True,
                                "source": "report_section",
                            }

    return {
        "evidence_registry_schema": 1,
        "targets": list(targets.values()),
        "references": references,
    }


class _RawReportIntakeParser(HTMLParser):
    """Small, dependency-free extractor for normalizing ordinary authored HTML."""

    _TEXT_TAGS = {"title", "h1", "h2", "h3", "p", "li"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[tuple[str, str]] = []
        self.tables: list[list[list[str]]] = []
        self.unsupported: set[str] = set()
        self._active_tag = ""
        self._text_parts: list[str] = []
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell_parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"script", "canvas", "svg", "iframe", "video", "object"}:
            self.unsupported.add(tag)
        if tag in self._TEXT_TAGS:
            self._flush_text()
            self._active_tag = tag
        if tag == "table":
            self._table = []
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in {"th", "td"} and self._row is not None:
            self._cell_parts = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == self._active_tag:
            self._flush_text()
        if tag in {"th", "td"} and self._cell_parts is not None and self._row is not None:
            self._row.append(clean_text(" ".join(self._cell_parts)))
            self._cell_parts = None
        elif tag == "tr" and self._row is not None and self._table is not None:
            if any(self._row):
                self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            if self._table:
                self.tables.append(self._table)
            self._table = None

    def handle_data(self, data: str) -> None:
        if self._cell_parts is not None:
            self._cell_parts.append(data)
        elif self._active_tag:
            self._text_parts.append(data)

    def _flush_text(self) -> None:
        text = clean_text(" ".join(self._text_parts))
        if text:
            self.blocks.append((self._active_tag, text))
        self._active_tag = ""
        self._text_parts = []


def _raw_html_storyboard(
    raw_html: str,
    *,
    title: str,
    report_goal: str,
    audience: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    parser = _RawReportIntakeParser()
    parser.feed(raw_html)
    parser.close()
    parser._flush_text()

    page_title = next((text for tag, text in parser.blocks if tag == "title"), "")
    heading = next((text for tag, text in parser.blocks if tag == "h1"), "")
    effective_title = clean_text(title or heading or page_title or "Normalized report")
    content = [(tag, text) for tag, text in parser.blocks if tag not in {"title", "h1"}]
    insights: list[dict[str, Any]] = []
    pending_heading = ""
    for tag, text in content:
        if tag in {"h2", "h3"}:
            pending_heading = text
            continue
        if tag not in {"p", "li"}:
            continue
        insights.append({
            "title": pending_heading or text[:90].rstrip(". ") or "Source observation",
            "detail": text,
            "status": "unverified",
            "caveat": "Extracted from legacy HTML; attach an evidence reference before treating this as a validated claim.",
        })
        pending_heading = ""
        if len(insights) >= 7:
            break
    if not insights:
        insights.append({
            "title": effective_title,
            "detail": "The source document was preserved, but its prose could not be reliably extracted into detailed findings.",
            "status": "unverified",
            "caveat": "Review the preserved source HTML and supply typed insights or evidence before publication.",
        })

    analyses: list[dict[str, Any]] = []
    for index, table in enumerate(parser.tables[:5]):
        if len(table) < 2:
            continue
        headers = [cell or f"Column {position + 1}" for position, cell in enumerate(table[0])]
        rows = [
            {headers[position]: row[position] if position < len(row) else "" for position in range(len(headers))}
            for row in table[1:101]
        ]
        analyses.append({
            "section_type": "interactive_table",
            "title": f"Extracted table {index + 1}",
            "caption": "Table extracted from the preserved source HTML; verify grain and filters against the original.",
            "columns": headers,
            "rows": rows,
        })

    total_signal = len(content) + len(parser.tables) * 2
    confidence = min(1.0, 0.25 + 0.12 * total_signal - 0.12 * len(parser.unsupported))
    mode = "structured_rebuild" if confidence >= 0.55 else "preserved_low_confidence"
    storyboard = design_report_storyboard(
        report_goal=clean_text(report_goal or heading or page_title or effective_title),
        insights=insights,
        analyses=analyses,
        audience=audience,
        title=effective_title,
        requirements={
            "kicker": "Normalized legacy report",
            "checks": [{
                "title": "Source preservation",
                "status": "warning" if mode == "preserved_low_confidence" else "pass",
                "detail": "Original HTML is stored beside this rebuilt report.",
            }],
        },
    )
    normalization = {
        "normalization_schema": 1,
        "mode": mode,
        "confidence": round(confidence, 2),
        "source_sha256": hashlib.sha256(raw_html.encode("utf-8")).hexdigest(),
        "extracted": {
            "text_blocks": len(content),
            "tables": len(analyses),
            "unsupported_elements": sorted(parser.unsupported),
        },
    }
    storyboard["normalization"] = normalization
    return storyboard, normalization


def normalize_raw_html_report(
    raw_html: str,
    *,
    title: str = "",
    report_goal: str = "",
    audience: str = "",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Turn raw HTML into a typed storyboard without discarding the source artifact."""
    sections = _extract_section_meta(raw_html)
    if not sections:
        return _raw_html_storyboard(raw_html, title=title, report_goal=report_goal, audience=audience)

    title_match = re.search(r"<title[^>]*>(.*?)</title>", raw_html, re.IGNORECASE | re.DOTALL)
    effective_title = clean_text(title or (title_match.group(1) if title_match else "Structured report"))
    plan: list[dict[str, Any]] = []
    for index, section in enumerate(sections):
        section_type = clean_text(section.get("kind") or "text")
        data = section.get("payload") if isinstance(section.get("payload"), dict) else {}
        data = dict(data)
        data.setdefault("section_id", clean_text(section.get("section_id") or f"section-{index + 1}"))
        plan.append({
            "section_type": section_type,
            "layout_role": f"preserved_{index + 1}_{section_type}",
            "rationale": "Preserve an existing typed section while refreshing the report shell.",
            "data": data,
        })
    storyboard = {
        "storyboard_schema": 1,
        "title": effective_title,
        "report_goal": clean_text(report_goal or effective_title),
        "audience": clean_text(audience or "decision-maker"),
        "designer": {"mode": "typed_preservation", "note": "Re-render existing typed report sections."},
        "section_plan": plan,
        "normalization": {
            "normalization_schema": 1,
            "mode": "typed_preservation",
            "confidence": 1.0,
            "render_from_source": True,
            "source_sha256": hashlib.sha256(raw_html.encode("utf-8")).hexdigest(),
        },
    }
    return storyboard, storyboard["normalization"]


def critique_report_storyboard(
    storyboard: dict[str, Any],
    *,
    max_passes: int = 5,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Apply bounded, non-fabricating improvements and review a storyboard.

    The repair pass may safely add presentational context, but it must never
    manufacture analytical evidence.  The review record is deliberately
    separate: it makes missing validation, uncertainty, sensitivity, and
    decision-path work visible to the caller as durable findings instead of
    silently leaving those gaps for a later chat turn to rediscover.
    """
    working = copy.deepcopy(storyboard)
    section_plan = working.get("section_plan")
    if not isinstance(section_plan, list):
        raise ValueError("storyboard requires a section_plan for critique")

    applied: list[dict[str, Any]] = []
    passes = 0
    converged = False
    for pass_number in range(1, max(1, max_passes) + 1):
        changed = False
        passes = pass_number
        for index, planned in enumerate(section_plan):
            if not isinstance(planned, dict):
                continue
            section_type = clean_text(planned.get("section_type") or planned.get("kind") or "")
            data = planned.get("data") if isinstance(planned.get("data"), dict) else {}
            if not data:
                continue
            title = clean_text(data.get("title") or section_type.replace("_", " ").title() or "this section")
            if section_type not in {"header", "metric_row"} and not clean_text(data.get("caption") or data.get("dek") or ""):
                data["caption"] = f"Context and evidence for {title}."
                planned["data"] = data
                planned["rationale"] = clean_text(planned.get("rationale") or "") + " Added a concise section dek."
                applied.append({"pass": pass_number, "section": index, "action": "add_section_dek"})
                changed = True
            if section_type in {"table", "interactive_table"} and not clean_text(data.get("caption") or ""):
                columns = data.get("columns", [])
                labels = ", ".join(clean_text(column.get("label") or column.get("key") or "") if isinstance(column, dict) else clean_text(column) for column in _as_list(columns)[:4])
                data["caption"] = f"Extracted values by {labels or 'available fields'}; verify grain and filters before interpretation."
                planned["data"] = data
                applied.append({"pass": pass_number, "section": index, "action": "add_table_caption"})
                changed = True
            if section_type in {"findings", "insight_grid"}:
                items = data.get("items", data.get("findings", []))
                if isinstance(items, list):
                    for item in items:
                        if isinstance(item, dict) and not _item_has_evidence_id(item) and not clean_text(item.get("caveat") or ""):
                            item["status"] = item.get("status") or "unverified"
                            item["caveat"] = "Evidence reference was not supplied in the source material."
                            applied.append({"pass": pass_number, "section": index, "action": "flag_missing_evidence"})
                            changed = True
        if not changed:
            converged = True
            break

    design_review = _critique_editorial_design(working, max_passes=max_passes)
    working["design_review"] = design_review
    registry = build_evidence_registry(working)
    working["evidence_registry"] = registry
    analytical_review = review_storyboard_analysis(working, registry=registry)
    working["analytical_review"] = analytical_review
    critique = {
        "critique_schema": 1,
        "max_passes": max(1, max_passes),
        "passes": passes,
        "converged": converged,
        "applied": applied,
        "design_review": design_review,
        "analytical_review": analytical_review,
        "guardrail": "No evidence identifiers, citations, numbers, or claims were invented during critique.",
    }
    working["critique"] = critique
    return working, critique


_PREDICTIVE_REVIEW_TERMS = (
    "forecast",
    "prediction",
    "predictive",
    "predict ",
    "projected",
    "projection",
    "win probability",
    "advance probability",
    "champion odds",
)
_BASELINE_REVIEW_TERMS = (
    "baseline",
    "ablation",
    "out-of-sample",
    "holdout",
    "cross-validation",
    "cross validation",
    "log-loss",
    "log loss",
    "brier",
    "backtest",
)
_UNCERTAINTY_REVIEW_TERMS = (
    "uncertainty",
    "credible interval",
    "confidence interval",
    "bootstrap",
    "standard error",
    "prediction interval",
    "confidence band",
)
_SENSITIVITY_REVIEW_TERMS = (
    "sensitivity",
    "scenario",
    "robustness",
    "robust to",
    "alternate pairing",
    "alternative pairing",
)
_ASSUMPTION_REVIEW_TERMS = (
    "assumption",
    "assumed",
    "inferred",
    "estimate",
    "estimated",
    "placeholder",
)
_TOURNAMENT_REVIEW_TERMS = (
    "tournament",
    "knockout",
    "bracket",
    "quarter-final",
    "quarterfinal",
    "semi-final",
    "semifinal",
)
_DECISION_PATH_REVIEW_TERMS = ("bracket", "tree", "decision path")
_MATCH_DISTRIBUTION_REVIEW_TERMS = ("scoreline", "heatmap", "outcome distribution", "score distribution")


def review_storyboard_analysis(
    storyboard: dict[str, Any],
    *,
    registry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Recompute the analytical-completeness review for a storyboard.

    This public entry point is used by both the design critique and the publish
    gate so a stored, stale review record cannot be treated as an approval.
    """
    return _review_storyboard_analysis(storyboard, registry or build_evidence_registry(storyboard))


def _review_storyboard_analysis(storyboard: dict[str, Any], registry: dict[str, Any]) -> dict[str, Any]:
    """Return durable, conservative analytical-review findings for a report.

    This is intentionally a completeness review, not a model evaluator.  It
    relies on an optional ``requirements.analysis_review`` contract plus the
    supplied storyboard text.  The latter lets legacy callers get useful
    warnings, while the contract lets new callers state exactly which analysis
    checks were completed without asking the renderer to infer or recompute
    scientific results.
    """
    contract = storyboard.get("analysis_contract")
    contract = dict(contract) if isinstance(contract, dict) else {}
    text = _storyboard_review_text(storyboard)
    delivered_text = _storyboard_review_text(storyboard, include_context=False)
    mode = clean_text(contract.get("mode") or "").lower()
    is_predictive = mode in {"forecast", "forecasting", "predictive", "prediction", "simulation"}
    if not is_predictive:
        is_predictive = _contains_any(text, _PREDICTIVE_REVIEW_TERMS)

    findings: list[dict[str, Any]] = []

    def add(
        finding_id: str,
        *,
        category: str,
        severity: str,
        claim: str,
        recommendation: str,
        evidence: list[dict[str, str]] | None = None,
    ) -> None:
        findings.append({
            "id": finding_id,
            "category": category,
            "severity": severity,
            "claim": claim,
            "recommendation": recommendation,
            "evidence": evidence or [],
        })

    targets = registry.get("targets", []) if isinstance(registry.get("targets"), list) else []
    target_map = {
        clean_text(target.get("id") or target.get("ref") or ""): target
        for target in targets
        if isinstance(target, dict) and clean_text(target.get("id") or target.get("ref") or "")
    }

    if is_predictive:
        if not _baseline_review_complete(contract.get("baseline"), target_map):
            add(
                "missing_baseline_comparison",
                category="model_validation",
                severity="required",
                claim="This predictive report has no completed, resolvable baseline comparison with a method and result.",
                recommendation="Compare the production approach with a simple baseline on a shared holdout, report the primary metric plus the delta, and cite a registered evidence target for that output.",
            )
        if not _review_item_complete(contract.get("uncertainty")) and not _contains_any(delivered_text, _UNCERTAINTY_REVIEW_TERMS):
            add(
                "missing_uncertainty_quantification",
                category="uncertainty",
                severity="warning",
                claim="This predictive report presents point estimates without a declared uncertainty method.",
                recommendation="Add intervals or uncertainty bands derived from a stated method (for example bootstrap, posterior draws, or an appropriate analytical interval).",
            )

    assumptions_declared = _review_item_complete(contract.get("sensitivity"))
    has_assumption = bool(_as_list(contract.get("assumptions"))) or _contains_any(delivered_text, _ASSUMPTION_REVIEW_TERMS)
    if has_assumption and not assumptions_declared and not _contains_any(delivered_text, _SENSITIVITY_REVIEW_TERMS):
        add(
            "missing_assumption_sensitivity",
            category="assumption_sensitivity",
            severity="warning",
            claim="The report includes an inferred or assumed input without a declared sensitivity analysis.",
            recommendation="Run the material plausible alternatives and show whether the decision or ranking changes; otherwise label the assumption as unresolved.",
        )

    is_tournament = _contains_any(text, _TOURNAMENT_REVIEW_TERMS)
    if is_tournament and is_predictive:
        if not _review_item_complete(contract.get("decision_path")) and not _contains_any(delivered_text, _DECISION_PATH_REVIEW_TERMS):
            add(
                "missing_decision_path_visual",
                category="presentation",
                severity="warning",
                claim="A tournament or knockout forecast has no declared bracket/tree decision-path visual.",
                recommendation="Add a bracket or tree that shows each matchup and its advance probability so readers can follow how the final odds are formed.",
            )
        if _contains_any(text, ("match", "goal", "tie")) and not _review_item_complete(contract.get("outcome_distribution")) and not _contains_any(delivered_text, _MATCH_DISTRIBUTION_REVIEW_TERMS):
            add(
                "missing_outcome_distribution",
                category="presentation",
                severity="info",
                claim="The forecast discusses match-level outcomes without a declared scoreline or outcome-distribution view.",
                recommendation="Show the leading scorelines, draw/shootout probability, or a compact outcome heatmap for the decision-relevant matches.",
            )

    references = registry.get("references", []) if isinstance(registry.get("references"), list) else []
    unresolved = _unresolved_evidence_refs([], target_map, references)
    if unresolved:
        add(
            "unresolved_evidence_anchors",
            category="evidence",
            severity="warning",
            claim="One or more supplied evidence references are not registered as present report targets.",
            recommendation="Register each local evidence target with a stable id and kind, or replace it with a stable external reference; do not invent an anchor.",
            evidence=unresolved[:20],
        )

    runtime = clean_text(contract.get("export_runtime") or contract.get("runtime") or "").lower()
    if runtime in {"cdn", "remote", "external"}:
        add(
            "external_runtime_dependency",
            category="export",
            severity="required",
            claim="The report declares a remote runtime even though DataClaw artifacts must remain self-contained.",
            recommendation="Keep Plotly in the local/artifact runtime and reduce the report payload or export size without adding a CDN dependency.",
        )

    return {
        "review_schema": 1,
        "mode": mode or ("predictive" if is_predictive else "general"),
        "status": "attention_required" if findings else "pass",
        "findings": findings,
        "guardrail": "Findings identify missing declared work; they do not assert that an uninspected analysis is wrong.",
    }


def _review_item_complete(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, str):
        return clean_text(value).lower() in {"complete", "completed", "done", "pass", "passed", "validated", "included"}
    if isinstance(value, dict):
        status = clean_text(value.get("status") or "").lower()
        if status in {"complete", "completed", "done", "pass", "passed", "validated", "included"}:
            return True
        return any(bool(value.get(key)) for key in ("method", "evidence", "result", "path", "summary"))
    return bool(value) if isinstance(value, (list, tuple, set)) else False


def _baseline_review_complete(value: Any, target_map: dict[str, dict[str, Any]]) -> bool:
    """Require concrete, registered proof for the publish-blocking baseline check.

    A mention of "baseline" in prose or a bare ``status: complete`` is only a
    declaration.  The contract must identify a completed comparison, explain
    its method and result, and point to a target already registered in the
    report inputs.  This remains a completeness check, not an attempt to
    independently re-run or certify the model.
    """
    if not isinstance(value, dict):
        return False
    status = clean_text(value.get("status") or "").lower()
    if status not in {"complete", "completed", "done", "pass", "passed", "validated", "included"}:
        return False
    if not clean_text(value.get("method") or "") or not clean_text(value.get("result") or value.get("summary") or ""):
        return False
    evidence = value.get("evidence", value.get("evidence_refs"))
    references = _evidence_refs_from_value(evidence)
    return (
        bool(references)
        and all(reference["kind"] != "unknown" for reference in references)
        and not _unresolved_evidence_refs([], target_map, references)
    )


def _storyboard_review_text(storyboard: dict[str, Any], *, include_context: bool = True) -> str:
    """Collect prose fields only; numerical arrays and figure payloads are excluded."""
    prose_keys = {
        "title", "report_goal", "subtitle", "detail", "summary", "interpretation",
        "conclusion", "caption", "dek", "kicker", "text", "note", "description",
        "label", "name", "assumption", "method", "status",
    }
    chunks: list[str] = []

    def walk(value: Any, key: str = "") -> None:
        if isinstance(value, dict):
            for child_key, child in value.items():
                walk(child, str(child_key))
        elif isinstance(value, list):
            for child in value:
                walk(child, key)
        elif isinstance(value, str) and key in prose_keys:
            text = clean_text(value)
            if text:
                chunks.append(text)

    source = {
        "section_plan": storyboard.get("section_plan", []),
        "analysis_contract": storyboard.get("analysis_contract", {}),
    }
    if include_context:
        source = {
            "title": storyboard.get("title"),
            "report_goal": storyboard.get("report_goal"),
            **source,
        }
    walk(source)
    return " ".join(chunks).lower()


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _chart_theme_failures(sections: list[dict[str, Any]]) -> list[dict[str, str]]:
    failures: list[dict[str, str]] = []
    for section in sections:
        payload = section.get("payload") if isinstance(section.get("payload"), dict) else {}
        figure = payload.get("figure")
        if not isinstance(figure, dict):
            continue
        layout = figure.get("layout") if isinstance(figure.get("layout"), dict) else {}
        styled_keys = [key for key in ("template", "paper_bgcolor", "plot_bgcolor", "colorway") if layout.get(key)]
        font = layout.get("font") if isinstance(layout.get("font"), dict) else {}
        if font.get("color"):
            styled_keys.append("font.color")
        if styled_keys:
            failures.append({
                "section_id": clean_text(section.get("section_id") or ""),
                "keys": ", ".join(styled_keys),
            })
    return failures


def _external_asset_refs(doc: str) -> list[str]:
    refs: list[str] = []
    patterns = (
        r"<script[^>]+\bsrc=[\"']([^\"']+)",
        r"<link[^>]+\bhref=[\"']([^\"']+)",
        r"<(?:img|iframe|video|audio|object)[^>]+\bsrc=[\"']([^\"']+)",
    )
    for pattern in patterns:
        refs.extend(match.group(1) for match in re.finditer(pattern, doc, re.IGNORECASE))
    return [ref for ref in refs if re.match(r"(?:https?:)?//", ref)]


def _runtime_smoke_failures(doc: str, sections: list[dict[str, Any]]) -> list[dict[str, str]]:
    failures: list[dict[str, str]] = []
    if REPORT_SHELL_SCRIPT_ATTR not in doc:
        failures.append({"check": "report_shell_script", "detail": "missing report runtime script"})

    target_ids = set(re.findall(r"\bid=[\"']([^\"']+)[\"']", doc, re.IGNORECASE))
    target_ids.update(re.findall(r"\bdata-dc-section-id=[\"']([^\"']+)[\"']", doc, re.IGNORECASE))
    for anchor in re.findall(r"<a\b[^>]*\bhref=[\"']#([^\"']+)[\"']", doc, re.IGNORECASE):
        if anchor not in target_ids:
            failures.append({"check": "anchor_target", "detail": f"missing target #{anchor}"})

    for section in sections:
        kind = clean_text(section.get("kind") or "")
        section_id = clean_text(section.get("section_id") or "")
        if kind in CHART_SECTION_KINDS and "r-chart-target" not in doc:
            failures.append({"check": "chart_target", "detail": f"{section_id or kind} has no chart mount"})
        if kind in INTERACTIVE_SECTION_KINDS and "data-dc-control-bar" not in doc:
            failures.append({"check": "interactive_controls", "detail": f"{section_id or kind} has no control mount"})
    return failures


def _contrast_failures(doc: str) -> list[dict[str, Any]]:
    """Check the shell's primary light/dark foreground pairs without a browser."""
    styles = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", doc, re.IGNORECASE | re.DOTALL))
    if not styles:
        return [{"pair": "shell", "detail": "no inline report token stylesheet"}]

    scopes = [styles]
    dark_match = re.search(r":root\[data-theme=[\"']dark[\"']\]\s*\{(.*?)\}", styles, re.DOTALL)
    if dark_match:
        scopes.append(dark_match.group(1))
    failures: list[dict[str, Any]] = []
    for index, scope in enumerate(scopes):
        ink = _css_hex_token(scope, "dc-ink") or _css_hex_token(styles, "dc-ink")
        surface = _css_hex_token(scope, "dc-surface") or _css_hex_token(styles, "dc-surface")
        muted = _css_hex_token(scope, "dc-muted") or _css_hex_token(styles, "dc-muted")
        if not ink or not surface or not muted:
            failures.append({"pair": "tokens", "detail": "missing dc-ink, dc-muted, or dc-surface color token"})
            continue
        for label, foreground, required in (("ink/surface", ink, 4.5), ("muted/surface", muted, 4.5)):
            ratio = _contrast_ratio(foreground, surface)
            if ratio < required:
                failures.append({"theme": "dark" if index else "light", "pair": label, "ratio": round(ratio, 2), "required": required})
    return failures


def _css_hex_token(css: str, token: str) -> str:
    match = re.search(rf"--{re.escape(token)}\s*:\s*(#[0-9a-fA-F]{{6}})", css)
    return match.group(1) if match else ""


def _contrast_ratio(first: str, second: str) -> float:
    def luminance(value: str) -> float:
        channels = [int(value[index:index + 2], 16) / 255 for index in (1, 3, 5)]
        adjusted = [channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4 for channel in channels]
        return 0.2126 * adjusted[0] + 0.7152 * adjusted[1] + 0.0722 * adjusted[2]

    high, low = sorted((luminance(first), luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


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
    max_design_passes: int = 5,
) -> dict[str, Any]:
    """Create a cohesive report plan from completed insights and analysis assets.

    The initial plan preserves every supplied insight and analysis object. A
    bounded design-refinement pass then improves adjacency, local data notes,
    and chart interpretation using only supplied material; it never invents a
    conclusion, caveat, or analytical result.
    """
    requirements = requirements or {}
    analysis_contract = requirements.get("analysis_review", {})
    if not isinstance(analysis_contract, dict):
        raise ValueError("requirements.analysis_review must be a dictionary when supplied")
    analysis_contract = dict(analysis_contract)
    if "assumptions" not in analysis_contract and isinstance(requirements.get("assumptions"), list):
        analysis_contract["assumptions"] = requirements["assumptions"]
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
            "kicker": "At a glance",
            "metrics": metrics[:5],
        })

    # Plan the evidence sections first so insights can anchor to them.
    planned_analyses: list[dict[str, Any]] = []
    hero_assigned = False
    for index, analysis in enumerate(normalized_analyses):
        planned = _storyboard_section_from_analysis(analysis, index)
        if not planned:
            continue
        planned["data"]["section_id"] = f"sec-evidence-{index + 1}"
        planned["data"].setdefault("kicker", f"Evidence {index + 1:02d}")
        if not hero_assigned and planned["section_type"] in (CHART_SECTION_KINDS | INTERACTIVE_SECTION_KINDS):
            planned["data"]["emphasis"] = "hero"
            hero_assigned = True
        planned_analyses.append(planned)

    paired_insights = [_storyboard_insight_item(item, i) for i, item in enumerate(normalized_insights[:7])]
    _pair_insights_with_evidence(paired_insights, planned_analyses)

    readout = _storyboard_readout(clean_goal, normalized_insights)
    add("narrative_band", "executive_readout", "State the answer before the reader reaches supporting evidence.", {
        "title": requirements.get("readout_title", "The answer"),
        "kicker": "Executive readout",
        "summary": readout,
        "bullets": [
            _readout_bullet(item)
            for item in normalized_insights[1:4]
            if _readout_bullet(item)
        ],
    })

    if paired_insights:
        add("insight_grid", "primary_insights", "Separate the material conclusions from the notebook execution trail.", {
            "title": requirements.get("insights_title", "Primary insights"),
            "kicker": "What changed",
            "section_id": "sec-primary-insights",
            "caption": "Findings promoted from completed analysis with evidence, caveats, and next actions where available.",
            "items": paired_insights,
        })

    for planned in planned_analyses:
        add(planned["section_type"], planned["layout_role"], planned["rationale"], planned["data"])

    methodology = requirements.get("methodology") or requirements.get("methods") or _collect_named_items(normalized_analyses, "methodology")
    if methodology:
        methods = methodology if isinstance(methodology, list) else [{"title": "Analysis method", "detail": methodology}]
        add("methodology_block", "methodology", "Show grain, denominator, validation, and assumptions after the evidence.", {
            "title": requirements.get("methodology_title", "Methodology"),
            "kicker": "Method & trust",
            "methods": methods,
            "checks": requirements.get("checks", []),
        })

    hypotheses = requirements.get("hypotheses", [])
    if isinstance(hypotheses, list) and hypotheses:
        add("hypothesis_ledger", "hypothesis_dispositions", "Show how the analysis moved from open questions to dispositions.", {
            "title": requirements.get("hypothesis_title", "Hypothesis ledger"),
            "kicker": "Method & trust",
            "hypotheses": hypotheses,
        })

    evidence = _storyboard_evidence(normalized_insights, normalized_analyses)
    if evidence:
        add("evidence_trace", "evidence_trace", "Make report claims traceable back to notebook cells, filters, and artifacts.", {
            "title": requirements.get("evidence_title", "Evidence trace"),
            "kicker": "Provenance",
            "evidence": evidence,
        })

    interaction_plan = _storyboard_interactions(section_plan)
    storyboard_steps = [
        {"phase": "readout", "purpose": "Answer the report goal in one screen.", "sections": ["opening_context", "executive_kpis", "executive_readout"]},
        {"phase": "insights", "purpose": "Promote only decision-changing findings.", "sections": ["primary_insights"]},
        {"phase": "evidence", "purpose": "Pair visuals, controls, tables, and interpretation.", "sections": [item["layout_role"] for item in section_plan if item["layout_role"].startswith("analysis_")]},
        {"phase": "trust", "purpose": "Close with methodology, hypothesis dispositions, and evidence trace.", "sections": ["methodology", "hypothesis_dispositions", "evidence_trace"]},
    ]

    editorial_architecture = _apply_editorial_architecture(section_plan, requirements)
    if editorial_architecture["archetype"] in {"taxonomy_explorer", "guided_explorer"}:
        storyboard_steps = editorial_architecture["narrative_acts"]
        interaction_plan = _storyboard_interactions(section_plan)

    storyboard = {
        "storyboard_schema": 1,
        "title": title,
        "report_goal": clean_goal,
        "audience": clean_audience,
        "designer": {
            "mode": "whole_report",
            "note": "Render from this storyboard after analysis is complete; do not rely on incremental report-cell appends for the final artifact.",
        },
        "storyboard": storyboard_steps,
        "editorial_architecture": editorial_architecture,
        "layout_plan": _storyboard_layout(section_plan),
        "interaction_plan": interaction_plan,
        "data_contract": {
            "policy": "Embed aggregate, ranked, or sampled payloads only. Do not fetch live data or embed raw full datasets.",
            "interactive_section_kinds": sorted(INTERACTIVE_SECTION_KINDS),
        },
        "intake": {
            "methodology": requirements.get("methodology") or requirements.get("methods") or [],
            "checks": requirements.get("checks") or [],
        },
        "source_context": {
            "insights": copy.deepcopy(normalized_insights),
            "analyses": copy.deepcopy(normalized_analyses),
            "requirements": copy.deepcopy(requirements),
        },
        "analysis_contract": analysis_contract,
        "evidence_registry": requirements.get("evidence_registry", requirements.get("evidence_targets", [])),
        "quality_plan": {
            "gate": "run before publish",
            "rubric_version": rubric_version(),
            "checks": live_criterion_ids(),
        },
        "section_plan": section_plan,
    }
    return _refine_storyboard_design(storyboard, max_passes=max_design_passes)


def _editorial_role(item: dict[str, Any]) -> str:
    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    return clean_text(data.get("editorial_role") or data.get("story_role") or "").lower().replace("-", "_")


def _editorial_priority(item: dict[str, Any], index: int) -> tuple[int, float, int]:
    """Return a stable, caller-overridable ranking for visual prominence."""
    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    role = _editorial_role(item)
    explicit_hero = role == "hero" or data.get("hero") is True
    inherited_hero = clean_text(data.get("emphasis") or "") == "hero"
    has_priority = "story_priority" in data or "layout_priority" in data
    raw_priority = data.get("story_priority", data.get("layout_priority", 10_000))
    try:
        priority = float(raw_priority)
    except (TypeError, ValueError):
        priority = 10_000.0
    return (0 if explicit_hero else 1 if has_priority else 2 if inherited_hero else 3, priority, index)


def _diagnostic_group(item: dict[str, Any]) -> str:
    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    return clean_text(
        data.get("diagnostic_group")
        or data.get("comparison_group")
        or data.get("story_group")
        or ""
    )


def _materialize_taxonomy_card_grid(
    section_plan: list[dict[str, Any]], analyses: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Use supplied selector items as orientation cards without losing the explorer.

    Item-shaped inputs commonly infer a selector panel because they carry
    filterable fields such as team or archetype.  A taxonomy report needs both
    a scan-friendly category introduction and that later explorer.  This adds a
    card-grid *view* of the same supplied aggregate items while preserving the
    selector as the interactive payoff.
    """
    existing = next(
        (item for item in analyses if clean_text(item.get("section_type") or "") == "entity_card_grid"),
        None,
    )
    if existing:
        return existing
    selector = next(
        (
            item for item in analyses
            if clean_text(item.get("section_type") or "") == "selector_panel"
            and isinstance((item.get("data") or {}).get("items"), list)
            and (item.get("data") or {}).get("items")
        ),
        None,
    )
    if not selector:
        return None

    source_data = selector.get("data") if isinstance(selector.get("data"), dict) else {}
    source_role = clean_text(selector.get("layout_role") or "analysis_taxonomy")
    source_id = clean_text(source_data.get("section_id") or source_role)
    cards_data = copy.deepcopy(source_data)
    cards_data["section_id"] = f"{source_id}-taxonomy"
    cards_data["derived_from_section"] = source_role
    cards_data["editorial_role"] = "taxonomy"
    cards_data["layout_variant"] = "category_taxonomy"
    cards_data["card_style"] = "categorical_accents"
    cards_data.setdefault("kicker", "The taxonomy")
    cards = {
        "section_type": "entity_card_grid",
        "layout_role": f"{source_role}_taxonomy_cards",
        "rationale": "Use the supplied selector items as category cards before the reader reaches the detailed explorer.",
        "data": cards_data,
    }
    section_plan.append(cards)
    analyses.append(cards)
    return cards


def _selector_panel_looks_taxonomic(analyses: list[dict[str, Any]]) -> bool:
    category_keys = {"archetype", "category", "segment", "persona", "cluster", "cohort", "type"}
    for item in analyses:
        if clean_text(item.get("section_type") or "") != "selector_panel":
            continue
        data = item.get("data") if isinstance(item.get("data"), dict) else {}
        items = data.get("items")
        if not isinstance(items, list):
            continue
        keys = {
            clean_text(key).lower()
            for entry in items if isinstance(entry, dict)
            for key in entry
        }
        if keys & category_keys:
            return True
    return False


def _apply_editorial_architecture(
    section_plan: list[dict[str, Any]], requirements: dict[str, Any],
) -> dict[str, Any]:
    """Apply an editorial page grammar when the supplied assets support one.

    The taxonomy/explorer sequence is intentionally structural rather than a
    cosmetic afterthought: it changes the order in which the reader encounters
    classification, evidence, interpretation, and interaction.  It only
    rearranges supplied sections and carries the existing readout into the
    header; it does not manufacture an analytical result.
    """
    requested = clean_text(
        requirements.get("editorial_archetype") or requirements.get("report_archetype") or "auto"
    ).lower().replace("-", "_").replace(" ", "_")
    analyses = [
        item for item in section_plan
        if isinstance(item, dict) and clean_text(item.get("layout_role") or "").startswith("analysis_")
    ]
    has_visual = any(
        clean_text(item.get("section_type") or "") in CHART_SECTION_KINDS
        and clean_text(item.get("section_type") or "") not in INTERACTIVE_SECTION_KINDS
        for item in analyses
    )
    has_interaction = any(clean_text(item.get("section_type") or "") in INTERACTIVE_SECTION_KINDS for item in analyses)
    requested_taxonomy = requested in {"taxonomy_explorer", "taxonomy", "archetype_explorer"}
    requested_guided = requested in {"guided_argument", "guided_explorer", "editorial"}
    existing_taxonomy = next(
        (item for item in analyses if clean_text(item.get("section_type") or "") == "entity_card_grid"),
        None,
    )
    taxonomy = existing_taxonomy or (
        _materialize_taxonomy_card_grid(section_plan, analyses)
        if has_visual and has_interaction and (requested_taxonomy or (requested in {"", "auto"} and _selector_panel_looks_taxonomic(analyses)))
        else None
    )
    has_taxonomy = taxonomy is not None
    use_taxonomy = (requested_taxonomy or requested in {"", "auto"}) and has_taxonomy and has_visual and has_interaction
    use_guided = not use_taxonomy and (requested_guided or requested in {"", "auto"}) and has_visual and has_interaction

    if not (use_taxonomy or use_guided):
        reason = (
            "The supplied asset set does not contain the taxonomy, visual evidence, and interactive explorer "
            "needed for the taxonomy_explorer sequence."
            if requested_taxonomy else
            "Use the standard whole-report sequence for this asset set."
        )
        return {
            "archetype": "standard",
            "requested": requested or "auto",
            "reason": reason,
            "guardrail": "The architecture may reorder supplied sections but never creates analytical claims or evidence.",
            "narrative_acts": [],
        }

    # The architecture may be re-applied during critique after a caller edits a
    # plan. Remove only its generated epilogue here, after confirming an
    # editorial archetype applies, so repair remains idempotent without
    # changing a standard report.
    section_plan[:] = [
        item for item in section_plan
        if not isinstance(item, dict) or clean_text(item.get("layout_role") or "") != "report_epilogue"
    ]

    by_role = {
        clean_text(item.get("layout_role") or ""): item
        for item in section_plan if isinstance(item, dict)
    }
    header = by_role.get("opening_context")
    metrics = by_role.get("executive_kpis")
    readout = by_role.get("executive_readout")
    findings = by_role.get("primary_insights")
    trust = [
        by_role[role] for role in ("methodology", "hypothesis_dispositions", "evidence_trace")
        if by_role.get(role)
    ]

    interactive = [
        item for item in analyses
        if item is not taxonomy and clean_text(item.get("section_type") or "") in INTERACTIVE_SECTION_KINDS
    ]
    static_visuals = [item for item in analyses
        if item is not taxonomy
        and item not in interactive
        and clean_text(item.get("section_type") or "") in CHART_SECTION_KINDS
    ]
    indexed_visuals = list(enumerate(static_visuals))
    indexed_visuals.sort(key=lambda pair: _editorial_priority(pair[1], pair[0]))
    ordered_visuals = [item for _, item in indexed_visuals]
    hero_visual = ordered_visuals[0] if ordered_visuals else None
    diagnostics = ordered_visuals[1:] if hero_visual else ordered_visuals[:]
    pair_group = ""
    for candidate in diagnostics:
        candidate_group = _diagnostic_group(candidate)
        if candidate_group and sum(1 for item in diagnostics if _diagnostic_group(item) == candidate_group) >= 2:
            pair_group = candidate_group
            break
    if pair_group:
        paired = [item for item in diagnostics if _diagnostic_group(item) == pair_group][:2]
        diagnostics = paired + [item for item in diagnostics if item not in paired]
    else:
        paired = diagnostics[:2]
    # The generic planner may have promoted the first chart *or interactive*
    # analysis before this architecture had enough context. Keep exactly one
    # visual hero once the editorial sequence is known.
    for candidate in analyses:
        candidate_data = candidate.get("data") if isinstance(candidate.get("data"), dict) else {}
        if candidate is not hero_visual and clean_text(candidate_data.get("emphasis") or "") == "hero":
            candidate_data.pop("emphasis", None)
            candidate["data"] = candidate_data
    consumed = {id(item) for item in [taxonomy, hero_visual, *diagnostics, *interactive] if item is not None}
    remaining_evidence = [item for item in analyses if id(item) not in consumed]

    if header:
        header_data = header.setdefault("data", {})
        header_data["visual_treatment"] = "editorial_dark"
        if readout:
            readout_data = readout.get("data") if isinstance(readout.get("data"), dict) else {}
            header_data["absorbed_readout"] = copy.deepcopy(readout_data)
            if not clean_text(header_data.get("abstract") or ""):
                header_data["abstract"] = clean_text(readout_data.get("summary") or "")
    if metrics:
        metrics.setdefault("data", {})["layout_variant"] = "floating_kpis"
    if taxonomy:
        taxonomy_data = taxonomy.setdefault("data", {})
        taxonomy_data["layout_variant"] = "category_taxonomy"
        taxonomy_data["card_style"] = "categorical_accents"
        taxonomy_data.setdefault("kicker", "The taxonomy")
    if hero_visual:
        hero_data = hero_visual.setdefault("data", {})
        hero_data["emphasis"] = "hero"
        hero_data["layout_variant"] = "hero_visual"
        hero_data["hero_selection"] = (
            "explicit" if _editorial_role(hero_visual) == "hero" or hero_data.get("hero") is True
            else "priority" if hero_data.get("story_priority", hero_data.get("layout_priority")) is not None
            else "input_order"
        )
        hero_data.setdefault("kicker", "The landscape")
    for index, diagnostic in enumerate(diagnostics):
        diagnostic_data = diagnostic.setdefault("data", {})
        diagnostic_data["layout_variant"] = "diagnostic"
        diagnostic_data.setdefault("kicker", f"Diagnostic {index + 1:02d}")
        if diagnostic in paired:
            diagnostic["layout_group"] = "diagnostic_pair_1"
            diagnostic_data["diagnostic_pair_source"] = "explicit_group" if pair_group else "input_order"
    for item in interactive:
        explorer_data = item.setdefault("data", {})
        explorer_data["layout_variant"] = "reader_explorer"
        explorer_data.setdefault("kicker", "Explore it yourself")
    if findings:
        findings.setdefault("data", {}).setdefault("kicker", "What the evidence says")

    ordered: list[dict[str, Any]] = []
    added: set[int] = set()

    def append(*items: dict[str, Any] | None) -> None:
        for item in items:
            if item is not None and id(item) not in added:
                ordered.append(item)
                added.add(id(item))

    # Orientation → summary → taxonomy → visual evidence → diagnostics →
    # conclusions → reader-led exploration → provenance.
    append(header, metrics, taxonomy if use_taxonomy else None, hero_visual)
    append(*diagnostics, *remaining_evidence, findings, *interactive, *trust)
    for item in section_plan:
        if item is not readout:
            append(item)

    if trust:
        footer_note = clean_text(requirements.get("footer_note") or "")
        append({
            "section_type": "narrative_band",
            "layout_role": "report_epilogue",
            "rationale": "End with the supplied scope, methodology, and provenance rather than another analytical claim.",
            "data": {
                "title": "Notes & provenance",
                "kicker": "Epilogue",
                "summary": footer_note or "See the methodology and evidence trace for scope, assumptions, and source references.",
                "layout_variant": "report_epilogue",
                "semantic_key": "report_epilogue",
            },
        })

    section_plan[:] = ordered
    narrative_acts = [
        {"phase": "orientation", "purpose": "Frame the question before the reader encounters detail.", "sections": ["opening_context"]},
        {"phase": "summary", "purpose": "Anchor the report with the headline KPIs.", "sections": ["executive_kpis"]},
        {"phase": "evidence", "purpose": "Lead with the hero visual and pair diagnostic views in a shared grid.", "sections": [item.get("layout_role") for item in [hero_visual, *diagnostics, *remaining_evidence] if item]},
        {"phase": "findings", "purpose": "State the conclusions after the supporting evidence.", "sections": ["primary_insights"]},
        {"phase": "exploration", "purpose": "Let the reader inspect the supplied aggregate data after the guided argument.", "sections": [item.get("layout_role") for item in interactive]},
        {"phase": "trust", "purpose": "Close with methodology, caveats, and provenance.", "sections": [item.get("layout_role") for item in [*trust] if item] + (["report_epilogue"] if trust else [])},
    ]
    if use_taxonomy:
        narrative_acts.insert(2, {
            "phase": "taxonomy",
            "purpose": "Classify the categories or archetypes before asking the reader to interpret the evidence.",
            "sections": [taxonomy.get("layout_role")] if taxonomy else [],
        })
    return {
        "archetype": "taxonomy_explorer" if use_taxonomy else "guided_explorer",
        "requested": requested or "auto",
        "reason": (
            "The supplied assets include category cards, visual evidence, and a reader-controlled explorer."
            if use_taxonomy else
            "The supplied assets include visual evidence and a reader-controlled explorer."
        ),
        "absorbed_sections": ["executive_readout"],
        "guardrail": "The architecture reorders supplied sections and promotes the supplied readout into the hero; it never creates analytical claims or evidence.",
        "narrative_acts": narrative_acts,
    }


_EDITORIAL_DESIGN_STAGES = (
    "restore_editorial_sequence",
    "complete_visual_hierarchy",
    "anchor_visuals_to_local_context",
    "recheck_evidence_and_explorer_pacing",
    "audit_page_architecture",
)


def _critique_editorial_design(storyboard: dict[str, Any], *, max_passes: int = 5) -> dict[str, Any]:
    """Run bounded page-architecture critique after the storyboard is designed.

    This is deliberately separate from the analytical review. It evaluates the
    reader's path through the supplied material and can make only reversible,
    presentational repairs: reorder existing sections, restore layout metadata,
    and place supplied context next to its visual. Missing assets remain
    findings rather than invented charts, methods, or claims.
    """
    section_plan = storyboard.get("section_plan")
    if not isinstance(section_plan, list):
        return {
            "review_schema": 1,
            "status": "attention_required",
            "findings": [{
                "id": "page_architecture_unavailable",
                "severity": "warning",
                "claim": "The report has no structured section plan to review for page architecture.",
                "recommendation": "Create a storyboard-backed report before requesting editorial critique.",
                "sections": [],
            }],
            "max_passes": 0,
            "passes": 0,
            "stages": [],
            "guardrail": "Design critique never invents content, analysis, or evidence.",
        }

    requirements = storyboard.get("source_context", {}).get("requirements", {})
    if not isinstance(requirements, dict):
        requirements = {}
    architecture = storyboard.get("editorial_architecture")
    architecture = dict(architecture) if isinstance(architecture, dict) else {}
    is_editorial_story = clean_text(architecture.get("archetype") or "") in {"taxonomy_explorer", "guided_explorer"}
    limit = max(1, min(int(max_passes or 5), len(_EDITORIAL_DESIGN_STAGES)))
    stages: list[dict[str, Any]] = []
    repairs: list[dict[str, Any]] = []

    for pass_number, action in enumerate(_EDITORIAL_DESIGN_STAGES[:limit], start=1):
        changed = False
        if action in {"restore_editorial_sequence", "recheck_evidence_and_explorer_pacing"} and is_editorial_story:
            before = copy.deepcopy(section_plan)
            repaired_architecture = _apply_editorial_architecture(section_plan, requirements)
            storyboard["editorial_architecture"] = repaired_architecture
            if repaired_architecture.get("archetype") in {"taxonomy_explorer", "guided_explorer"}:
                storyboard["storyboard"] = repaired_architecture.get("narrative_acts", [])
                storyboard["layout_plan"] = _storyboard_layout(section_plan)
                storyboard["interaction_plan"] = _storyboard_interactions(section_plan)
            is_editorial_story = repaired_architecture.get("archetype") in {"taxonomy_explorer", "guided_explorer"}
            changed = section_plan != before
        elif action == "complete_visual_hierarchy" and is_editorial_story:
            changed = _repair_editorial_hierarchy(section_plan)
        elif action == "anchor_visuals_to_local_context":
            paired = _add_adjacent_story_insights(section_plan)
            noted = _add_local_data_notes(section_plan)
            interpreted = _complete_chart_context_from_adjacent_insights(section_plan)
            changed = paired or noted or interpreted

        stages.append({"pass": pass_number, "action": action, "changed": changed})
        if changed:
            repairs.append({"pass": pass_number, "action": action})

    review = _review_editorial_design(storyboard)
    review.update({
        "max_passes": limit,
        "passes": limit,
        "stages": stages,
        "repairs": repairs,
        "guardrail": "Design critique may only reorder supplied sections or restore presentation and local context; it never invents content, analysis, or evidence.",
    })
    return review


def _repair_editorial_hierarchy(section_plan: list[dict[str, Any]]) -> bool:
    """Restore existing taxonomy/explorer hierarchy metadata without new prose."""
    changed = False
    by_role = {
        clean_text(item.get("layout_role") or ""): item
        for item in section_plan if isinstance(item, dict)
    }
    header = by_role.get("opening_context")
    if header:
        data = header.get("data") if isinstance(header.get("data"), dict) else {}
        if clean_text(data.get("visual_treatment") or "") != "editorial_dark":
            data["visual_treatment"] = "editorial_dark"
            changed = True
        if not clean_text(data.get("abstract") or "") and isinstance(data.get("absorbed_readout"), dict):
            abstract = clean_text(data["absorbed_readout"].get("summary") or "")
            if abstract:
                data["abstract"] = abstract
                changed = True
        header["data"] = data

    metrics = by_role.get("executive_kpis")
    if metrics:
        data = metrics.get("data") if isinstance(metrics.get("data"), dict) else {}
        if clean_text(data.get("layout_variant") or "") != "floating_kpis":
            data["layout_variant"] = "floating_kpis"
            metrics["data"] = data
            changed = True

    for item in section_plan:
        if not isinstance(item, dict):
            continue
        section_type = clean_text(item.get("section_type") or "")
        data = item.get("data") if isinstance(item.get("data"), dict) else {}
        if section_type == "entity_card_grid":
            if clean_text(data.get("layout_variant") or "") != "category_taxonomy":
                data["layout_variant"] = "category_taxonomy"
                changed = True
            if clean_text(data.get("card_style") or "") != "categorical_accents":
                data["card_style"] = "categorical_accents"
                changed = True
        elif clean_text(data.get("layout_variant") or "") == "hero_visual":
            if clean_text(data.get("emphasis") or "") != "hero":
                data["emphasis"] = "hero"
                changed = True
        item["data"] = data
    return changed


def _review_editorial_design(storyboard: dict[str, Any]) -> dict[str, Any]:
    """Return non-fabricating findings about the rendered story structure."""
    section_plan = storyboard.get("section_plan")
    section_plan = section_plan if isinstance(section_plan, list) else []
    architecture = storyboard.get("editorial_architecture")
    architecture = architecture if isinstance(architecture, dict) else {}
    archetype = clean_text(architecture.get("archetype") or "standard")
    findings: list[dict[str, Any]] = []

    def add(
        finding_id: str,
        *,
        severity: str,
        claim: str,
        recommendation: str,
        sections: list[str] | None = None,
    ) -> None:
        findings.append({
            "id": finding_id,
            "severity": severity,
            "claim": claim,
            "recommendation": recommendation,
            "sections": sections or [],
        })

    indexed = [item for item in section_plan if isinstance(item, dict)]
    roles = [clean_text(item.get("layout_role") or "") for item in indexed]

    def position(role: str) -> int | None:
        try:
            return roles.index(role)
        except ValueError:
            return None

    def data_at(role: str) -> dict[str, Any]:
        index = position(role)
        if index is None:
            return {}
        value = indexed[index].get("data")
        return value if isinstance(value, dict) else {}

    def item_data(item: dict[str, Any]) -> dict[str, Any]:
        value = item.get("data")
        return value if isinstance(value, dict) else {}

    visual_sections = [
        item for item in indexed
        if clean_text(item.get("section_type") or "") in CHART_SECTION_KINDS
    ]
    contextless_visuals = []
    unevidenced_guided_visuals = []
    for item in visual_sections:
        data = item_data(item)
        section_type = clean_text(item.get("section_type") or "")
        variant = clean_text(data.get("layout_variant") or "")
        has_caption = bool(clean_text(data.get("caption") or data.get("dek") or ""))
        has_interpretation = bool(clean_text(data.get("interpretation") or data.get("conclusion") or data.get("insight") or ""))
        has_note = bool(clean_text(data.get("data_note") or ""))
        guided_visual = variant in {"hero_visual", "diagnostic"} or section_type in {"chart", "chart_interpretation"}
        if not (has_caption and (has_interpretation if guided_visual else (has_interpretation or has_note))):
            contextless_visuals.append(clean_text(item.get("layout_role") or ""))
        if guided_visual and not _evidence_ref_keys(data):
            unevidenced_guided_visuals.append(clean_text(item.get("layout_role") or ""))
    if contextless_visuals:
        add(
            "visual_context_incomplete",
            severity="warning",
            claim="One or more visual sections lack a local caption plus interpretation or data note.",
            recommendation="Supply a concise interpretation and caveat, or retain the local data note; do not make the reader infer the conclusion from a chart alone.",
            sections=contextless_visuals,
        )
    if unevidenced_guided_visuals:
        add(
            "guided_visual_evidence_missing",
            severity="warning",
            claim="One or more guided visuals make an interpretation without a supplied evidence reference.",
            recommendation="Attach the completed analysis cell, artifact, or finding reference to each hero and diagnostic visual; do not rely on a chart title as evidence.",
            sections=unevidenced_guided_visuals,
        )

    if archetype not in {"taxonomy_explorer", "guided_explorer"}:
        return {
            "review_schema": 1,
            "archetype": archetype,
            "status": "attention_required" if findings else "pass",
            "findings": findings,
        }

    is_taxonomy_explorer = archetype == "taxonomy_explorer"
    header = data_at("opening_context")
    if clean_text(header.get("visual_treatment") or "") != "editorial_dark" or not clean_text(header.get("abstract") or ""):
        add(
            "hero_hierarchy_incomplete",
            severity="warning",
            claim="The editorial hero is missing its dark hierarchy treatment or supplied explanatory abstract.",
            recommendation="Keep the kicker, title, and supplied abstract together in the hero before the report body.",
            sections=["opening_context"],
        )

    metric_position = position("executive_kpis")
    if metric_position is None:
        add(
            "headline_kpis_unavailable",
            severity="info",
            claim="The editorial story has no supplied metric row to bridge the hero and the body.",
            recommendation="Provide two to five decision-relevant aggregate metrics when they exist; do not invent headline numbers.",
            sections=[],
        )
    elif clean_text(data_at("executive_kpis").get("layout_variant") or "") != "floating_kpis":
        add(
            "kpi_continuity_missing",
            severity="warning",
            claim="The supplied KPI row is not visually connected to the hero.",
            recommendation="Use the floating KPI layout so the reader moves from orientation into the report body without a hard visual break.",
            sections=["executive_kpis"],
        )

    taxonomy_index = next(
        (index for index, item in enumerate(indexed) if clean_text(item.get("section_type") or "") == "entity_card_grid"),
        None,
    )
    hero_index = next(
        (index for index, item in enumerate(indexed)
         if clean_text(item_data(item).get("layout_variant") or "") == "hero_visual"),
        None,
    )
    finding_index = position("primary_insights")
    explorer_indices = [
        index for index, item in enumerate(indexed)
        if clean_text(item_data(item).get("layout_variant") or "") == "reader_explorer"
    ]
    evidence_indices = [
        index for index, item in enumerate(indexed)
        if clean_text(item.get("layout_role") or "").startswith("analysis_")
        and clean_text(item_data(item).get("layout_variant") or "") != "reader_explorer"
    ]

    if hero_index is None:
        add(
            "hero_visual_missing",
            severity="warning",
            claim="The declared editorial story is missing a dedicated hero visualization.",
            recommendation="Provide a non-interactive visual for the central argument or use the standard report sequence instead of declaring this archetype.",
            sections=[],
        )
    elif is_taxonomy_explorer and taxonomy_index is None:
        add(
            "taxonomy_missing",
            severity="warning",
            claim="The declared taxonomy/explorer story is missing category cards.",
            recommendation="Provide category cards or an archetype selector with supplied items, or use the guided explorer archetype.",
            sections=[],
        )
    elif is_taxonomy_explorer and not (taxonomy_index < hero_index):
        add(
            "taxonomy_precedes_evidence_broken",
            severity="warning",
            claim="The category system no longer appears before the hero evidence visual.",
            recommendation="Restore the taxonomy → hero visualization order so readers know how to interpret the evidence.",
            sections=[roles[taxonomy_index], roles[hero_index]],
        )

    diagnostics = [
        item for item in indexed
        if clean_text(item_data(item).get("layout_variant") or "") == "diagnostic"
    ]
    if len(diagnostics) >= 2:
        first_two = diagnostics[:2]
        first_roles = [clean_text(item.get("layout_role") or "") for item in first_two]
        groups = [clean_text(item.get("layout_group") or "") for item in first_two]
        positions = [roles.index(role) for role in first_roles]
        if not groups[0] or groups[0] != groups[1] or positions[1] != positions[0] + 1:
            add(
                "diagnostic_pair_unresolved",
                severity="warning",
                claim="The first two diagnostic views are not a contiguous, shared visual comparison.",
                recommendation="Pair the diagnostics in one two-column group so their contrast is visible without scrolling between them.",
                sections=first_roles,
            )
        pair_source = clean_text(item_data(first_two[0]).get("diagnostic_pair_source") or "")
        if pair_source == "input_order":
            add(
                "diagnostic_pair_inferred",
                severity="info",
                claim="The diagnostic pair was selected from input order rather than a declared comparison group.",
                recommendation="Set the same diagnostic_group or comparison_group on charts that should be read side by side.",
                sections=first_roles,
            )

    if hero_index is not None:
        hero_source = clean_text(item_data(indexed[hero_index]).get("hero_selection") or "")
        if hero_source == "input_order":
            add(
                "hero_selected_from_input_order",
                severity="info",
                claim="The hero visualization was selected from input order rather than a declared editorial priority.",
                recommendation="Set editorial_role='hero' or a lower story_priority on the visual that should carry the report's central argument.",
                sections=[roles[hero_index]],
            )

    if finding_index is not None and evidence_indices and finding_index < max(evidence_indices):
        add(
            "findings_precede_evidence",
            severity="warning",
            claim="The primary findings appear before the supplied visual evidence is complete.",
            recommendation="Move findings after the hero and diagnostics so the report alternates evidence with interpretation rather than announcing conclusions first.",
            sections=["primary_insights"],
        )

    if explorer_indices and finding_index is not None and min(explorer_indices) < finding_index:
        add(
            "explorer_precedes_conclusions",
            severity="warning",
            claim="The interactive explorer appears before the guided findings.",
            recommendation="Keep the explorer after the evidence and key findings so it becomes the reader's payoff rather than an unframed data dump.",
            sections=[roles[min(explorer_indices)], "primary_insights"],
        )
    elif not explorer_indices:
        add(
            "reader_explorer_missing",
            severity="warning",
            claim="The editorial story has no reader-controlled explorer after its findings.",
            recommendation="Provide an interactive table, selector, or filterable chart from the supplied aggregate data, or use the standard story archetype.",
            sections=[],
        )

    trust_indices = [
        position(role) for role in ("methodology", "hypothesis_dispositions", "evidence_trace", "report_epilogue")
        if position(role) is not None
    ]
    final_content_index = max(explorer_indices + ([finding_index] if finding_index is not None else []) + evidence_indices, default=-1)
    if not trust_indices:
        add(
            "methodology_or_provenance_missing",
            severity="warning",
            claim="The report ends without a supplied methodology, provenance section, or footer note.",
            recommendation="Provide methodology, evidence targets, or a scoped footer note so the report closes with caveat and provenance rather than another analytic claim.",
            sections=[],
        )
    elif min(trust_indices) < final_content_index:
        add(
            "trust_section_precedes_explorer",
            severity="warning",
            claim="Methodology or provenance interrupts the evidence-to-explorer sequence.",
            recommendation="Move methodology and provenance after the reader explorer to preserve the report's guided pacing.",
            sections=[roles[index] for index in trust_indices],
        )

    return {
        "review_schema": 1,
        "archetype": archetype,
        "status": "attention_required" if any(item["severity"] == "warning" for item in findings) else "pass",
        "findings": findings,
    }


def review_storyboard_design(storyboard: dict[str, Any]) -> dict[str, Any]:
    """Re-evaluate the current storyboard architecture without mutating it."""
    return _review_editorial_design(storyboard)


def _refine_storyboard_design(storyboard: dict[str, Any], *, max_passes: int = 5) -> dict[str, Any]:
    """Run bounded, non-fabricating layout refinement over a complete plan."""
    working = copy.deepcopy(storyboard)
    section_plan = working.get("section_plan")
    if not isinstance(section_plan, list):
        return working
    limit = max(1, min(int(max_passes or 5), 5))
    applied: list[dict[str, Any]] = []
    pass_labels = (
        "pair_insights_with_evidence",
        "place_local_data_notes",
        "complete_chart_context_from_supplied_findings",
        "apply_visual_emphasis_plan",
        "final_context_coverage_check",
    )

    for pass_number in range(1, limit + 1):
        action = pass_labels[pass_number - 1]
        changed = False
        if action == "pair_insights_with_evidence":
            changed = _add_adjacent_story_insights(section_plan)
        elif action == "place_local_data_notes":
            changed = _add_local_data_notes(section_plan)
        elif action == "complete_chart_context_from_supplied_findings":
            changed = _complete_chart_context_from_adjacent_insights(section_plan)
        elif action == "apply_visual_emphasis_plan":
            changed = _apply_visual_emphasis_plan(section_plan)
        if changed:
            applied.append({"pass": pass_number, "action": action})

    working["design_iterations"] = {
        "max_passes": limit,
        "passes": limit,
        "applied": applied,
        "guardrail": "Design refinement may reorganize and annotate supplied context, but never creates analytical claims or evidence.",
    }
    working["source_context"] = {
        "insights": copy.deepcopy(working.get("source_context", {}).get("insights", [])),
        "analyses": copy.deepcopy(working.get("source_context", {}).get("analyses", [])),
        "requirements": copy.deepcopy(working.get("source_context", {}).get("requirements", {})),
    }
    return working


def _add_adjacent_story_insights(section_plan: list[dict[str, Any]]) -> bool:
    insight_section = next(
        (
            item for item in section_plan
            if isinstance(item, dict) and item.get("layout_role") == "primary_insights"
        ),
        None,
    )
    insight_data = insight_section.get("data", {}) if isinstance(insight_section, dict) else {}
    insights = insight_data.get("items", []) if isinstance(insight_data, dict) else []
    if not isinstance(insights, list):
        return False
    by_anchor: dict[str, list[dict[str, Any]]] = {}
    for insight in insights:
        if not isinstance(insight, dict):
            continue
        anchor = clean_text(insight.get("evidence_anchor") or "")
        if not anchor:
            continue
        by_anchor.setdefault(anchor, []).append({
            key: copy.deepcopy(insight[key])
            for key in (
                "title", "detail", "status", "severity", "confidence", "caveat",
                "limitation", "next_action", "action", "metrics", "evidence_anchor",
            )
            if key in insight
        })
    changed = False
    for planned in section_plan:
        if not isinstance(planned, dict):
            continue
        data = planned.get("data") if isinstance(planned.get("data"), dict) else {}
        section_id = clean_text(data.get("section_id") or "")
        adjacent = by_anchor.get(section_id, [])
        if adjacent and data.get("adjacent_insights") != adjacent[:2]:
            data["adjacent_insights"] = adjacent[:2]
            planned["data"] = data
            changed = True
    return changed


def _add_local_data_notes(section_plan: list[dict[str, Any]]) -> bool:
    changed = False
    for planned in section_plan:
        if not isinstance(planned, dict):
            continue
        data = planned.get("data") if isinstance(planned.get("data"), dict) else {}
        if clean_text(data.get("data_note") or ""):
            continue
        records = data.get("records", data.get("rows"))
        if isinstance(records, list):
            data["data_note"] = (
                f"Data note: {len(records):,} supplied aggregate row{'s' if len(records) != 1 else ''}; "
                "use the local controls or table to inspect the underlying slice."
            )
        elif isinstance(data.get("figure"), dict) or data.get("figure_json"):
            data["data_note"] = "Data note: interactive figure supplied from the completed analysis; hover for the plotted values."
        else:
            continue
        planned["data"] = data
        changed = True
    return changed


def _complete_chart_context_from_adjacent_insights(section_plan: list[dict[str, Any]]) -> bool:
    changed = False
    for planned in section_plan:
        if not isinstance(planned, dict):
            continue
        section_type = clean_text(planned.get("section_type") or "")
        if section_type not in {"chart_interpretation", "filterable_chart", "chart_table_explorer"}:
            continue
        data = planned.get("data") if isinstance(planned.get("data"), dict) else {}
        adjacent = data.get("adjacent_insights", [])
        if not isinstance(adjacent, list) or not adjacent:
            continue
        lead = adjacent[0] if isinstance(adjacent[0], dict) else {}
        section_changed = False
        if not clean_text(data.get("interpretation") or data.get("insight") or data.get("summary") or ""):
            detail = clean_text(lead.get("detail") or "")
            if detail:
                data["interpretation"] = detail
                section_changed = True
        if not clean_text(data.get("caveat") or data.get("limitation") or ""):
            caveat = clean_text(lead.get("caveat") or lead.get("limitation") or "")
            if caveat:
                data["caveat"] = caveat
                section_changed = True
        if section_changed:
            planned["data"] = data
            changed = True
    return changed


def _apply_visual_emphasis_plan(section_plan: list[dict[str, Any]]) -> bool:
    """Add renderable emphasis metadata from supplied hierarchy, without style invention."""
    changed = False
    for planned in section_plan:
        if not isinstance(planned, dict):
            continue
        section_type = clean_text(planned.get("section_type") or "")
        data = planned.get("data") if isinstance(planned.get("data"), dict) else {}
        section_changed = False
        if section_type == "entity_card_grid" and "card_style" not in data:
            data["card_style"] = "categorical_accents"
            section_changed = True
        if section_type in {"chart_interpretation", "filterable_chart", "chart_table_explorer"} and "layout_variant" not in data:
            data["layout_variant"] = "evidence_with_interpretation"
            section_changed = True
        if section_changed:
            planned["data"] = data
            changed = True
    return changed


def render_report_from_storyboard(storyboard: dict[str, Any], *, title: str | None = None) -> str:
    """Render all storyboard sections in one pass."""
    section_plan = storyboard.get("section_plan", [])
    if not isinstance(section_plan, list) or not section_plan:
        raise ValueError("storyboard requires non-empty list 'section_plan'")

    html_sections: list[str] = []
    include_plotly = False
    active_group = ""
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
        group = clean_text(planned.get("layout_group") or "")
        if group != active_group:
            if active_group:
                html_sections.append("    </div>")
            if group:
                html_sections.append(f'    <div class="r-diagnostic-pair" data-dc-layout-group="{_esc(group)}">')
            active_group = group
        html_sections.append(render_report_section(section_type, data, typed))
    if active_group:
        html_sections.append("    </div>")

    registry = build_evidence_registry(storyboard)
    return report_shell(
        title=title or clean_text(storyboard.get("title") or "Analysis Report"),
        first_section="\n".join(html_sections),
        include_plotly=include_plotly,
        evidence_registry=registry,
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
    answer = f"{lead}. {detail}" if detail else f"{lead}."
    statuses = [
        clean_text(item.get("status") or item.get("disposition") or item.get("severity") or "")
        for item in insights
    ]
    confirmed = sum(1 for s in statuses if _status_class(s) == "good")
    caution = sum(1 for s in statuses if _status_class(s) in {"warn", "danger"})
    coverage_bits = [f"{len(insights)} material insight{'s' if len(insights) != 1 else ''}"]
    if confirmed:
        coverage_bits.append(f"{confirmed} confirmed")
    if caution:
        coverage_bits.append(f"{caution} flagged with caveats")
    coverage = "The analysis surfaced " + ", ".join(coverage_bits) + "; each is paired with its evidence below."
    return f"{answer}\n\n{coverage}"


def _readout_bullet(item: dict[str, Any]) -> str:
    title = clean_text(item.get("title") or item.get("headline") or item.get("finding") or "")
    if not title:
        return ""
    status = clean_text(item.get("status") or item.get("disposition") or item.get("severity") or "")
    return f"{title} ({status})" if status else title


def _evidence_ref_keys(source: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for field in ("finding_id", "hypothesis_id"):
        value = clean_text(source.get(field) or "")
        if value:
            keys.add(value)
    for entry in _as_list(source.get("evidence") or source.get("evidence_refs")):
        if isinstance(entry, dict):
            for field in ("cell_id", "ref", "artifact_id", "finding_id", "hypothesis_id", "path"):
                value = clean_text(entry.get(field) or "")
                if value:
                    keys.add(value)
        else:
            value = clean_text(entry)
            if value:
                keys.add(value)
    return keys


def _pair_insights_with_evidence(insights: list[dict[str, Any]], planned_analyses: list[dict[str, Any]]) -> None:
    """Anchor each insight to the evidence section that shares its provenance, and backlink the section."""
    analysis_refs = []
    for planned in planned_analyses:
        data = planned.get("data", {})
        refs = _evidence_ref_keys(data)
        source = data.get("data") if isinstance(data.get("data"), dict) else None
        if source:
            refs |= _evidence_ref_keys(source)
        analysis_refs.append(refs)
    for insight in insights:
        refs = _evidence_ref_keys(insight)
        if not refs:
            continue
        for planned, planned_refs in zip(planned_analyses, analysis_refs):
            if refs & planned_refs:
                anchor = clean_text(planned["data"].get("section_id") or "")
                if not anchor:
                    continue
                insight["evidence_anchor"] = anchor
                supports = planned["data"].setdefault("supports", [])
                title = clean_text(insight.get("title") or "")
                if title and all(entry.get("title") != title for entry in supports if isinstance(entry, dict)):
                    supports.append({"title": title, "anchor": "sec-primary-insights"})
                break


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

    renderable = (
        STORY_SECTION_KINDS
        | CHART_SECTION_KINDS
        | {"table", "callout", "text", "comparison", "checklist", "explanation", "metric_row"}
    )
    if explicit in renderable:
        return {
            "section_type": explicit,
            "layout_role": f"analysis_{index + 1}_{explicit}",
            "rationale": "Use the explicit section type chosen by the report designer.",
            "data": data,
        }
    if explicit:
        raise ValueError(
            f"analyses[{index}] requested unsupported section_type '{explicit}'; "
            f"supported types: {', '.join(sorted(renderable))}"
        )

    if isinstance(data.get("groups"), list) and data.get("groups"):
        return {
            "section_type": "comparison",
            "layout_role": f"analysis_{index + 1}_comparison",
            "rationale": "Side-by-side groups compare cleanly as comparison cards.",
            "data": data,
        }
    if isinstance(data.get("checks"), list) and data.get("checks"):
        return {
            "section_type": "checklist",
            "layout_role": f"analysis_{index + 1}_checklist",
            "rationale": "Check items render as a readiness checklist.",
            "data": data,
        }
    if isinstance(data.get("events") or data.get("timeline"), list) and (data.get("events") or data.get("timeline")):
        return {
            "section_type": "ledger_timeline",
            "layout_role": f"analysis_{index + 1}_ledger_timeline",
            "rationale": "Chronological events render as a timeline.",
            "data": data,
        }

    records = data.get("records", data.get("rows"))
    chart = data.get("chart")
    if isinstance(records, list) and isinstance(chart, dict):
        filters = data.get("filters", data.get("controls"))
        if not filters:
            filters = _infer_filters(records, chart)
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
        data.setdefault("filters", data.get("controls") or _infer_filters(data.get("rows", [])))
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

    items = data.get("items", data.get("entities"))
    if isinstance(items, list):
        filters = data.get("controls", data.get("filters"))
        if not filters:
            filters = _infer_filters(items)
        if filters and len(items) > 1:
            data.setdefault("controls", filters)
            return {
                "section_type": "selector_panel",
                "layout_role": f"analysis_{index + 1}_selector_panel",
                "rationale": "Let the reader choose an entity/archetype and inspect its metrics without scanning every card.",
                "data": data,
            }
        return {
            "section_type": "entity_card_grid",
            "layout_role": f"analysis_{index + 1}_entity_cards",
            "rationale": "Summarize entities/archetypes as cards instead of burying them in prose.",
            "data": data,
        }

    if clean_text(data.get("body") or data.get("text") or ""):
        return {
            "section_type": "text",
            "layout_role": f"analysis_{index + 1}_text",
            "rationale": "Prose-only analysis renders as a narrative text section.",
            "data": data,
        }

    raise ValueError(
        f"analyses[{index}] ('{clean_text(data.get('title') or '')}') has no renderable shape; "
        "provide records+chart, rows+columns, figure, items, groups, checks, events, or an explicit section_type"
    )


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


def _infer_filters(records: list[Any], chart: dict[str, Any] | None = None) -> list[dict[str, str]]:
    if not records:
        return []
    chart = chart or {}
    excluded = {
        clean_text(chart.get("x") or chart.get("x_key") or ""),
        clean_text(chart.get("y") or chart.get("y_key") or ""),
    }
    preferred = [
        clean_text(chart.get("color") or chart.get("group") or chart.get("series") or ""),
        "segment",
        "cohort",
        "category",
        "group",
        "type",
        "status",
        "region",
        "scenario",
        "stage",
    ]
    rows = [row for row in records if isinstance(row, dict)]
    candidates: list[tuple[int, str, int]] = []
    for key in _columns_from_records(rows):
        if key in excluded:
            continue
        values = [row.get(key) for row in rows if row.get(key) not in (None, "")]
        if not values or all(_is_numberish(value) for value in values):
            continue
        unique = {clean_text(value) for value in values if clean_text(value)}
        if len(unique) < 2:
            continue
        key_l = key.lower()
        priority_index = next((i for i, name in enumerate(preferred) if name and key_l == name.lower()), None)
        max_options = 32 if priority_index is not None else 16
        if len(unique) > max_options:
            continue
        priority = priority_index if priority_index is not None else 100
        candidates.append((priority, key, len(unique)))
    candidates.sort(key=lambda item: (item[0], item[2], item[1]))
    return [
        {"key": key, "label": key.replace("_", " ").title()}
        for _, key, _ in candidates[:3]
    ]


def _is_numberish(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        try:
            float(value.replace(",", ""))
        except ValueError:
            return False
        return True
    return False


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
        variant = clean_text((item.get("data") or {}).get("layout_variant") or "") if isinstance(item.get("data"), dict) else ""
        if clean_text(item.get("layout_group") or ""):
            pattern = "two-column diagnostic pair"
        elif variant == "floating_kpis":
            pattern = "floating KPI row"
        elif variant == "hero_visual":
            pattern = "hero visualization"
        elif variant == "reader_explorer":
            pattern = "interactive reader explorer"
        elif variant == "report_epilogue":
            pattern = "methodology and provenance footer"
        elif section_type in {"chart_interpretation", "chart_table_explorer", "filterable_chart"}:
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


NARROW_SECTION_KINDS = {"narrative_band", "callout", "text", "explanation"}


def render_report_section(section_type: str, data: dict[str, Any], typed: dict[str, Any] | None = None) -> str:
    typed = typed or typed_report_section(section_type, data)
    st = str(typed.get("kind") or section_type).strip().lower()
    html = _render_section_body(section_type, data, typed)
    classes = []
    if clean_text(data.get("emphasis") or "") == "hero" and st in (CHART_SECTION_KINDS | INTERACTIVE_SECTION_KINDS):
        classes.append("is-hero")
    if st in NARROW_SECTION_KINDS:
        classes.append("is-narrow")
    variant = clean_text(data.get("layout_variant") or "")
    if st == "metric_row" and variant == "floating_kpis":
        classes.append("is-floating-kpis")
    if st == "narrative_band" and variant == "report_epilogue":
        classes.append("is-report-epilogue")
    if st == "header" and clean_text(data.get("visual_treatment") or "") == "editorial_dark":
        classes.append("is-editorial-dark")
    if classes:
        wrapper = "r-hero" if st == "header" else "r-section"
        html = html.replace(f'class="{wrapper}"', f'class="{wrapper} {" ".join(classes)}"', 1)
    kicker = clean_text(data.get("kicker") or "")
    if kicker and st != "header" and not (st == "metric_row" and variant == "floating_kpis"):
        html = re.sub(r"(<h2>)", f'<p class="r-section-kicker">{_esc(kicker)}</p>\\1', html, count=1)
    return html


def _render_section_body(section_type: str, data: dict[str, Any], typed: dict[str, Any]) -> str:
    st = str(typed.get("kind") or section_type).strip().lower()
    attrs = _section_attrs(typed)
    meta = _section_meta_script(typed)
    if st == "header":
        title = _esc(data.get("title", "Analysis Report"))
        kicker = _esc(data.get("kicker", "Dataclaw report"))
        subtitle = clean_text(data.get("subtitle", data.get("summary", "")))
        abstract = clean_text(data.get("abstract", ""))
        hero_copy = ""
        if subtitle and abstract:
            hero_copy = f'<p class="r-hero-abstract"><span class="r-hero-scope">{_esc(subtitle)}</span>{_esc(abstract)}</p>'
        elif subtitle:
            hero_copy = f'<p class="r-hero-abstract">{_esc(subtitle)}</p>'
        elif abstract:
            hero_copy = f'<p class="r-hero-abstract">{_esc(abstract)}</p>'
        return f"""    <section class="r-hero" {attrs}>
      <div class="r-kicker">{kicker}</div>
      <h1>{title}</h1>
      {hero_copy}
      {meta}
    </section>"""

    if st == "metric_row":
        floating = clean_text(data.get("layout_variant") or "") == "floating_kpis"
        metrics = data.get("metrics", [])
        cards = []
        for m in metrics if isinstance(metrics, list) else []:
            if not isinstance(m, dict):
                continue
            trend = _esc(m.get("trend", ""))
            spark = _spark_svg(m.get("spark") or m.get("sparkline"))
            cards.append(f"""<div class="r-metric">
        <div class="r-metric-label">{_esc(m.get("label", ""))}</div>
        <div class="r-metric-value">{_esc(m.get("value", ""))}{f'<span style="font-size:13px;color:var(--muted);margin-left:5px">{_esc(m.get("unit", ""))}</span>' if m.get("unit") else ''}</div>
        {f'<div class="r-metric-delta {trend}">{_esc(m.get("delta", ""))}</div>' if m.get("delta") else ''}
        {spark}
      </div>""")
        return f"""    <section class="r-section" {attrs}>
      {f'<h2 class="sr-only">{_esc(data.get("title", "Headline metrics"))}</h2>' if floating else f'<h2>{_esc(data.get("title", ""))}</h2>' if data.get("title") else ''}
      {'' if floating else _section_context(data)}
      <div class="r-metrics">{''.join(cards)}</div>
      {meta}
    </section>"""

    if st in {"chart", "chart_interpretation"}:
        chart_id = f"chart-{clean_text(typed.get('section_id') or uuid.uuid4().hex[:10])}"
        figure = copy.deepcopy(data.get("figure"))
        if not figure and data.get("figure_json"):
            figure = json.loads(str(data["figure_json"]))
        if not isinstance(figure, dict):
            raise ValueError(f"{st} section requires 'figure' dict or 'figure_json'")
        palette = data.get("palette") or data.get("colorway")
        if isinstance(palette, list) and palette:
            layout = figure.setdefault("layout", {})
            if isinstance(layout, dict) and not layout.get("colorway"):
                layout["colorway"] = palette
        figure_json = _json_for_script({"figure": figure})
        title = _esc(data.get("title", figure.get("layout", {}).get("title", {}).get("text", "Chart") if isinstance(figure.get("layout"), dict) else "Chart"))
        caption = _esc(data.get("caption", ""))
        interpretation = clean_text(data.get("interpretation") or data.get("insight") or "")
        if st == "chart_interpretation":
            interpretation = interpretation or clean_text(data.get("summary") or "")
        conclusion = clean_text(data.get("conclusion") or "")
        caveat = clean_text(data.get("caveat") or data.get("limitation") or "")
        next_action = clean_text(data.get("next_action") or data.get("action") or "")
        evidence = data.get("evidence", data.get("evidence_refs", []))
        rail = _render_evidence_rail(evidence, title="Evidence") if isinstance(evidence, list) and evidence else ""
        render_script = f'<script>(window.__DataClawReportQueue=window.__DataClawReportQueue||[]).push({{fn:"renderFigureById",id:"{chart_id}",config:{figure_json}}});</script>'
        chart_main = f"""<div class="r-chart-main">
          <div id="{chart_id}" class="r-chart-target"></div>
          {f'<p class="r-caption">{caption}</p>' if caption else ''}
          {f'<p class="r-conclusion">{_esc(conclusion)}</p>' if conclusion else ''}
        </div>"""
        has_panel = bool(interpretation or caveat or next_action or rail)
        if has_panel:
            body = f"""<div class="r-chart-story-grid">
        {chart_main}
        <aside class="r-interpretation-panel">
          <h3>Interpretation</h3>
          {f'<p>{_esc(interpretation)}</p>' if interpretation else ''}
          {f'<p class="r-finding-meta"><strong>Caveat:</strong> {_esc(caveat)}</p>' if caveat else ''}
          {f'<p class="r-finding-meta"><strong>Next:</strong> {_esc(next_action)}</p>' if next_action else ''}
          {rail}
        </aside>
      </div>"""
        else:
            body = chart_main
        context_data = {k: v for k, v in data.items() if k not in {"caption", "summary", "interpretation", "insight", "conclusion", "evidence", "evidence_refs"}}
        return f"""    <section class="r-section" {attrs}>
      <h2>{title}</h2>
      {_section_context(context_data)}
      {body}
      {render_script}
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
        rows = _normalize_interactive_table_rows(rows, data.get("columns", []))
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
        records = _normalize_interactive_table_rows(records, data.get("columns", []))
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
        <div class="r-selection-detail" data-dc-selection-detail aria-live="polite"></div>
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

        def _cell_value(row: Any, col_index: int) -> Any:
            if isinstance(row, dict):
                return row.get(columns[col_index], "")
            if isinstance(row, list) and col_index < len(row):
                return row[col_index]
            return ""

        numeric_cols = []
        for ci in range(len(columns)):
            values = [_cell_value(row, ci) for row in rows]
            values = [v for v in values if v not in (None, "")]
            numeric_cols.append(bool(values) and all(_is_numberish(v) for v in values))

        def _fmt(value: Any, ci: int) -> str:
            if numeric_cols[ci] and _is_numberish(value):
                try:
                    number = float(str(value).replace(",", ""))
                    formatted = f"{number:,.2f}".rstrip("0").rstrip(".")
                    return _esc(formatted)
                except ValueError:
                    pass
            return _esc(value)

        num_attr = ' class="num"'
        head = "".join(
            f'<th{num_attr if numeric_cols[ci] else ""}>{_esc(clean_text(str(c)).replace("_", " "))}</th>'
            for ci, c in enumerate(columns)
        )
        body_rows = []
        max_rows = int(data.get("max_rows", 20) or 20)
        max_bytes = int(data.get("max_bytes", TABLE_PREVIEW_MAX_BYTES) or TABLE_PREVIEW_MAX_BYTES)
        used_bytes = 0
        truncated = len(rows) > max_rows
        for row in rows[:max_rows]:
            cells = [
                f'<td{num_attr if numeric_cols[ci] else ""}>{_fmt(_cell_value(row, ci), ci)}</td>'
                for ci in range(len(columns))
            ]
            row_html = "<tr>" + "".join(cells) + "</tr>"
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
        narrative_title = data.get("title") or data.get("heading") or "Narrative"
        return f"""    <section class="r-section" {attrs}>
      <div class="r-narrative-band">
        <h2>{_esc(narrative_title)}</h2>
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


def _safe_inline_markup(value: Any) -> str:
    """Escape prose while preserving the small inline emphasis vocabulary we support.

    Report inputs frequently come from agents and notebooks.  Rendering their HTML
    directly would create an XSS boundary, but rendering every tag literally makes
    basic prose such as ``<b>Argentina</b>`` look broken.  Only tag names without
    attributes are reinstated after escaping; everything else remains text.
    """
    escaped = _esc(value)
    replacements = (
        (r"&lt;(?:b|strong)&gt;", "<strong>"),
        (r"&lt;/(?:b|strong)&gt;", "</strong>"),
        (r"&lt;(?:i|em)&gt;", "<em>"),
        (r"&lt;/(?:i|em)&gt;", "</em>"),
        (r"&lt;code&gt;", "<code>"),
        (r"&lt;/code&gt;", "</code>"),
    )
    for pattern, replacement in replacements:
        escaped = re.sub(pattern, replacement, escaped, flags=re.IGNORECASE)
    return escaped


def _interactive_table_column_keys(columns: Any) -> list[str]:
    keys: list[str] = []
    for column in columns if isinstance(columns, list) else []:
        if isinstance(column, dict):
            key = clean_text(column.get("key") or column.get("name") or column.get("label") or "")
        else:
            key = clean_text(column)
        if key:
            keys.append(key)
    return keys


def _normalize_interactive_table_rows(rows: list[Any], columns: Any) -> list[dict[str, Any]]:
    """Accept object rows or tabular rows, and serialize one reliable table shape."""
    column_keys = _interactive_table_column_keys(columns)
    normalized: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if isinstance(row, dict):
            normalized.append(row)
            continue
        if not isinstance(row, list):
            raise ValueError(f"interactive_table row {index + 1} must be an object or an array")
        if not column_keys:
            raise ValueError("interactive_table array rows require a non-empty 'columns' list")
        if len(row) > len(column_keys):
            raise ValueError(
                f"interactive_table row {index + 1} has {len(row)} values but only {len(column_keys)} columns"
            )
        normalized.append({key: row[position] if position < len(row) else "" for position, key in enumerate(column_keys)})
    return normalized


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
    data_note = clean_text(data.get("data_note") or "")
    if data_note:
        parts.append(f'<p class="r-data-note">{_esc(data_note)}</p>')
    supports = data.get("supports")
    if isinstance(supports, list) and supports:
        links = []
        for entry in supports[:3]:
            if not isinstance(entry, dict):
                continue
            title = clean_text(entry.get("title") or "")
            anchor = clean_text(entry.get("anchor") or "")
            if title and anchor:
                links.append(f'<a class="r-supports-link" href="#{_esc(anchor)}">Evidence for: {_esc(title)} ↑</a>')
        if links:
            parts.append(f'<div class="r-pill-row">{"".join(links)}</div>')
    pills = data.get("pills") or data.get("tags") or data.get("labels")
    if pills:
        parts.append(_render_pill_row(pills))
    methodology = data.get("methodology") or data.get("method") or data.get("approach")
    if methodology:
        parts.append(f'<div class="r-method-note"><strong>Method</strong>{_paragraphs(methodology)}</div>')
    bullets = data.get("bullets") or data.get("key_points") or data.get("takeaways")
    if bullets:
        parts.append(_render_bullet_list(bullets))
    adjacent_insights = data.get("adjacent_insights")
    if isinstance(adjacent_insights, list) and adjacent_insights:
        cards = "".join(_render_insight_card(item) for item in adjacent_insights[:2])
        if cards:
            parts.append(f'<div class="r-adjacent-insights">{cards}</div>')
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
    if status in {"warning", "warn", "caution", "caveat", "unknown", "medium", "unresolved", "needs_review", "weakened"}:
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
    # Must mirror the JS selectorKey() fallback chain, or selector cards get
    # keys the runtime visibility map never matches and every card hides.
    if isinstance(item, dict):
        return clean_text(item.get("id") or item.get("key") or item.get("name") or item.get("title") or index)
    return clean_text(index)


def _spark_svg(values: Any) -> str:
    """Render a small inline sparkline SVG from a list of numbers."""
    nums: list[float] = []
    for value in _as_list(values):
        try:
            nums.append(float(value))
        except (TypeError, ValueError):
            return ""
    if len(nums) < 2:
        return ""
    lo, hi = min(nums), max(nums)
    span = (hi - lo) or 1.0
    width, height, pad = 100.0, 30.0, 2.0
    step = (width - 2 * pad) / (len(nums) - 1)
    points = [
        (pad + i * step, pad + (height - 2 * pad) * (1 - (v - lo) / span))
        for i, v in enumerate(nums)
    ]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    fill = f"{pad:.1f},{height - pad:.1f} {line} {points[-1][0]:.1f},{height - pad:.1f}"
    return (
        f'<svg class="r-spark" viewBox="0 0 {width:.0f} {height:.0f}" preserveAspectRatio="none" aria-hidden="true">'
        f'<polygon points="{fill}"></polygon>'
        f'<polyline points="{line}"></polyline>'
        f"</svg>"
    )


def _metric_bar_pct(metric: dict[str, Any] | None, value: Any) -> float | None:
    """Derive a 0-100 fill percentage for an entity metric bar, if the value supports one."""
    if isinstance(metric, dict):
        if metric.get("bar_pct") is not None:
            try:
                return max(0.0, min(100.0, float(metric["bar_pct"])))
            except (TypeError, ValueError):
                return None
        if metric.get("max") not in (None, "", 0):
            try:
                return max(0.0, min(100.0, float(metric.get("value", 0)) / float(metric["max"]) * 100))
            except (TypeError, ValueError, ZeroDivisionError):
                return None
    text = clean_text(value)
    if text.endswith("%"):
        try:
            return max(0.0, min(100.0, float(text.rstrip("%").replace(",", ""))))
        except ValueError:
            return None
    return None


def _safe_css_color(value: Any) -> str:
    color = clean_text(value or "")
    if re.fullmatch(r"#[0-9a-fA-F]{3,8}", color):
        return color
    if re.fullmatch(r"var\(--[A-Za-z0-9-]+\)", color):
        return color
    return ""


def _render_entity_card(item: Any, index: int, *, selector: bool = False) -> str:
    selector_attr = (
        f' data-dc-selector-card="{_esc(_selector_key(item, index))}" role="button" tabindex="0" aria-pressed="false"'
        if selector
        else ""
    )
    accent = _safe_css_color(item.get("accent_color") or item.get("color")) if isinstance(item, dict) else ""
    accent = accent or f"var(--dc-cat-{(index % 8) + 1})"
    accent_style = f' style="--card-accent: {accent}"'
    if not isinstance(item, dict):
        return f'<article class="r-entity-card"{selector_attr}{accent_style}><h3>{_esc(item)}</h3></article>'
    title = _item_title(item, f"Entity {index + 1}")
    detail = _item_detail(item)
    status = item.get("status") or item.get("state") or item.get("segment") or item.get("archetype")
    tag_values = [
        value
        for value in _as_list(item.get("tags") or item.get("pills") or item.get("meta"))
        if clean_text(value)
    ][:3]
    chips = "".join([
        _chip(status, _status_class(status)),
        _chip(item.get("confidence"), "neutral"),
        *(_chip(value, "neutral") for value in tag_values),
    ])
    count = item.get("count") or item.get("n") or item.get("size")
    count_badge = f'<span class="r-entity-count">{_esc(count)}</span>' if count not in (None, "") else ""
    metrics = item.get("metrics")
    metric_rows: list[tuple[str, Any, dict[str, Any] | None]] = []
    if isinstance(metrics, dict):
        metric_rows = [(clean_text(key).replace("_", " ").title(), value, None) for key, value in metrics.items()]
    elif isinstance(metrics, list):
        for metric in metrics:
            if isinstance(metric, dict):
                label = clean_text(metric.get("label") or metric.get("name") or metric.get("key"))
                metric_rows.append((label, metric.get("value", ""), metric))
    else:
        for key in ("score", "rank", "value", "projection", "similarity"):
            if item.get(key) not in (None, ""):
                metric_rows.append((key.replace("_", " ").title(), item.get(key), None))
    rendered_metrics = []
    for label, value, metric in metric_rows:
        if not label and value in (None, ""):
            continue
        pct = _metric_bar_pct(metric, value)
        bar = f'<span class="r-metric-bar"><span style="width:{pct:.1f}%"></span></span>' if pct is not None else ""
        rendered_metrics.append(
            f'<div class="r-entity-metric"><span>{_esc(label)}</span>{bar}<strong>{_esc(value)}</strong></div>'
        )
    bullets = _render_bullet_list(item.get("bullets") or item.get("traits") or item.get("points"))
    return f"""<article class="r-entity-card"{selector_attr}{accent_style}>
      {count_badge}
      <div class="r-meta-row">{chips}</div>
      <h3>{_esc(title)}</h3>
      {f'<p>{_esc(detail)}</p>' if detail else ''}
      {bullets}
      {f'<div class="r-entity-metrics">{"".join(rendered_metrics)}</div>' if rendered_metrics else ''}
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


def _evidence_label(item: Any) -> str:
    if isinstance(item, dict):
        kind = clean_text(item.get("kind") or item.get("type") or "")
        ref = clean_text(
            item.get("cell_id")
            or item.get("ref")
            or item.get("artifact_id")
            or item.get("finding_id")
            or item.get("path")
            or item.get("summary")
            or ""
        )
        if kind and ref:
            return f"{kind.replace('_', ' ')}: {ref}"
        return ref or kind
    return clean_text(item)


def _render_evidence_chips(evidence: Any, *, anchor: str = "") -> str:
    chips = []
    for item in _as_list(evidence):
        label = _evidence_label(item)
        if not label:
            continue
        if anchor:
            chips.append(f'<a class="r-chip neutral r-evidence-chip" href="#{_esc(anchor)}">{_esc(label)}</a>')
        else:
            chips.append(f'<span class="r-chip neutral r-evidence-chip">{_esc(label)}</span>')
    if not chips:
        return ""
    return f'<div class="r-evidence-chips"><span class="r-evidence-chips-label">Evidence</span>{"".join(chips)}</div>'


def _render_insight_card(item: Any) -> str:
    if not isinstance(item, dict):
        return f'<article class="r-insight-card"><p>{_esc(item)}</p></article>'
    status = item.get("severity") or item.get("disposition") or item.get("status") or item.get("confidence")
    status_class = _status_class(status)
    accent = _safe_css_color(item.get("accent_color") or item.get("color"))
    accent_style = f' style="border-top-color:{accent}"' if accent else ""
    chips = [
        _chip(status, status_class),
        _chip(item.get("confidence"), "neutral") if item.get("confidence") and item.get("confidence") != status else "",
        _chip(item.get("finding_id"), "neutral"),
        _chip(item.get("hypothesis_id"), "neutral"),
    ]
    evidence = item.get("evidence")
    evidence_anchor = clean_text(item.get("evidence_anchor") or "")
    caveat = item.get("caveat") or item.get("limitation")
    next_action = item.get("next_action") or item.get("action")
    bullets = _render_bullet_list(item.get("bullets") or item.get("points") or item.get("supporting_points"))
    method = item.get("method") or item.get("methodology")
    anchor_link = (
        f'<a class="r-supports-link" href="#{_esc(evidence_anchor)}">See the evidence ↓</a>'
        if evidence_anchor
        else ""
    )
    return f"""<article class="r-insight-card {status_class}"{accent_style}>
      <div class="r-meta-row">{''.join(chips)}</div>
      <h3>{_esc(_item_title(item))}</h3>
      {f'<p>{_esc(_item_detail(item))}</p>' if _item_detail(item) else ''}
      {bullets}
      {f'<p class="r-finding-meta"><strong>Method:</strong> {_esc(method)}</p>' if method else ''}
      {_render_evidence_chips(evidence, anchor=evidence_anchor)}
      {f'<p class="r-finding-meta"><strong>Caveat:</strong> {_esc(caveat)}</p>' if caveat else ''}
      {f'<p class="r-finding-meta"><strong>Next:</strong> {_esc(next_action)}</p>' if next_action else ''}
      {anchor_link}
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
        {_render_evidence_chips(evidence)}
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
        rows = [(clean_text(str(k)).replace("_", " ").title(), v) for k, v in group_metrics.items()]
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
    evidence_html = _render_evidence_chips(evidence)
    caveat_html = f'<p class="r-finding-meta"><strong>Caveat:</strong> {_esc(caveat)}</p>' if caveat else ""
    return f'<li class="r-finding">{title_html}{detail_html}{bullets}{evidence_html}{caveat_html}</li>'


def _paragraphs(value: Any) -> str:
    text = clean_text(value)
    parts = [p.strip() for p in text.split("\n\n") if p.strip()]
    return "".join(f"<p>{_safe_inline_markup(p)}</p>" for p in parts)
