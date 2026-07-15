---
name: report_design
description: Design polished analytical reports and upgrade legacy HTML from completed insights, aggregate assets, evidence, methodology, and interaction requirements. Use before final report generation so the agent creates a storyboard-backed, publishable report instead of appending chart dumps.
---

## When to use

Use this skill before producing any polished analytical report, dashboard, living-report artifact, or final report HTML. It owns report composition: story flow, section choice, interaction design, evidence placement, and the `report_design_report` payload contract.

Do not use this skill for a quick scratch chart or a single draft section. For that, `report_add_section` is acceptable with `quality_gate="warn"`, but it is not the final-report path.

## Required flow

1. Finish the analysis first: notebook cells, validations, EDA findings, hypothesis dispositions, aggregate tables, chart specs, caveats, evidence ids, and methodology.
2. Use completed outputs from `visualization` and `dashboarding` when those skills were already part of the analysis. If the task never did visual grammar or question-framing work, fetch the missing prerequisite before designing the final report.
3. Build a short, domain-specific storyboard before calling the tool. It is a
   variable set of named reader-facing arcs, not a fixed template. For each
   arc, state the reader question, the supplied claim or topic, the primary
   visual/table/card/interaction, a concise interpretation, and any material
   caveat. Use an answer/readout, metrics, explorer, methodology, or appendix
   only when the supplied material warrants it.
   - A chart, compact table, map, comparison, or explorer is reader-facing
     evidence for an analytical claim.
   - Notebook cells, finding IDs, hypothesis IDs, query cards, and review
     records are audit provenance. Keep them in the storyboard, receipt, and
     an optional Sources & reproducibility disclosure; do not render them as
     the main report story.
   - Pass those arcs in `requirements.story_arcs` when their order should
     control the report. Each arc needs a `title`, a distinct `reader_question`
     (or `purpose`), and either explicit rendered section roles or analyses
     marked with the same `story_arc` id. Set `primary_section` when the first
     visual/table/card is not the central proof point; otherwise the compiler
     records the first supplied evidence-shaped section. Arcs remain variable
     in number and purpose; they may frame a question, comparison, mechanism,
     scenario, or decision without imposing a fixed set of acts.
   - The opening answer is the default summary. A separate `Primary insights`
     list is opt-in (`presentation.insight_summary="opening"` or
     `"after_evidence"`) and may only add a new scan-level view; it must not
     restate the same conclusion that appears beside a visual.
   - Navigation is a reader outline, not a process log. Use five to seven
     named Storyboard-v2 arcs for a substantial report; the renderer otherwise
     exposes only the answer, major evidence surfaces, and Methods & limits.
