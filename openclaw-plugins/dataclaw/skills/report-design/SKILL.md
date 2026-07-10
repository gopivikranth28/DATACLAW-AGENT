---
name: report_design
description: Design polished analytical reports from completed insights, aggregate assets, evidence, methodology, and interaction requirements. Use before final report generation so the agent storyboards layout, sections, controls, and quality gates instead of appending chart dumps.
tags: [reporting, report-design, dashboarding, visualization, artifacts]
---

## When to use

Use this skill before producing any polished analytical report, dashboard,
living-report artifact, or final report HTML. This skill owns report composition:
story flow, section choice, interaction design, evidence placement, and the
payload contract for `report_design_report`.

Do not use this skill for a quick scratch chart or a single draft section. For
that, `report_add_section` is acceptable with `quality_gate="warn"`, but it is
not the final-report path.

## Required flow

1. Finish the analysis first: notebook cells, validations, EDA findings,
   hypothesis dispositions, aggregate tables, chart specs, caveats, evidence ids,
   and methodology.
2. Use the completed outputs from `visualization` and `dashboarding` when those
   skills were already part of the analysis. If the task never did visual grammar
   or question-framing work, fetch the missing prerequisite before designing the
   final report.
3. Build a short storyboard before calling the tool:
   - answer/readout
   - headline metrics
   - primary insights
   - evidence sections
   - interactive controls
   - methodology, caveats, and evidence trace
4. Call `report_design_report`, not a sequence of final `report_add_section`
   calls.
5. Keep `quality_gate="fail"` for final reports. Fix failures before presenting
   the report as complete.
6. Keep the report recipe in the notebook or a source script so the artifact can
   be regenerated.

## Report tool contract

Call `report_design_report` with completed material:

```python
report_design_report(
    report_goal="Explain the World Cup performance story and where readers should inspect teams and players.",
    title="FIFA World Cup 2026 Performance Report",
    report_path="reports/wc26-performance.html",
    storyboard_path="reports/wc26-performance-storyboard.json",
    quality_gate="fail",
    insights=[
        {
            "title": "France and Argentina are the class of the field",
            "detail": "Both are perfect on points; France combines top scoring with the tightest defense.",
            "finding_id": "find-perfect-teams",
            "hypothesis_id": "hyp-contenders",
            "evidence": [{"kind": "notebook_cell", "cell_id": "cell-team-table"}],
            "caveat": "Only completed matches through the Round of 16 are included.",
            "metrics": [{"label": "Perfect teams", "value": "2"}],
        }
    ],
    analyses=[
        {
            "title": "Team performance explorer",
            "caption": "Filter by confederation or stage to inspect points, xG, and finishing.",
            "records": team_summary.to_dict("records"),
            "chart": {"type": "bar", "x": "team", "y": "points", "color": "confederation"},
            "columns": ["team", "confederation", "points", "goal_difference", "xg_for", "xg_against"],
            "filters": [{"key": "confederation", "label": "Confederation"}],
            "interpretation": "The same aggregate payload drives the chart and lookup table.",
            "evidence": [{"kind": "notebook_cell", "cell_id": "cell-team-summary"}],
        },
        {
            "section_type": "entity_card_grid",
            "title": "Player archetypes",
            "items": archetype_cards,
            "caption": "Cards summarize each archetype before the reader explores individual players.",
        },
    ],
    requirements={
        "metrics": [{"label": "Matches analyzed", "value": "96"}],
        "methodology": [
            {"title": "Grain", "detail": "Team-match and player-tournament aggregates."},
            {"title": "Validation", "detail": "Goal totals reconcile across match, event, and player tables."},
        ],
        "checks": [{"title": "No raw full dataset embedded", "status": "pass"}],
    },
)
```

## Asset shapes the designer understands

Give the designer typed, aggregate assets. The section choice is driven by the
shape of each `analyses` item:

- `records` or `rows` plus `chart` -> `chart_table_explorer` when columns,
  filters, or many records are present.
- `records` plus `chart` with a small payload -> `filterable_chart`.
- `rows` plus `columns` -> `interactive_table`.
- `figure` or `figure_json` -> `chart_interpretation`.
- `items` or `entities` -> `entity_card_grid`.
- explicit `section_type` or `kind` -> use that section type.

Prefer aggregate, ranked, or sampled records. Do not embed raw full datasets,
connection strings, secrets, or large unbounded row sets.

## Section choices

Use report sections according to the job they do:

- `narrative_band` for the answer, revised interpretation, or caveat turn.
- `insight_grid` for the 3-7 findings that change the user's answer.
- `chart_interpretation` for a conclusion-bearing chart with evidence and caveat.
- `chart_table_explorer` when a chart and searchable table should inspect the
  same aggregate payload.
- `filterable_chart` when the same chart should respond to controls.
- `interactive_table` when lookup, sorting, search, or column filters matter.
- `selector_panel` when a team, player, cohort, model, or scenario selector
  changes adjacent evidence.
- `entity_card_grid` for archetypes, segments, cohorts, players, models, or
  scenarios.
- `methodology_block` for grain, denominator, validation, review method, and
  assumptions.
- `evidence_trace` and `evidence_rail` for claims that need notebook cell,
  filter, artifact, finding, or review references.
- `hypothesis_ledger` and `ledger_timeline` for EDA hypotheses, dispositions,
  supersessions, risk acceptance, and review chronology.

Use plain `chart` only as supporting material when interpretation and provenance
are already next to it. A report with several plain charts and no explorer is a
failed report shape.

## Layout recipes

### Executive analytical report

1. Header with objective and scope.
2. KPI row with 2-5 headline numbers.
3. `narrative_band` answering the primary question.
4. `insight_grid` with evidence, confidence/status, caveat, and next action.
5. One primary `chart_table_explorer` or `chart_interpretation`.
6. Supporting `interactive_table`, `filterable_chart`, or `entity_card_grid`.
7. `methodology_block`, `evidence_trace`, caveats, and next steps.

### Structured EDA report

1. Objective, unit of observation, row/column coverage, and data quality risk.
2. Hypothesis ledger with dispositions.
3. Insight grid of confirmed or materially useful findings.
4. Evidence sections paired with chart interpretation or explorers.
5. Readiness/checklist section.
6. Methodology, caveats, blocked claims, and evidence trace.

### Player/archetype or segment report

1. Define the archetypes/segments in cards.
2. Show a map or fingerprint view with interpretation.
3. Add a selector or explorer for "find similar" or "compare entities".
4. Close with caveats, feature set, validation, and evidence trace.

## Quality gate

Before calling a report complete, the quality result must not include:

- `consecutive_plain_charts`
- `chart_dump`
- `plain_chart_overuse`
- `missing_interactive_explorer`
- `missing_primary_insights`
- `missing_insight_sections`
- `missing_evidence_ids`
- `missing_table_caption`
- `stale_installed_skills`
- `oversized_report`

If any of these appear, revise the storyboard or analysis payloads. Do not
present a failed report as complete.

## Anti-patterns

- Building the final report with repeated `report_add_section(section_type="chart")`.
- Saving final charts as PNGs when Plotly/report sections are available.
- A long findings list with no evidence ids, caveats, or adjacent chart/table.
- Separate static charts where one explorer with filters would answer better.
- A methodology callout at the end that should have been beside the evidence.
- Report assembly logic that exists only as transient tool calls.

`report_add_section` is a compatibility and draft helper. Use
`quality_gate="warn"` for scratch sections; the polished final report path is
`report_design_report` plus the returned storyboard JSON.
