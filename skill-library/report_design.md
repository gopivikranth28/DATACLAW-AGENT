---
name: report-design
description: Design polished analytical reports and upgrade legacy HTML from completed insights, aggregate assets, evidence, methodology, and interaction requirements. Use before final report generation so the agent creates a storyboard-backed, publishable report instead of appending chart dumps.
---

## When to use

Use this skill before producing any polished analytical report, dashboard, living-report artifact, or final report HTML. It owns report composition: story flow, section choice, interaction design, evidence placement, and the `report_design_report` payload contract.

Do not use this skill for a quick scratch chart or a single draft section. For that, `report_add_section` is acceptable with `quality_gate="warn"`, but it is not the final-report path.

## Required flow

1. Finish the analysis first: notebook cells, validations, EDA findings, hypothesis dispositions, aggregate tables, chart specs, caveats, evidence ids, and methodology.
2. Use completed outputs from `visualization` and `dashboarding` when those skills were already part of the analysis. If the task never did visual grammar or question-framing work, fetch the missing prerequisite before designing the final report.
3. Build a short storyboard before calling the tool:
   - answer/readout
   - headline metrics
   - primary insights
   - evidence sections
   - interactive controls
   - methodology, caveats, and evidence trace
4. Call `report_design_report`, not a sequence of final `report_add_section` calls. Inspect its `analytical_review` and quality result; resolve every `required` finding or obtain an explicit user-approved risk acceptance; resolve or explicitly disclose warnings before calling the report complete.
   The designer performs up to five bounded critique-and-repair passes, stopping early when no further safe repair is available. These passes can improve structure, captions, caveats, and evidence presentation; they never invent analytical validation or silently clear a substantive finding.
   Keep the default `design_passes=5` unless a deliberately smaller, faster draft is needed. The design passes preserve the full supplied context in the storyboard, pair insights with evidence, add local data notes, carry supplied caveats into chart interpretation, and plan visual emphasis without fabricating content.
   When supplied assets include category/archetype cards, static visual evidence, and an interactive explorer, set `requirements.editorial_archetype="taxonomy_explorer"`. It makes the page architecture deliberate: **hero → floating KPIs → taxonomy cards → hero visualization → paired diagnostics → findings → explorer → methodology and provenance footer**. The supplied readout becomes the hero abstract, so the report does not duplicate its conclusion before evidence.
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
6. For a final release, set `requirements.publication.require_visual_review=true`, inspect screenshots, then call `report_review_visuals(report_path=..., storyboard_path=..., reviewer=..., decision="approved", notes=...)`. It writes a named, hash-bound review only when browser evidence and automated semantic review pass; browser-unavailable cannot create approval, and changed HTML or screenshots require a new review.
7. Call `report_publish(report_path=..., storyboard_path=...)` after the designed report passes (and, when required, review is approved). It re-runs the fail gate, writes a receipt, and records runtime-smoke/DOCX outcomes. Pass `export_docx=False` when no Word export was requested. Do not edit HTML after: its SHA-256 and analytical-review contract are bound to publication.
8. Keep the report recipe in the notebook or source script. Designed reports also write a hash-bound `*.recipe.json` sidecar; regenerate from its storyboard/source context, never edited HTML.

### Keep the critique domain-neutral

