---
name: dashboarding
description: Compose a clear, non-misleading artifact dashboard/report that directly answers a stated question, using the visualization skill for visual grammar and dataclaw-artifacts for publishing, versioning, security, and export.
tags: [visualization, dashboarding, reporting, charts, artifacts]
---

## When to use
The user has a dataset and a specific question, and wants a clean, shareable
visual answer - "build a dashboard", "show me who/what/when", "visualize this",
"give me a report". Use this skill to decide the story and layout. Use the
`visualization` skill for the visual evidence, and fetch the `report_design`
skill before final report generation. Use artifacts as the final published
surface.

Do not leave the final answer as loose charts, App-panel state, or a long chat
message. The final visual deliverable should be a published artifact or a living
report entry. `/app/:sessionId` is only a compatibility scratch view for loose
visual outputs; do not use it as the final dashboard/report surface.

Publish a standalone report/dashboard/chart page with `publish_artifact`. Use
living-report notes for interpretation, decisions, rationale, and direction
changes that accumulate during the investigation.

## Skill triad
- `dashboarding` scopes the decision and composes the storyboard.
- `report_design` owns the final report design pass: section mix, controls,
  evidence placement, methodology layer, storyboard JSON, and quality gate.
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
  coverage gaps, and the structured EDA readiness verdict as the canonical
  readiness source.
- **Exploratory briefing** - ranked findings from the EDA findings ledger,
  evidence chart per finding, and "what to investigate next".

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
   narrative band, primary `chart_interpretation` or `chart_table_explorer`,
   supporting interactive tables/selectors, methodology block, evidence rail,
   ledger/timeline, caveats, next steps, and appendix. The storyboard should
   name the executive readout, primary insight, supporting evidence, caveats,
   methodology, and any controls the reader needs.
5. **Aggregate data** - compute summary series in pandas/polars. Never embed raw
   datasets in the dashboard artifact. The 25 MiB cap applies to published/exported
   single-file artifacts, not the living-report manifest store.
6. **Visual evidence** - follow `visualization`: Plotly via `fig.show()`, KPIs
   via `display_metric`, captions via `display_cell_output`, and completed
   insights/assets/evidence for the report designer.
7. **Report design pass** - after the analysis is complete, fetch and follow the
   `report_design` skill, then call `report_design_report` with the final
   insights, aggregate analysis payloads, methodology, hypotheses, evidence,
   and interaction requirements. Do not treat appended report cells as the final
   dashboard/report architecture. Then call `report_publish` with the returned
   HTML and storyboard paths (use `export_docx=False` unless Word output was
   requested) before artifact publication.
8. **Artifact assembly** - the designer should assemble `header`, `metric_row`, `narrative_band`,
   `chart_interpretation`, `chart_table_explorer`, `filterable_chart`,
   `interactive_table`, `selector_panel`, `entity_card_grid`,
   `methodology_block`, `evidence_rail`, `ledger_timeline`, `chart`, `table`,
   `findings`, `callout`, and `text` sections into a report HTML source. Keep
   report assembly calls in the notebook or a source script so the dashboard can
   be regenerated.
9. **Publish or revise** - inspect the `report_publish` receipt, then fetch and follow the `artifacts` skill and call `publish_artifact(source_path=..., title=...)`.
   For edits, read/revise the canonical source, re-run the report publish gate,
   and publish with the same `artifact_id` and `base_version`. If artifact tools
   are unavailable, keep the canonical source in the workspace and say
   publication is unavailable; do not invent an id, version, or URL.
10. **Audit and self-check** - run the pitfalls checklist. When browser tooling is
   available, screenshot the artifact in light and dark mode before closing the
   plan step. Run the report-quality gate and address stale skills, chart dumps,
   missing evidence ids, missing captions, and oversized embedded HTML/data
   before publishing.

## Layout rules
- Put the answer first: headline, 2-3 KPI tiles, and the primary chart above the
  fold.
- Use 2-4 charts for most dashboards. More charts require a report structure,
  not a denser grid.
- One chart per sub-question. Prefer a filtered chart over near-duplicates.
- When the reader needs lookup or slicing, use report-level controls:
  `filterable_chart`, `interactive_table`, `selector_panel`, or
  `chart_table_explorer`. Controls should sit beside the evidence they affect.
- For domain-specific reports, build the obvious explorer: team comparison,
  player leaderboard filters, stage/confederation filters, archetype/player
  similarity selector, champion scenario controls, cohort/model selectors, or
  metric/ranking toggles.
- Use tables only when exact values or auditability matter.
- Put caveats next to the evidence they qualify, not at the end where they will
  be missed. Use `chart_interpretation` and `evidence_rail` for this pairing.
- Use `methodology_block` for grain, denominator, validation, and review method;
  use `ledger_timeline` when the reader needs to understand how a conclusion
  evolved.
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
- Missing report-level controls when the analysis naturally supports slicing,
  selection, lookup, scenarios, or leaderboard exploration.
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
