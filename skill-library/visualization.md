---
name: visualization
description: Produce interactive Plotly charts, KPI metric tiles, and an aggregated App view from any analysis. The standard visual-output contract — other skills follow these conventions instead of implementing their own charting.
tags: [visualization, charts, metrics, insights, framework]
---

## When to use
Whenever an analysis produces a number worth headlining or a comparison worth
showing. Any skill that needs visual output should follow these conventions
rather than defining its own — outputs then render inline in chat AND
accumulate automatically in the session's App panel, which the user can
curate and publish as a standalone page.

## The three output primitives

### 1. Interactive charts — standard Plotly, nothing custom
Write ordinary Plotly in a notebook cell and call `fig.show()`:

```python
import plotly.express as px
fig = px.bar(df, x="segment", y="value", title="Clear, specific title")
fig.show()
```

The chart renders interactively (hover/zoom/pan) in chat and is collected
into the App panel. Do NOT save charts as PNG files or use matplotlib for
final output — static images are not collected.

To attach a one-line insight to a chart, re-show its cell with a caption:
`display_cell_output(cell_index=..., caption="Stat + caveat in one sentence.")`
The caption appears under the chart in the App panel and on the published page.

### 2. Metric tiles — one call per headline KPI

```python
display_metric(label="AI Adoption Rate", value="67%",
               delta="+12 pp vs 2022", trend="up")
display_metric(label="Respondents", value="89,184", unit="developers")
```

- `label`: short, uppercase-friendly name
- `value`: the headline number, pre-formatted as a string
- `delta` (optional): change vs baseline, with the comparison spelled out
- `unit` (optional): rendered small after the value
- `trend` (optional): `"up"` | `"down"` | `"flat"` — colors the delta and adds an arrow

Emit 2–3 metric tiles per analysis: the numbers that answer the user's
question. More than ~5 dilutes the panel.

### 3. App panel — automatic, no action needed
Every chart and metric above is collected into the App sidebar tab and the
published `/app/<session-id>` page. Produce outputs in narrative order —
headline metrics first, then charts from most to least important — the panel
preserves production order (the user can hide/reorder afterward).

## Chart-type selection
- Categorical comparison / ranking → bar
- Trend over time → line
- Relationship between two continuous variables → scatter
- Matrix / cross-segment intensity → heatmap
- Key headline numbers → metric tiles (not a chart)

## Viewer interactivity (explore-lite)
Published charts keep Plotly's hover/zoom/pan for free. When a chart has a
natural breakdown dimension (segment, region, year), bake a dropdown filter
into the figure with `updatemenus` so viewers can explore without code:

```python
fig.update_layout(updatemenus=[dict(
    buttons=[dict(label=seg, method="update",
                  args=[{"visible": [t.name == seg for t in fig.data]}])
             for seg in segments],
    direction="down", x=1.0, y=1.15,
)])
```

Prefer one well-filtered chart over five near-duplicate charts.

## Quality bar (self-check before finishing)
- Every chart has a title and labelled axes with units
- No truncated y-axis that exaggerates differences
- No dual y-axis with incompatible units; no pie charts with >5 slices; no 3D
- Trends/predictions show uncertainty where available
- One-line caption per chart: stat + caveat