The critique evaluates the reader's path, not the subject matter. Do not turn
one report's nouns into global defaults: a `decision_path` might be a tournament
bracket, customer journey, supply-chain route, treatment pathway, incident tree,
or staged launch. Keep specialised labels in the supplied title, caption, and
interpretation; select an editorial archetype only when the corresponding
asset shape is present. Otherwise, use the standard or `guided_explorer` flow.

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
    report_goal="Explain which customer cohorts need retention intervention and where readers should inspect the evidence.",
    title="Customer Retention Health Report",
    report_path="reports/customer-retention.html",
    storyboard_path="reports/customer-retention-storyboard.json",
    quality_gate="fail",
    design_passes=5,
    insights=[
        {
            "title": "New customers are the highest-risk renewal cohort",
            "detail": "The first-90-day cohort has the lowest renewal rate and the largest recoverable account base.",
            "finding_id": "find-new-customer-risk",
            "hypothesis_id": "hyp-onboarding-risk",
            "evidence": [{"kind": "notebook_cell", "cell_id": "cell-cohort-table"}],
            "caveat": "Renewal status is observed only for cohorts that have reached their contract anniversary.",
            "metrics": [{"label": "At-risk accounts", "value": "1,284"}],
        }
    ],
    analyses=[
        {
            "title": "Cohort health explorer",
            "caption": "Filter by customer segment or acquisition channel to inspect renewal, activation, and support burden.",
            "records": cohort_summary.to_dict("records"),
            "chart": {"type": "bar", "x": "cohort", "y": "renewal_rate", "color": "segment"},
            "columns": ["cohort", "segment", "renewal_rate", "activation_rate", "support_tickets"],
            "filters": [{"key": "segment", "label": "Customer segment"}],
            "interpretation": "The same aggregate payload drives the chart and lookup table.",
            "evidence": [{"kind": "notebook_cell", "cell_id": "cell-cohort-summary"}],
        },
        {
            "section_type": "entity_card_grid",
            "title": "Renewal segments",
            "items": segment_cards,
            "caption": "Cards summarize each segment before the reader explores individual accounts.",
        },
    ],
    requirements={
        "editorial_archetype": "taxonomy_explorer",
        "metrics": [{"label": "Accounts analyzed", "value": "12,480"}],
        "methodology": [
            {"title": "Grain", "detail": "Account-month and cohort-level aggregates."},
            {"title": "Validation", "detail": "Renewal totals reconcile across billing and customer-success tables."},
        ],
        "checks": [{"title": "No raw full dataset embedded", "status": "pass"}],
        "evidence_registry": {
            "targets": [
                {"id": "cell-cohort-table", "kind": "notebook_cell", "present": True},
                {"id": "cell-cohort-summary", "kind": "notebook_cell", "present": True},
            ],
        },
    },
)
```

## What the designer does with the payload

The designer adds contents navigation, phase kickers, local data notes, and
cross-links between evidence and insights with the same `finding_id`,
`hypothesis_id`, or evidence ref. Give every insight an honest status:
`confirmed`/`validated`, `caution`/`weakened`/`unresolved`, or
`rejected`/`blocked`.

### Editorial archetypes

`path_dependent_forecast` is for a forecast whose supplied evidence contains a
decision-path visual. It uses the neutral sequence **answer → decision path →
outcome race → mechanism → pivotal scenarios → complete lookup → trust**.
Use `story_role` values `decision_path`, `outcome_race`, `mechanism`,
`outcome_distribution`, and `complete_lookup` to identify those supplied
assets. It is not a tournament-only layout: the report's own copy names the
path, outcomes, and scenarios. Without a `decision_path` asset, the renderer
falls back to the standard sequence rather than manufacturing one.

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
            "method": "Shared-holdout log loss against a prior-period-only baseline",
            "result": "Full model improves log loss by 0.04",
            "evidence": {"kind": "notebook_cell", "ref": "cell-ablation"},
        },
        "uncertainty": {"method": "block bootstrap", "result": "90% intervals"},
        "assumptions": ["One workflow branch is inferred from historical process logs"],
        "sensitivity": {"status": "complete", "evidence": "cell-path-scenarios"},
        "decision_path": {"status": "complete", "summary": "Decision-path visual"},
        "outcome_distribution": {"status": "complete", "summary": "Outcome distribution"},
        "export_runtime": "local",
    },
}
```

The baseline is publish-blocking: it needs a completed status, a method, a
result, and an evidence reference that resolves to a registered target in
`requirements.evidence_registry.targets`, with an explicit matching `kind`.
A bare `status: complete`, prose that mentions a baseline, or an unregistered
id does not clear the gate.

Without this contract, conservative predictive cues still trigger findings for
a missing baseline, uncertainty, or assumed-input sensitivity. Path language
such as a journey, workflow, route, tree, bracket, or treatment pathway is only
an advisory: it never makes a path visual mandatory by itself. Require a
decision-path or outcome-distribution view only when the structured analysis
contract declares it or the caller explicitly selects
`editorial_archetype="path_dependent_forecast"`. Resolve findings by supplying
the completed evidence or by narrowing/disclosing the report; never mark work
complete by inventing IDs or validation results. `export_runtime="cdn"` is not
an export fix: DataClaw reports must stay self-contained.

## Section choices

Use report sections according to the job they do:

### Presentation contract

The analysis contract proves a claim; the presentation contract makes that
claim easy to read. Supply display semantics rather than asking the renderer to
invent a domain's visual language:

```python
requirements={
    "presentation": {
        "insight_layout": "editorial_list",  # default; use "card_grid" for true peer cards
        "insight_evidence": "linked",        # concise link into the paired evidence section
        "evidence_trace": "disclosure",      # keep a long trace available without dominating the story
        "require_display_facts": True,         # enforce typed source facts for runtime composition
    },
    "rigor": {
        "require_methodology": True,            # grain, denominator, validation
        "require_data_quality": True,           # visible scope/coverage disclosure
        "require_uncertainty": True,            # visible interval/confidence disclosure
        "require_component_semantics": True,    # enforce declared semantic-role components
    },
}
```

Use `card_grid` only for genuine peers. For new reports, author pills, scan
points, examples, and annotations as `display_facts`, never as prose the
renderer must mine. Every fact needs a stable `fact_id`, exact source text,
allowed `uses` (`pill`, `scan_point`, `example`, `annotation`), and preferably
an evidence ref. A data-bearing display fact's evidence must resolve through the
same `evidence_registry` as the insight or chart it supports. Legacy
`pills`/`bullets` remain compatible, but the authoring review flags them when
typed facts are required or runtime composition is used. With
`require_display_facts=True`, unresolved authoring findings block publication.
Rigor is source-declared, never inferred from prose: required methodology blocks
only when requested; predictive analysis contracts require an uncertainty disclosure.
Use `semantic_role` on an analysis (`methodology`, `data_quality`, `uncertainty`,
`provenance`, `timeline`, or `status`) to select the safe matching component.

