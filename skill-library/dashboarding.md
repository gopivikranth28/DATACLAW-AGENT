---
name: dashboarding
description: Compose a clear, non-misleading artifact dashboard/report that directly answers a stated question, using the visualization skill for visual grammar and dataclaw-artifacts for publishing, versioning, security, and export.
tags: [visualization, dashboarding, reporting, charts, artifacts]
---

## When to use
The user has a dataset and a specific question, and wants a clean, shareable
visual answer - "build a dashboard", "show me who/what/when", "visualize this",
"give me a report". Use this skill to decide the story and layout. Use the
`visualization` skill for the visual evidence. Use artifacts as the final
published surface.

Do not leave the final answer as loose charts, App-panel state, or a long chat
message. The final visual deliverable should be a published artifact or a living
report entry. `/app/:sessionId` is only a compatibility scratch view for loose
visual outputs; do not use it as the final dashboard/report surface.

Publish a standalone report/dashboard/chart page with `publish_artifact`. Use
living-report notes for interpretation, decisions, rationale, and direction
changes that accumulate during the investigation.

## Skill triad
- `dashboarding` scopes the decision and composes the storyboard.
- `visualization` produces the chart/KPI/table/caption sections and runs the
  misleading-viz audit.
- `dataclaw-artifacts` publishes/revises the artifact, serves it safely, keeps
  history, syncs theme, and exports it.
Use one shared DataClaw token system within a session/project; do not invent a
new palette, radius system, or decorative language for each dashboard.

## Tool names
Examples use canonical DataClaw tool names: `display_metric`,
`display_cell_output`, `report_add_section`, `publish_artifact`, and
`read_artifact`. If the runtime exposes only plugin-prefixed aliases such as
`dataclaw_report_add_section`, use the visible alias with the same arguments.

## First questions
Ask only when the request does not already answer them:

1. What is the single question this dashboard must answer?
2. Who is the audience and what decision does this inform?
3. What is the time grain, comparison baseline, and grouping?

If the user's request already answers these, state your reading in one line and
proceed.

## Dashboard archetypes
Pick one primary archetype before building:

- **Executive readout** - 2-3 KPIs, one primary trend/comparison, short caveats.
- **Diagnostic dashboard** - starts with symptom, then segment/time breakdowns.
- **Model comparison** - primary metric, baseline row, deltas, reproducibility
  notes, and badging for incomparable evaluation data.
- **Data quality report** - completeness, duplicates, type/range anomalies,
  coverage gaps, and readiness verdict.
- **Exploratory briefing** - ranked findings, evidence chart per finding, and
  "what to investigate next".

The archetype controls layout and chart count. Do not mix archetypes unless the
user asks for a broad report.

## Analytical sequence

1. **Question scoping** - reduce to one primary question; every element must
   serve it.
2. **Data sanity pass** - shape, types, missing values, duplicates, time range,
   and denominator traps. Note limits that affect trust.
3. **Metric selection** - choose 2-3 KPIs that answer the question directly.
   Emit them as metric tiles first.
4. **Storyboard** - decide the section order before charting: header, KPI row,
   executive callout, primary chart, supporting charts/tables, caveats, next
   steps.
5. **Aggregate data** - compute summary series in pandas/polars. Never embed raw
   datasets in the dashboard artifact. The 25 MiB cap applies to published/exported
   single-file artifacts, not the living-report manifest store.
6. **Visual evidence** - follow `visualization`: Plotly via `fig.show()`, KPIs
   via `display_metric`, captions via `display_cell_output`, and report sections
   via `report_add_section`.
7. **Artifact assembly** - assemble `header`, `metric_row`, `chart`, `table`,
   `findings`, `callout`, and `text` sections into a report HTML source.
8. **Publish or revise** - fetch and follow the `artifacts` skill, then call
   `publish_artifact(source_path=..., title=...)`. For edits, read/revise the
   canonical source and publish with the same `artifact_id` and `base_version`.
   If artifact tools are unavailable, keep the canonical source in the workspace
   and say publication is unavailable; do not invent an id, version, or URL.
9. **Audit and self-check** - run the pitfalls checklist. When browser tooling is
   available, screenshot the artifact in light and dark mode before closing the
   plan step.

## Layout rules
- Put the answer first: headline, 2-3 KPI tiles, and the primary chart above the
  fold.
- Use 2-4 charts for most dashboards. More charts require a report structure,
  not a denser grid.
- One chart per sub-question. Prefer a filtered chart over near-duplicates.
- Use tables only when exact values or auditability matter.
- Put caveats next to the evidence they qualify, not at the end where they will
  be missed.
- Preserve stable section titles so revisions and living-report anchors remain
  meaningful. Attribute sections and notes by stable plan step id; step names are
  display labels, not identity.

## Revision loop
When the user asks to change the dashboard:

1. Read the current artifact source with `read_artifact(artifact_id, version?)`.
2. Make the smallest source change that satisfies the request.
3. Re-run affected notebook aggregates if the data logic changes.
4. Follow the `artifacts` skill and publish the same `artifact_id` with `base_version`.
5. Mention the new version and what changed in one sentence.

Do not create a new artifact for ordinary dashboard revisions.
If `read_artifact`/`publish_artifact` are unavailable, revise the canonical
workspace source only and tell the user publication is blocked by missing
artifact tooling.

## Pitfalls checklist
- Truncated y-axis that exaggerates differences - bars start at zero.
- Dual y-axis with incompatible units - split into two charts.
- Pie chart with more than 5 slices - use a bar chart.
- 3D charts - chartjunk.
- Missing axis labels, units, or chart titles.
- Trend lines on scatter without uncertainty or caveat.
- Cumulative charts presented as per-period growth.
- Categorical axes sorted arbitrarily; sort by value unless the order is
  inherent.
- Raw row-level data embedded in browser payloads.
- External assets, remote images, fetch calls, inline event handlers, or custom
  script patterns that artifact validation will reject.
- Relative asset paths that escape the workspace/project root.
- JavaScript-driven navigation (`window.open`, `location = ...`,
  `location.assign`, `location.replace`) instead of ordinary external links.

## Standard deliverables
- 2-3 KPI metric tiles answering the stated question.
- 2-4 Plotly charts, each with a one-sentence insight caption: stat + caveat.
- A published artifact assembled from typed report sections and DataClaw theme
  tokens, or a canonical workspace source with publication explicitly marked
  unavailable.
- A short chat close: one or two sentences with the main answer, caveat, and
  artifact version.
- A screenshot self-check before declaring the dashboard done when browser
  tooling is available.
