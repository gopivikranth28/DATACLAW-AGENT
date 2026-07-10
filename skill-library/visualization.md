---
name: visualization
description: Produce artifact-compliant visual evidence: Plotly charts, KPI metric tiles, tables, captions, and typed report sections that can be published, versioned, secured, and exported by dataclaw-artifacts.
tags: [visualization, charts, metrics, insights, artifacts, framework]
---

## When to use
Whenever an analysis produces a number worth headlining, a comparison worth
showing, or a finding worth presenting. Any skill that needs visual output
should follow this contract instead of inventing its own chart/report format.

The final visual deliverable is an **artifact** or a **living report**. Chat
messages are for short narration; the durable surface is the published artifact.
The `/app/:sessionId` route is compatibility only and should not be used as the
final report/dashboard handoff.

## Skill stack
- `dashboarding` decides the story: user question, audience, decision, KPI
  sequence, chart order, filters, and revision loop.
- `report_design` turns completed insights and aggregate assets into the final
  storyboard, section mix, interaction plan, evidence placement, and quality gate.
- `visualization` emits the visual evidence: charts, metrics, tables, captions,
  aggregate data islands, and integrity checks.
- `dataclaw-artifacts` publishes, versions, serves, embeds, secures, themes, and
  exports the result.
Use the shared DataClaw artifact token system for report/dashboard output so
charts, KPI tiles, tables, and living-report entries look related inside the
same session or project.

If a task needs a full dashboard/report, fetch and follow `dashboarding` and
`report_design` too.

## Tool names
Examples use canonical DataClaw tool names: `report_add_section`,
`display_cell_output`, `display_metric`, `publish_artifact`, and
`read_artifact`. If the runtime exposes only plugin-prefixed aliases such as
`dataclaw_report_add_section` or `dataclaw_display_metric`, use the visible
alias with the same arguments.

## Output primitives

### 1. Artifact report sections - the primary surface
Build the user-facing deliverable as artifact sections, not a long chat answer.
For final comprehensive reports, finish the notebook analysis and EDA findings
first, then fetch and follow the `report_design` skill and call
`report_design_report` with the completed insights, analysis assets, aggregate
payloads, evidence, methodology, and requirements. The report designer should
storyboard the full report, choose section layouts and interactions, write a
storyboard JSON, and render the HTML in one pass.
`report_add_section` remains a low-level compatibility helper for manual or
incremental assembly, but do not rely on appended report cells as the final
strategy for a cohesive analytical report.

```python
report_design_report(
    report_goal="Explain the player archetypes and which signals support each one.",
    title="FIFA World Cup 2026 Player Archetypes",
    report_path="reports/world-cup-player-archetypes.html",
    storyboard_path="reports/world-cup-player-archetypes-storyboard.json",
    insights=[
        {
            "title": "Creator archetype separates from finishers",
            "detail": "Similarity scores show a distinct creator cluster with higher chance creation.",
            "finding_id": "find-creator",
            "hypothesis_id": "hyp-archetype",
            "evidence": [{"kind": "notebook_cell", "cell_id": "cell-sim"}],
            "caveat": "Simulation data is descriptive, not causal.",
        }
    ],
    analyses=[
        {
            "title": "Player similarity explorer",
            "records": player_similarity_aggregate.to_dict("records"),
            "chart": {"type": "bar", "x": "player", "y": "similarity", "color": "archetype"},
            "columns": ["team", "archetype", "player", "similarity"],
            "filters": [{"key": "team"}, {"key": "archetype"}],
            "interpretation": "The selector changes both the visual evidence and the lookup table.",
        }
    ],
    requirements={"methodology": [{"title": "Aggregate first", "detail": "Embed only precomputed aggregate records."}]},
)
```

When you do use `report_add_section`, each section must map cleanly to artifact
section types and pass artifact validation before publish.

```python
report_add_section(
    section_type="header",
    report_path="reports/world-cup-performance.html",
    title="FIFA World Cup 2026 Player Performance",
    data={
        "kicker": "Simulation analysis",
        "title": "FIFA World Cup 2026 - Player Performance",
        "subtitle": "A visual readout of player value, team strength, and stage trends.",
    },
)

report_add_section(section_type="metric_row", report_path="reports/world-cup-performance.html", data={
    "metrics": [
        {"label": "Rows analyzed", "value": "54,600"},
        {"label": "Bench/DNP rows", "value": "42%", "delta": "Filter minutes > 0"},
        {"label": "Rating correlation", "value": "0.93", "delta": "vs performance_score"},
    ]
})
```

