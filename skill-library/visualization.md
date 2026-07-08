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

## Skill triad
- `dashboarding` decides the story: user question, audience, decision, KPI
  sequence, chart order, filters, and revision loop.
- `visualization` emits the visual evidence: charts, metrics, tables, captions,
  aggregate data islands, and integrity checks.
- `dataclaw-artifacts` publishes, versions, serves, embeds, secures, themes, and
  exports the result.

If a task needs a full dashboard/report, fetch and follow `dashboarding` too.

## Tool names
Examples use canonical DataClaw tool names: `report_add_section`,
`display_cell_output`, `display_metric`, `publish_artifact`, and
`read_artifact`. If the runtime exposes only plugin-prefixed aliases such as
`dataclaw_report_add_section` or `dataclaw_display_metric`, use the visible
alias with the same arguments.

## Output primitives

### 1. Artifact report sections - the primary surface
Build the user-facing deliverable as artifact sections, not a long chat answer.
Start early and add sections as findings emerge. `report_add_section` remains
the compatibility helper, but its sections must map cleanly to artifact section
types and pass artifact validation before publish.

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

Allowed section types: `header`, `metric_row`, `chart`, `findings`, `callout`,
`text`, and `table`. Each section needs a stable title, short caption or body,
and enough provenance for the living report to attach it to the current plan
step. Step attribution travels by stable plan step id; names are display labels.

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
object or JSON into a report chart section:

```python
report_add_section(section_type="chart", report_path="reports/analysis.html", data={
    "title": "Value vs output",
    "figure": fig.to_dict(),
    "caption": "Market value explains output only weakly; expensive does not equal elite.",
})
```

### 3. Metric tiles - one call per headline KPI

```python
display_metric(label="AI Adoption Rate", value="67%",
               delta="+12 pp vs 2022", trend="up")
display_metric(label="Respondents", value="89,184", unit="developers")
```

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

## Artifact section contract
Skill-generated sections should be representable as typed artifact sections:

```json
{
  "section_id": "sec-primary-chart",
  "kind": "chart",
  "title": "Revenue by segment",
  "caption": "Enterprise drove 62% of growth; SMB declined after Q3.",
  "plan_step_id": "s2",
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