4. Call `report_design_report`, not a sequence of final `report_add_section` calls. Inspect its `analytical_review` and quality result; resolve every `required` finding or obtain an explicit user-approved risk acceptance; resolve or explicitly disclose warnings before calling the report complete.
   The designer performs up to five bounded critique-and-repair passes, stopping early when no further safe repair is available. These passes can improve structure, captions, caveats, and evidence presentation; they never invent analytical validation or silently clear a substantive finding.
   Keep the default `design_passes=5` unless a deliberately smaller, faster draft is needed. The design passes preserve the full supplied context in the storyboard, retain audit-only provenance mappings, carry supplied caveats into chart interpretation, and plan visual emphasis without fabricating content. They preserve a source-authored `data_note` but do not add generic row-count notes unless `presentation.data_notes="automatic"` is explicitly requested for a diagnostic draft. They must not create generic `Evidence 01` sections, duplicate an insight beside its supporting chart, or insert filler captions.
   When supplied assets include category/archetype cards, static visual evidence, and an interactive explorer, set `requirements.editorial_archetype="taxonomy_explorer"`. It makes the page architecture deliberate: **hero → floating KPIs → taxonomy cards → hero visualization → paired diagnostics → explorer → methodology and limitations footer**. An explicitly requested summary may appear once where its stated purpose warrants it; the supplied readout otherwise lives in the hero rather than duplicating the conclusion before analysis.
   Category-shaped selector items (`archetype`, `category`, `segment`, etc.)
   are automatically shown first as non-interactive cards while the original
   selector remains the later explorer. Reports with visual evidence and an
   explorer but no category system use the same paced `guided_explorer` flow
   without the taxonomy-card act.
   When a selector's supplied items and an aggregate chart/table share a clear
   categorical field such as `archetype`, `category`, or `segment`, the
   designer links them automatically: selection updates the matching chart,
   table, and local interpretation context. For an ambiguous or nonstandard
   relationship, set the same explicit contract on both analyses:
   `selection={"group": "player-archetype", "key": "archetype"}`. Never
   link sections by display position or manufacture rows to make a link work.
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
   The compiler also assigns every rendered section one desktop composition:
   `opening`, `headline_metrics`, `reader_readout`, `editorial_findings`,
   `guided_visual`, `interactive_explorer`, `comparison`, `trust_close`,
   `story_arc`, or `supporting`. These are layout frames, not a new rigid
   storyboard template: they make visual/evidence sections use the report
   width, keep long-form conclusions and disclosures at a readable measure,
   and prevent arbitrary narrow or floating panels. Override only a genuine
   exception with `desktop_composition` on that analysis/section. If the
   supplied evidence genuinely needs a non-default `layout_width`, add
   `layout_exception={"width": "…", "reason": "…"}`; the reason is retained
   for visual review. Do not use pixel offsets or a custom CSS width to
   compensate for a weak story order.
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