Allowed section types: `header`, `metric_row`, `narrative_band`,
`methodology_block`, `chart_interpretation`, `evidence_rail`,
`ledger_timeline`, `insight_grid`, `explanation`, `comparison`, `checklist`,
`hypothesis_ledger`, `evidence_trace`, `filterable_chart`,
`interactive_table`, `selector_panel`, `chart_table_explorer`,
`entity_card_grid`, `chart`, `findings`, `callout`, `text`, and `table`.
Each section needs a stable title,
short caption or body, and enough provenance for the living report to attach it
to the current plan step. Step attribution travels by stable plan step id; names
are display labels.

Before emitting sections, storyboard the report: executive readout, primary
insight, supporting evidence, caveats, methodology, and appendix. Persist the
report assembly calls in the notebook or a source script so the final artifact
can be regenerated and reviewed; do not leave the report-building logic only in
transient tool calls.

Use the richer narrative sections deliberately:

- `narrative_band` for a short story turn, executive readout, caveat band, or revised interpretation.
- `methodology_block` for how an analysis was checked: grain, denominator, validation, review, and assumptions.
- `chart_interpretation` when a chart needs adjacent interpretation, caveat, evidence refs, or next action. Prefer it over plain `chart` for structured EDA.
- `evidence_rail` to keep notebook cells, query cards, artifact sections, or findings beside the claim they support.
- `ledger_timeline` for hypothesis, finding, review, risk-acceptance, publish, or supersession chronology.
- `insight_grid` for 2-6 key insights, each with evidence, confidence/status, and caveat.
- `explanation` for the analysis path, assumptions, or why a result matters.
- `comparison` for side-by-side segments, cohorts, models, periods, or scenarios.
- `checklist` for readiness, QA, validation, and launch/blocker states.
- `hypothesis_ledger` for EDA hypotheses, dispositions, and next actions.
- `evidence_trace` for notebook cells, tables, filters, or checks that support claims.
- `filterable_chart` when the same aggregate chart should respond to a small set of embedded filters.
- `interactive_table` for sortable/searchable aggregate or preview tables with captions and filters.
- `selector_panel` for team, player, cohort, model, or scenario selectors that filter adjacent cards.
- `chart_table_explorer` for chart + interpretation + searchable table over the same aggregate payload. Prefer this over repeated near-duplicate charts.
- `entity_card_grid` for archetype, player, segment, cohort, or scenario cards with metric summaries.
  Cards support `count` (badge), `tags` (chips), and metrics as
  `{"label", "value", "max"?}` or `{"label", "value", "bar_pct"?}` — numeric
  shares and percentage values render as inline comparison bars.
- `findings` for published EDA finding lists; each item should carry `finding_id`
  and, when applicable, `hypothesis_id` so review can trace claims back to the
  ledgers.

Use consistent section structure as the report evolves. Prefer these optional
fields whenever they clarify the story: `caption` for the section thesis,
`tags`/`pills` for state or scope, `methodology`/`method` for how the claim was
checked, `bullets`/`key_points` for scannable logic, and per-item `evidence`,
`caveat`, `next_action`, and `bullets`. When a later insight changes the
interpretation, append a new section that names the revised layer rather than
silently replacing the earlier story.

Use plain `chart` as supporting material, not the main storytelling unit. If a
report naturally supports slicing, lookup, ranking, or side-by-side comparison,
use `filterable_chart`, `interactive_table`, `selector_panel`, or
`chart_table_explorer` with small aggregate JSON payloads. Do not embed raw full
datasets in report controls.