### Runtime visual author

When a configured LLM should compose the presentation at build time, opt into
the runtime visual author. It is a visual-editor stage, not a prompt-to-HTML
stage: the model chooses a named theme, section surfaces/layouts, and supplied
facts to show as pills, scan points, examples, or small annotations. The
renderer then materializes those choices with its safe components.

```python
report_design_report(
    # ... completed insights and analyses ...
    visual_author={
        "mode": "runtime",  # use "required" to fail instead of falling back
        "facts": [
            {
                "fact_id": "renewal-rate",
                "insight_id": "find-new-customer-risk",
                "text": "61% renewal rate",
                "uses": ["pill"],
            },
            {
                "fact_id": "recoverable-base",
                "insight_id": "find-new-customer-risk",
                "text": "Largest recoverable account base",
                "uses": ["scan_point"],
            },
            {
                "fact_id": "affected-segments",
                "insight_id": "find-new-customer-risk",
                "text": "Self-serve and new enterprise accounts",
                "uses": ["example"],
            },
        ],
    },
)
```

`insight_id` is the insight's `finding_id` when present (otherwise its stable
storyboard position). For a metric row, entity grid, chart, explorer,
methodology block, or provenance section, use `section_id` (its stable
`layout_role`) instead. Set `visual_author_section_id` on an analysis when the
source recipe needs a stable explicit section id. A section can also carry its
own `display_facts`:

```python
analyses=[{
    "title": "Cohort renewal evidence",
    "visual_author_section_id": "renewal_evidence",
    "figure": figure,
    "display_facts": [
        {"fact_id": "renewal-gap", "text": "23-point renewal gap", "uses": ["scan_point"]},
        {"fact_id": "cohort-note", "text": "Observed cohorts only", "uses": ["annotation"]},
    ],
}]
```

Facts must have stable IDs, exact source text, a section or insight owner, and
explicit allowed uses; prose summaries are never eligible. The LLM response is
validated against those exact IDs and a fixed set of
surface/layout/theme choices. It cannot add claims, labels, CSS, JavaScript, or
HTML, and a fact cannot be repeated across display roles. Runtime output is
bounded by a timeout and maximum response size. A malformed response or
unavailable provider records `visual_author.status="fallback"` and renders the
original storyboard; `mode="required"` stops the build and writes a
`*.visual-author-failure.json` audit beside the storyboard. Use `mode="provided"`
with a previously validated `spec` when an auditable reproducible run must not
make an LLM call.

For a real but bounded story-order decision, set `allow_story_reorder=true` and
label consecutive source sections with both `visual_author_story_zone` and
`visual_author_story_block`. The model may reorder whole declared blocks only
within that zone; it cannot split a block or move it across another narrative
boundary. Do not enable it merely to shuffle a settled architecture.

### Surface budget

Treat cards as a scarce visual treatment, not the default wrapper for every
section. The default grammar is one strong hero, cards for KPIs and genuinely
comparable entities, a flat numbered list for primary findings, one framed
surface per chart or explorer, compact methodology cards, and a quiet
provenance disclosure. Dense card grids remain valid when the reader is
comparing peer entities. The invariant is not a fixed card count: avoid nested
surfaces unless their parent-child relationship is clear, and do not frame
purely narrative material repeatedly.

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

## Story flows

Use **answer → findings → primary evidence/explorer → trust** for an executive
readout; add a hypothesis ledger for EDA, entity cards before evidence for a
taxonomy, and **answer → supplied path → outcomes → mechanism → scenarios →
lookup → trust** for a path-dependent forecast. These are semantic sequences,
not domain labels or mandatory templates.

## Quality gate

The gate loads its criteria from the report rubric (`report_rubric.yaml`,
currently v7) — the canonical machine-readable definition of a good dataclaw
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

The live v7 rubric also reports warning-level remediation for unresolved evidence
targets, evidence-free chart conclusions, missing narrative/deks/table captions,
unpaired insights, baked chart themes, inaccessible token contrast, external
assets, typed-display-fact coverage, runtime visual-author fallback, visual-plan
budget observations, and failed or skipped runtime smoke. Browser review records
full-page desktop/mobile and desktop key-section screenshot hashes when Playwright
is available; it also checks rendered-page heading hierarchy, evidence context,
editorial findings, and nested surfaces. A final-release visual-review request
requires a named approved review record bound to that exact HTML and those screenshot hashes.
Treat warnings
as work to resolve or disclose; compatible warning
severity is not permission to ignore them.

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