The designer preserves the provenance links between insights and the supplied
analysis assets, but it does not expose opaque IDs, `Evidence for` backlinks,
or copied insight cards in the reader path. Keep an honest internal status for
every insight. In a final report, render only statuses that change
interpretation—such as `caution`, `weakened`, `unresolved`, or `blocked`—not
routine `confirmed` or `validated` badges.

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
At publish time, desktop browser checks (one 1440×900 Chromium viewport, when
Playwright is available) verify rendering outcomes only: horizontal overflow,
viewport clipping, chart mounts, diagnostic-grid integrity, floating-KPI
anchoring, blank interactive tables, and a compositor screenshot. Prescriptive
template checks (composition widths, section spacing, interpretation-rail
ratios, card density) were removed — composition quality is the vision
review's job (docs/report-design-variance.md, D5). An unavailable browser, or
a browser run exceeding the 20-second publish budget, is recorded as an
explicit skipped/review-info result rather than a fake pass; design warnings
are publish-blocking until the report is redesigned from its supplied assets.

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
both an `analysis_review` and a `claim_contract` in `requirements`. The
claim contract maps every material reader claim to one primary visual/table,
its scope, caveat, and registered provenance; it is audit metadata, not a
reader-visible evidence chip. The storyboard critique persists
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
        "validation": {
            "status": "complete",
            "split": "time-ordered held-out weeks",
            "metric": "Brier score 0.14 against 0.19 baseline",
            "calibration": {"status": "complete", "result": "Reliability slope 0.97"},
            "evidence": {"kind": "notebook_cell", "ref": "cell-ablation"},
        },
        "uncertainty": {"method": "block bootstrap", "result": "90% intervals"},
        "assumptions": ["One workflow branch is inferred from historical process logs"],
        "sensitivity": {"status": "complete", "evidence": "cell-path-scenarios"},
        "decision_path": {"status": "complete", "summary": "Decision-path visual"},
        "outcome_distribution": {"status": "complete", "summary": "Outcome distribution"},
        "export_runtime": "local",
    },
    "claim_contract": {
        "claims": [{
            "id": "champion-odds",
            "text": "Spain lead the completed forecast, within its stated uncertainty.",
            "claim_type": "predictive",
            "primary_section": "analysis_1_chart_interpretation",
            "scope": "The completed forecast input and declared holdout only.",
            "caveat": "Unplayed fixtures and model assumptions can change the estimate.",
            "uncertainty": {"status": "complete", "method": "block bootstrap"},
            "evidence": {"kind": "notebook_cell", "ref": "cell-ablation"},
        }],
    },
}
```

The baseline and validation are publish-blocking: a baseline needs a completed
status, method, result, and registered evidence; validation additionally needs
a split/holdout or resampling rationale, metric/result, completed calibration
or reliability result, and registered evidence. A bare `status: complete`,
prose that mentions a baseline, or an unregistered id does not clear the gate.
Predictive and scenario claims also require a scope, caveat, uncertainty, a
primary reader-evidence section, and a matching `claim_id` or `claim_ids` on
that chart/table/explorer. A causal claim additionally needs a declared causal
design; association alone cannot be published as causal.

Without this contract, conservative predictive cues trigger required findings
for a missing claim contract, baseline, validation, uncertainty, or
assumed-input sensitivity. Path language such as a journey, workflow, route,
tree, bracket, or treatment pathway is only an advisory. Once the structured
analysis contract declares a decision path—or the caller selects
`editorial_archetype="path_dependent_forecast"`—a supplied decision-path visual
is required; a stage bar alone does not satisfy it. Resolve findings by
supplying the completed evidence or by narrowing/disclosing the report; never
mark work complete by inventing IDs or validation results.

## Section choices

Use report sections according to the job they do:

### Presentation contract

The analysis contract proves a claim; the presentation contract makes that
claim easy to read. Supply display semantics rather than asking the renderer to
invent a domain's visual language:

```python
requirements={
    "presentation": {
        "insight_summary": "none",           # default; opening answer carries the conclusion
        "insight_layout": "editorial_list",  # default; use "card_grid" for true peer cards
        "insight_evidence": "none",          # source IDs are not reader-facing evidence
        "provenance": "audit",               # use "disclosure" only for an optional Sources appendix
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

Use `card_grid` only for genuine peers, and only when `insight_summary` is
explicitly enabled. For new reports, author pills, scan
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

Every report starts with the renderer's deterministic desktop-editorial
baseline (semantic composition frames, hierarchy, evidence surfaces, and
Plotly theming). It is recorded in the storyboard/receipt even when runtime
visual authoring is off. This baseline is the reproducible default; it does
not require an LLM.

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
- `evidence_trace` and `evidence_rail` only for an explicitly requested
  Sources & reproducibility disclosure. Keep notebook cells, filter IDs,
  artifact IDs, findings, and review references out of the main narrative.
- `hypothesis_ledger` and `ledger_timeline` for EDA hypotheses, dispositions,
  supersessions, risk acceptance, and review chronology.

Use plain `chart` only as supporting material when interpretation and provenance
are already next to it. A report with several plain charts and no explorer is a
failed report shape.

## Story flows

Use **answer → primary evidence/explorer → methods and limits** for an
executive readout; add a deliberately non-overlapping summary only when it
helps scanning. Add a hypothesis ledger for EDA, entity cards before evidence
for a taxonomy, and **answer → supplied path → outcomes → mechanism →
scenarios → lookup → trust** for a path-dependent forecast. These are semantic
sequences, not domain labels or mandatory templates.

## Quality gate

The gate loads its criteria from the report rubric (`report_rubric.yaml`,
currently v8) — the canonical machine-readable definition of a good dataclaw
report. Every quality result cites the `rubric_version` it was judged by.
Before calling a report complete, the quality result must not include any
fail-severity code (these block `quality_gate="fail"` and publication):

- `consecutive_plain_charts`
- `chart_dump`
- `plain_chart_overuse`
- `missing_interactive_explorer` (applies at ≥6 sections with ≥3 chart-like sections)
- `missing_primary_insights`
- `missing_insight_sections`
- `stale_installed_skills`
- `oversized_report`
- `unstructured_report` (a passing verified-freeform fact contract satisfies
  this in place of typed section metadata)

and treat these warn-severity codes as work to resolve or disclose before
presenting the report — they do not mechanically block, which is not
permission to ignore them:

- `unsourced_claim` (formerly `missing_evidence_ids`)
- `chart_interpretation_missing_evidence`
- `missing_table_caption`

If any of these appear, revise the storyboard or analysis payloads. Do not
present a failed report as complete.

The live v8 rubric also reports warning-level remediation for unresolved evidence
targets, evidence-free chart conclusions, missing narrative/deks/table captions,
unpaired insights, baked chart themes, inaccessible token contrast, external
assets, typed-display-fact coverage, runtime visual-author fallback, visual-plan
budget observations, and failed or skipped runtime smoke. Browser review records
full-page desktop and desktop key-section screenshot hashes when Playwright
is available; it also checks rendered-page heading hierarchy, evidence context,
editorial findings, and nested surfaces. A final-release visual-review request
requires a named approved review record bound to that exact HTML and those screenshot hashes.
Treat warnings
as work to resolve or disclose; compatible warning
severity is not permission to ignore them.

## Design variance & verified-freeform

The renderer varies output deterministically so reports stop looking like one
template (docs/report-design-variance.md):

- **Semantic color bindings.** An entity (card title or chart trace name)
  appearing in two or more sections is bound to a stable `--dc-cat-N`
  categorical slot; its entity-card accent and every chart trace that names it
  render in the same theme-reactive hue. Bindings are stored on the storyboard
  as `color_bindings`; an explicit `accent_color` always wins.
- **Interpretation placement.** A chart's interpretation lays out by content
  shape: one short sentence renders as an unlabeled caption; 2–5 discrete
  `takeaways` render as a numbered "What this reveals" panel; a
  `display_facts` entry with `use: "annotation"` plus coordinates (`x`/`y`, or
  `axis` + `value`) is drawn inside the figure as an append-only reference
  line/label; long-form prose or caveats/evidence keep the side rail. Set
  `interpretation_placement` (`caption`, `takeaway_panel`, `side_rail`,
  `figure_annotation`) on the section data to override; the runtime visual
  author may also choose it per chart section.
- **Components.** `callout` accepts `layout_variant: "note"` with an optional
  `tone` (`good`/`warn`/`danger`/`neutral`) for a compact tinted aside; a
  `layout_group` pair accepts `layout_group_ratio: "60-40"` or `"40-60"` for
  asymmetric splits.
- **Seeded art direction.** When neither the author nor the visual author sets
  a theme, the render derives one deterministically from the report's
  title/goal, from eight curated palettes (`blue`, `ocean`, `forest`, `plum`,
  `slate`, `ember`, `indigo`, `crimson`) — regeneration reproduces the choice.
- **Archetype aliases.** `editorial_archetype` also accepts the aliases
  `archetype_explorer`/`editorial` (→ `taxonomy_explorer`),
  `guided_argument` (→ `guided_explorer`), and `forecast_knockout`/
  `scenario_path_forecast`/`decision_path_forecast`
  (→ `path_dependent_forecast`). Top-level
  `requirements.require_visual_review` is a legacy alias for
  `requirements.publication.require_visual_review`.
- **Verified-freeform tier.** A freeform-authored page (bespoke HTML/CSS) is
  publishable through `build_report(html=..., facts=[{fact_id, text}, ...])`:
  the page is preserved byte-for-byte as the report, every displayed
  number/claim must sit in an element carrying `data-fact-id` whose visible
  text carries the contract fact verbatim, and numerals outside any binding
  fail the gate. Verification is fail-closed at build time and recomputed at
  publish. A `preserved_low_confidence` normalization without a fact contract
  is mechanically blocked at publish — the fact contract is its upgrade path.

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