```python
report_add_section(section_type="insight_grid", report_path="reports/analysis.html", data={
    "title": "What changed the interpretation",
    "caption": "Only promote insights that changed the answer or readiness verdict.",
    "tags": ["validated", "decision-relevant"],
    "methodology": "Each card ties back to a notebook cell, denominator check, or hypothesis disposition.",
    "bullets": ["Separate signal from data artifacts.", "Keep unresolved caveats visible."],
    "items": [
        {
            "title": "High-value users are concentrated in two cohorts",
            "detail": "The top decile contributes 48% of revenue, but only after excluding refund rows.",
            "status": "confirmed",
            "meta": ["n=18,420", "validated against revenue_total"],
            "bullets": ["Tail concentration persists by account age.", "Refund rows explain the largest outliers."],
        },
        {
            "title": "Signup channel is confounded by tenure",
            "detail": "Paid channels look weaker until account age is controlled.",
            "status": "caution",
            "meta": ["requires cohort-normalized view"],
        },
    ],
})

report_add_section(section_type="checklist", report_path="reports/analysis.html", data={
    "title": "Model-readiness checks",
    "checks": [
        {"title": "Target leakage audit", "status": "pass", "detail": "Future-only fields excluded."},
        {"title": "Class balance", "status": "warning", "detail": "Positive class is 7.8%; use stratified split."},
    ],
})
```

If the generated compatibility shell includes a remote CDN fallback or other
artifact-invalid HTML, fix the source once before publishing. If publish tools
are unavailable, leave the canonical report source in the workspace and say that
artifact publication is unavailable; do not invent an artifact id or version.

After the report is assembled, fetch and follow the `artifacts` skill to
publish or revise it with `publish_artifact`. Use the same `artifact_id` when
the user asks for changes.

### 2. Interactive charts - standard Plotly, nothing custom
Write ordinary Plotly in a notebook cell and call `fig.show()`:

```python
import plotly.express as px
fig = px.bar(df, x="segment", y="value", title="Clear, specific title")
fig.show()
```

The chart renders interactively in chat while the artifact/living report carries
the final published surface. Do not save charts as PNG files or use
matplotlib/seaborn for final output unless the user explicitly asks for a static
image.

To attach a one-line insight to a chart, re-show its cell with a caption:
`display_cell_output(cell_index=..., caption="Stat + caveat in one sentence.")`

To embed a notebook chart in an artifact section, pass the same Plotly figure
object or JSON into a report chart section. Use `chart_interpretation` when the
chart carries an analytical claim, caveat, evidence, or next action:

```python
report_add_section(section_type="chart_interpretation", report_path="reports/analysis.html", data={
    "title": "Value vs output",
    "figure": fig.to_dict(),
    "caption": "Market value explains output only weakly; expensive does not equal elite.",
    "interpretation": "The relationship is outlier-sensitive, so value should not be used as a single ranking signal.",
    "caveat": "Correlation is descriptive and not causal.",
    "evidence": [{"kind": "notebook_cell", "cell_id": "abc123", "summary": "Correlation recompute after outlier review."}],
})
```

Plain `chart` remains appropriate for supporting visuals whose interpretation
is already carried by a nearby narrative or findings section.

### Chart spec grammar for record-driven sections

`filterable_chart`, `chart_table_explorer`, and designer `analyses` entries take a
small `chart` spec over aggregate `records`:

- `type`: `bar` (default), `hbar` (horizontal bar), `line`, `scatter`, or
  `heatmap` (`x`, `y`, plus `z`/`value` for cell intensity; diverging data that
  spans zero automatically gets a diverging colorscale centered at 0).
- `x`, `y`, `color` (series/group key), `x_label`, `y_label`, `title`.
- `sort`: bars sort by value descending by default; use `"asc"`, `"label"`, or
  `"none"` to override. Rely on this instead of pre-sorting for display.
- `agg`: duplicate x values per series aggregate with `sum` by default; use
  `"mean"`, `"max"`, `"min"`, or `"count"` when the grain requires it.
- `reference_lines`: `[{"axis": "y", "value": 50, "label": "baseline"}]` draws
  dotted cue lines; `annotations`: `[{"x": ..., "y": ..., "text": "..."}]`
  points at the notable region. Use these for "what to look at" cueing.

Charts are themed at render time: colorway from the `--dc-cat-*` tokens,
transparent surfaces, shell typography, and automatic re-render on light/dark
toggle. Do not bake explicit background colors, font colors, or a Plotly
template into figures or `chart.layout` — they defeat theme sync.

### 3. Metric tiles - one call per headline KPI

```python
display_metric(label="AI Adoption Rate", value="67%",
               delta="+12 pp vs 2022", trend="up")
display_metric(label="Respondents", value="89,184", unit="developers")
```

