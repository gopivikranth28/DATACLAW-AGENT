---
name: report_design
description: Design polished analytical reports and upgrade legacy HTML from completed insights, aggregate assets, evidence, methodology, and interaction requirements. Use before final report generation so the agent creates a storyboard-backed, publishable report instead of appending chart dumps.
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
   calls. Inspect its `analytical_review` as well as its quality result; resolve
   every `required` finding or obtain an explicit user-approved risk acceptance;
   resolve or explicitly disclose warnings before calling the report complete.
   The designer performs up to five bounded critique-and-repair passes, stopping
   early when no further safe repair is available. These passes can improve
   structure, captions, caveats, and evidence presentation; they never invent
   analytical validation or silently clear a substantive finding.
   Keep the default `design_passes=5` unless a deliberately smaller, faster
   draft is needed. The design passes preserve the full supplied context in the
   storyboard, pair insights next to the evidence they explain, add local data
   notes, carry supplied caveats into chart interpretation, and plan visual
   emphasis without fabricating content.
   When the supplied assets include category/archetype cards, static visual
   evidence, and an interactive explorer, set
   `requirements.editorial_archetype="taxonomy_explorer"`. It makes the page
   architecture deliberate: **hero → floating KPIs → taxonomy cards → hero
   visualization → paired diagnostics → findings → explorer → methodology and
   provenance footer**. The supplied readout becomes the hero abstract, so the
   report does not duplicate its conclusion before evidence.
   Category-shaped selector items (`archetype`, `category`, `segment`, etc.)
   are automatically shown first as non-interactive cards while the original
   selector remains the later explorer. Reports with visual evidence and an
   explorer but no category system use the same paced `guided_explorer` flow
   without the taxonomy-card act.
   After the generic critique, the designer runs five page-architecture checks:
   sequence restoration, visual hierarchy, local chart context,
   evidence/explorer pacing, and a final architecture audit. The returned
   `design_review` records every pass, safe repair, and unresolved design risk.
   It may only reorder supplied sections or restore presentation metadata; a
   missing visual, KPI, methodology note, or explorer remains a finding rather
   than fabricated content.
   Hero and comparison intent should be explicit when input order is not the
   intended story order: set `editorial_role="hero"` (or a lower
   `story_priority`) on the central visual, and the same `diagnostic_group` or
   `comparison_group` on charts that belong in a two-column diagnostic pair.
5. Keep `quality_gate="fail"` for final reports. Fix failures before presenting
   the report as complete.
6. Call `report_publish(report_path=..., storyboard_path=...)` after the designed
   report passes. It re-runs the current fail gate, writes a publish receipt, and
   records runtime-smoke and DOCX export outcomes. Pass `export_docx=False` when
   no Word export was requested.
   Do not edit the report HTML after this step: the receipt records its exact
   SHA-256 and artifact publication rejects a changed structured report. The
   analytical-review contract is also bound to the rendered report; redesign if
   the completed work changes.
7. Keep the report recipe in the notebook or a source script so the artifact can
   be regenerated.

## Upgrade an existing HTML report

Use `build_report` for existing HTML rather than rewriting it or appending draft
sections. It preserves the original as a sibling `.source.html`, creates a
storyboard, runs the bounded critique, and returns `normalization`, `critique`,
and `quality` records.

```python
build_report(
    html_path="legacy/customer-retention.html",
    output_path="reports/customer-retention.html",
    storyboard_path="reports/customer-retention.storyboard.json",
    report_goal="Explain which customer cohorts need retention action.",
    audience="Retention leadership",
    quality_gate="warn",
)
```

Publish only a `normalization.mode == "structured_rebuild"` or
`"typed_preservation"` result, with its returned HTML and storyboard paths.
`"preserved_low_confidence"` deliberately keeps unsupported source elements in
the source file; recreate that report from typed insights and aggregate assets
with `report_design_report` before publication. Never treat source preservation
as proof that a legacy report passed the structured publish gate.

## Report tool contract

Call `report_design_report` with completed material:

```python
report_design_report(
    report_goal="Explain the World Cup performance story and where readers should inspect teams and players.",
    title="FIFA World Cup 2026 Performance Report",
    report_path="reports/wc26-performance.html",
    storyboard_path="reports/wc26-performance-storyboard.json",
    quality_gate="fail",
    design_passes=5,
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
        "editorial_archetype": "taxonomy_explorer",
        "metrics": [{"label": "Matches analyzed", "value": "96"}],
        "methodology": [
            {"title": "Grain", "detail": "Team-match and player-tournament aggregates."},
            {"title": "Validation", "detail": "Goal totals reconcile across match, event, and player tables."},
        ],
        "checks": [{"title": "No raw full dataset embedded", "status": "pass"}],
        "evidence_registry": {
            "targets": [
                {"id": "cell-team-table", "kind": "notebook_cell", "present": True},
                {"id": "cell-team-summary", "kind": "notebook_cell", "present": True},
            ],
        },
    },
)
```

## What the designer does with the payload

`report_design_report` builds a report with a left contents rail (scroll-spy,
numbered sections, anchor deep-links), phase kickers ("At a glance", "What
changed", "Evidence NN", "Method & trust"), and a hero treatment on the first
chart-bearing analysis.

Insights and evidence sections are cross-linked automatically: an insight whose
`finding_id`, `hypothesis_id`, or evidence refs (e.g. notebook `cell_id`)
overlap with an analysis gets a "See the evidence" anchor into that section,
and the section gets a backlink chip. **Carry the same `finding_id` /
`hypothesis_id` / evidence `cell_id` on both the insight and its analysis
asset** — that shared provenance is what drives the pairing. An insight with no
overlapping refs renders unlinked, which reads as an unsupported claim.

Statuses color the insight cards: `confirmed`/`validated` green,
`caution`/`weakened`/`unresolved` amber, `rejected`/`blocked` red. Give every
insight an honest status.

### Editorial archetypes

`taxonomy_explorer` is the recommended option for analytical reports that need
to introduce a category system before showing evidence and offering reader-led
inspection. It is used only when the payload supplies all three necessary
assets: an `entity_card_grid`, one or more non-interactive chart sections, and an interactive
section. The renderer then gives the hero a dark editorial treatment, lets the
KPI row overlap it, groups the first two diagnostics in a two-column grid, and
keeps the findings after the evidence. It preserves the original inputs and
the absorbed readout in the storyboard's `source_context` and header metadata.
Every `report_design_report` result also exposes `design_review`; the report UI
shows unresolved architecture warnings separately from analytical findings.
At publish time, responsive browser checks verify desktop/mobile overflow,
diagnostic columns, floating-KPI anchoring, chart mounts, and a compositor
screenshot when Playwright Chromium is available. An unavailable browser is
recorded as an explicit review-info finding; design warnings are publish-blocking
until the report is redesigned from its supplied assets.

```python
analyses=[
    {
        "title": "Central comparison",
        "figure": figure,
        "interpretation": "The central evidence-backed conclusion.",
        "evidence": [{"kind": "notebook_cell", "ref": "cell-central"}],
        "editorial_role": "hero",
    },
    {
        "title": "Diagnostic A",
        "figure": diagnostic_a,
        "interpretation": "The first comparable diagnostic.",
        "evidence": [{"kind": "notebook_cell", "ref": "cell-diagnostic-a"}],
        "diagnostic_group": "finishing",
    },
    {
        "title": "Diagnostic B",
        "figure": diagnostic_b,
        "interpretation": "The second comparable diagnostic.",
        "evidence": [{"kind": "notebook_cell", "ref": "cell-diagnostic-b"}],
        "diagnostic_group": "finishing",
    },
]
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

When an insight or analysis cites evidence, provide an explicit registry in
`requirements.evidence_registry.targets`, for example
`{"id": "cell-team-summary", "kind": "notebook_cell", "present": true}`.
Every `evidence`/`evidence_refs` entry must use the same `kind` and `ref` (or
`cell_id`/`artifact_id`) so the report can resolve it. Do not invent ids to
satisfy the gate.

### Analytical critique contract

For a forecast, prediction, simulation, or other model-based report, include
an `analysis_review` object in `requirements`. The storyboard critique persists
its findings in the returned `critique`, storyboard JSON, and publish receipt.
It does not rerun the model or invent support; it flags missing declared work
so the agent can add it before calling the report complete. A `required`
finding blocks `report_publish` until it is remediated or explicitly accepted
by the user with a rationale; warnings must be resolved or disclosed.

Each emitted report finding is also recorded in the shared analysis-review
lifecycle and returned as `review_lifecycle`, with a `review_finding_id` and
status on the report finding itself. Use `resolve_review_finding` to record a
real resolution (with supporting evidence when applicable) or an
`accepted_with_rationale` risk decision.
The latter requires explicit user approval through the review guardrail and is
preserved in the publish receipt and report UI.

```python
requirements={
    "evidence_registry": {
        "targets": [
            {"id": "cell-ablation", "kind": "notebook_cell", "present": True},
            {"id": "cell-pairing-scenarios", "kind": "notebook_cell", "present": True},
        ],
    },
    "analysis_review": {
        "mode": "predictive",
        "baseline": {
            "status": "complete",
            "method": "Shared-holdout log loss against Elo-only",
            "result": "Full model improves log loss by 0.04",
            "evidence": {"kind": "notebook_cell", "ref": "cell-ablation"},
        },
        "uncertainty": {"method": "block bootstrap", "result": "90% intervals"},
        "assumptions": ["Two bracket pairings are inferred from R16 adjacency"],
        "sensitivity": {"status": "complete", "evidence": "cell-pairing-scenarios"},
        "decision_path": {"status": "complete", "summary": "Bracket visual"},
        "outcome_distribution": {"status": "complete", "summary": "Scoreline heatmaps"},
        "export_runtime": "local",
    },
}
```

The baseline is publish-blocking: it needs a completed status, a method, a
result, and an evidence reference that resolves to a registered target in
`requirements.evidence_registry.targets`, with an explicit matching `kind`.
A bare `status: complete`, prose that mentions a baseline, or an unregistered
id does not clear the gate.

Without this contract, conservative forecast/tournament cues still trigger
findings for a missing baseline, uncertainty, assumed-input sensitivity,
bracket/tree visual, or outcome-distribution visual. Resolve those by supplying
the completed evidence or by narrowing/disclosing the report; never mark work
complete by inventing IDs or validation results. `export_runtime="cdn"` is not
an export fix: DataClaw reports must stay self-contained.

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

The gate loads its criteria from the report rubric (`report_rubric.yaml`,
currently v3) — the canonical machine-readable definition of a good dataclaw
report. Every quality result cites the `rubric_version` it was judged by.
Before calling a report complete, the quality result must not include:

- `consecutive_plain_charts`
- `chart_dump`
- `plain_chart_overuse`
- `missing_interactive_explorer`
- `missing_primary_insights`
- `missing_insight_sections`
- `unsourced_claim` (formerly `missing_evidence_ids`)
- `chart_interpretation_missing_evidence`
- `missing_table_caption`
- `stale_installed_skills`
- `oversized_report`
- `unstructured_report`

If any of these appear, revise the storyboard or analysis payloads. Do not
present a failed report as complete.

The live v3 rubric also reports warning-level remediation for unresolved evidence
targets, evidence-free chart conclusions, missing narrative/deks/table captions,
unpaired insights, baked chart themes, inaccessible token contrast, external
assets, and failed or skipped runtime smoke. Treat those as work to resolve or
disclose; their compatible warning severity is not permission to ignore them.

## Anti-patterns

- Building the final report with repeated `report_add_section(section_type="chart")`.
- Saving final charts as PNGs when Plotly/report sections are available.
- A long findings list with no evidence ids, caveats, or adjacent chart/table.
- Separate static charts where one explorer with filters would answer better.
- A methodology callout at the end that should have been beside the evidence.
- Report assembly logic that exists only as transient tool calls.

`report_add_section` is a compatibility and draft helper. Use
`quality_gate="warn"` for scratch sections; the polished final report path is
`report_design_report`, its returned storyboard JSON, and `report_publish`.