In report `metric_row` sections, a metric may also carry
`"spark": [5.1, 5.4, 5.2, 5.9, 6.4]` — a small trend series rendered as an
inline sparkline under the value. Prefer it whenever a KPI has a natural
time series behind it.

- `label`: short, uppercase-friendly name
- `value`: the headline number, pre-formatted as a string
- `delta` (optional): change vs baseline, with the comparison spelled out
- `unit` (optional): rendered small after the value
- `trend` (optional): `"up"` | `"down"` | `"flat"` - colors the delta and adds an arrow

Emit 2-3 metric tiles per analysis: the numbers that answer the user's
question. More than ~5 dilutes the dashboard.

### 4. Tables, findings, and callouts
Use tables for exact comparisons and auditability, not decoration. Use findings
or callouts for interpretation, caveats, and action implications.

Every table section should include:
- a concise title
- row/column labels with units
- sort order
- source or filter note when the denominator matters
- no more rows than a reader can scan; put long tables in downloadable files

Prefer `interactive_table` when the reader needs search, sort, column filters,
pagination, or row lookup. Include only aggregate, ranked, or sampled rows that
are safe to embed in the artifact preview.

## Report quality gate
`report_add_section` returns a `quality` object. Treat warnings as action items
before publishing. Use `quality_gate="fail"` before the final publish/revise pass
to catch chart dumps, missing insight sections, missing evidence ids, missing
table captions, stale installed skills, oversized HTML, or reports that should
have an explorer but only contain static chart stacks.

## Artifact section contract
Skill-generated sections should be representable as typed artifact sections:

```json
{
  "section_id": "sec-primary-chart",
  "kind": "chart",
  "title": "Revenue by segment",
  "caption": "Enterprise drove 62% of growth; SMB declined after Q3.",
  "plan_step_id": "step-a1b2c3d4",
  "data_policy": "aggregate_only",
  "payload": {
    "plotly_json_asset": "sha256:...",
    "summary_json_bytes": 48213
  }
}
```

Use DataClaw theme tokens (`--dc-bg`, `--dc-ink`, `--dc-muted`,
`--dc-accent`, `--dc-good`, `--dc-warn`, `--dc-danger`) rather than hard-coded
visual systems. Any custom HTML/JS must obey artifact validation: no external
assets, no fetch/XHR/WebSocket, no iframes/objects/embeds/base tags, no inline
event handlers, no JavaScript-driven navigation, and no relative assets that
resolve outside allowed workspace/project roots.

## Data contract
Aggregate in the notebook, not the browser. Embed summary series as a
`<script type="application/json">` island or a typed section payload. Keep each
visual payload small; target <= 200 KB per chart/section. Never embed raw
datasets in final visual artifacts. The 25 MiB cap applies to the published or
exported single-file artifact, not the living-report manifest store.

## Chart-type selection
- Categorical comparison / ranking -> bar
- Trend over time -> line
- Relationship between two continuous variables -> scatter
- Matrix / cross-segment intensity -> heatmap
- Part-to-whole with <= 5 categories -> small multiple bars before pie
- Key headline numbers -> metric tiles, not charts

## Viewer interactivity
Published charts keep Plotly hover/zoom/pan. When a chart has a natural
breakdown dimension (segment, region, year), bake a dropdown filter into the
figure with `updatemenus` so viewers can explore without code:

```python
fig.update_layout(updatemenus=[dict(
    buttons=[dict(label=seg, method="update",
                  args=[{"visible": [t.name == seg for t in fig.data]}])
             for seg in segments],
    direction="down", x=1.0, y=1.15,
)])
```

Prefer one well-filtered chart over five near-duplicate charts. Filters must use
precomputed aggregate slices; artifacts must not query live data.

## Quality bar
Before finishing, verify:
- every chart has a title and labelled axes with units
- bars start at zero unless the chart is not encoding magnitude by bar length
- no dual y-axis with incompatible units
- no pie chart with >5 slices; no 3D charts
- trends/predictions show uncertainty where available
- one-line caption per chart: stat + caveat
- color is not the only signal; labels or symbols carry meaning too
- layout works in light mode, dark mode, inline embed, expanded view, and export
- publish/revision followed the `artifacts` skill and used the same `artifact_id` for edits
