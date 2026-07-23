---
name: report_design
description: Author and publish bespoke analytical reports from validated findings, bounded aggregate evidence, methodology, caveats, and an evidence ledger. Use for final reports, report-like dashboards, interactive analytical briefings, or redesigning existing report HTML; the creative author owns all unspecified story, prose, layout, and visual decisions.
---

## Role

Use this skill as the sole final-report composition layer. It owns the story,
prose, hierarchy, visual forms, interactions, evidence placement, HTML, review,
and publication handoff.

`visualization` is optional upstream support for notebook charts and evidence
preparation. It is not a prerequisite when validated findings and aggregate
outputs already exist. Do not fetch a separate dashboard-layout skill.

Do not pre-compose a final page from component names. Do not specify KPI/chart
counts, fixed archetypes, visual types, or section order unless they are genuine
user or analytical requirements. The author should receive evidence and
constraints, not a nearly completed layout.

## Required handoff

Finish the analysis before authoring. Give `report_design_report` enough detail
to write independently without inventing facts:

- `report_goal` and the intended `audience` or decision;
- completed insights with a stable `finding_id` (and `hypothesis_id` when
  applicable), validated statement, claim scope/status, metrics where relevant,
  caveat, and evidence references;
- bounded aggregate analyses with title/topic, records or compact figure,
  semantic relationship, grain, scope, units, denominator, field definitions,
  filters, baseline, interpretation, caveat, `claim_source_id`, and evidence
  references. Set `required_visual: true` only when that exact asset must appear
  as a reader-facing figure; it then may not be omitted and is rendered as a
  figure/SVG/canvas. For a custom visual beyond the familiar charts and the
  governed advanced forms, describe intent in free-text `visual_direction` (see
  Bespoke per-asset visuals);
- methodology, data-quality limits, uncertainty, assumptions, definitions, and
  coverage risks;
- a non-empty evidence ledger in
  `requirements.evidence_registry.targets`, with matching typed references. This
  ledger is required: `report_design_report` raises without it, and authoring is
  fail-closed with no fallback to a non-authored report;
- optional hard constraints: required controls, brand, design brief, or explicit
  story arcs.

Audience, decision, time scope, comparison baseline, grouping, and required
lookup/filter tasks are report inputs. Put them in the goal, analyses, or
requirements rather than using a separate dashboard-planning stage.

Use aggregate, ranked, or sampled records. Never include raw full datasets,
credentials, connection strings, PII, or unbounded row collections.

## Default flow

1. Assemble completed findings, aggregates, trust material, and evidence
   targets. Do not manufacture ids or validation results to satisfy the gate.
2. Call `report_design_report` with `quality_gate="fail"` and the full handoff.
   Every report is a single handcrafted, creative, evidence-bound visual
   document authored by the ledger-backed creative author; there is no
   presentation mode to select.
3. Inspect `analytical_review`, `design_review`, `authoring_review`, source
   coverage, evidence-review status, and quality. Resolve required analytical
   findings with real evidence or obtain explicit user-approved risk acceptance.
   Treat design, layout, chart-variety, and story-arc warnings as editorial
   advice unless the user explicitly made one a requirement.
4. Only when the user explicitly requests named visual approval, set
   `requirements.publication.require_visual_review=true`, inspect the desktop
   screenshots and call `report_review_visuals` with a named reviewer, decision,
   and rationale. Visual review is otherwise off, including for handcrafted reports.
5. Call `report_publish(report_path=..., storyboard_path=...,
   export_docx=False)` unless Word output was requested and supported. It
   re-runs the gate and writes a hash-bound receipt.
6. Fetch `artifacts` and call `publish_artifact` with the report source and
   receipt. Use the same `artifact_id` and `base_version` for revisions.

```python
report_design_report(
    report_goal="Explain how the draw changed contender paths and where uncertainty remains.",
    audience="Tournament analysts",
    title="World Cup 2026 — The Draw Changed the Map",
    report_path="reports/world-cup-draw.html",
    storyboard_path="reports/world-cup-draw.storyboard.json",
    quality_gate="fail",
    insights=validated_findings,
    analyses=[change_asset, path_asset, scenario_lookup],
    requirements={
        "methodology": completed_methodology,
        "limitations": material_limitations,
        "evidence_registry": {"targets": completed_evidence_targets},
    },
)
```

## Creative authoring contract

Every report is authored by the ledger-backed `creative` author from a non-empty
evidence ledger; there is no other presentation and no deterministic path. The
exact Markdown dossier is persisted as
`*.author-dossier.md`. It includes the report brief, every completed finding,
bounded aggregate values, grain, units, denominators, definitions, caveats,
methods, evidence aliases, and optional constraints.

The author may write original supported prose and choose the complete story,
layout, typography, density, HTML/CSS, bespoke SVG/Canvas visuals, and small
safe DOM-local interactions. It may merge, split, reorder, or intentionally
omit supplied sources. Familiar charts are allowed when they communicate best;
custom visuals are allowed when the evidence supports them. The governed
`advanced_visual` forms are an optional shared vocabulary, not quotas or the
authored report schema.

The author must not introduce a new finding, value, category, denominator,
causal explanation, or unsupported visual relationship. Descriptive evidence
must remain descriptive. Every substantive claim and quantitative visual must
use its source/evidence aliases; every source must be used or explicitly omitted
with a reason.

The host validates the complete document, runs an independent evidence pass,
allows one bounded repair, and injects the canonical ledger, source coverage,
CSP, report contract, and regeneration recipe. Authored JavaScript must use
`data-dc-author-script`; external resources, live fetching, forms, storage,
workers, unsafe handlers, dynamic code, and navigation scripts are rejected.

## Bespoke per-asset visuals

Section kinds and the governed advanced-visual forms (`dot_plot`, `lollipop`,
`slopegraph`, `range_band`, `matrix`, `timeline`, `flow`, `bracket`, alongside
the familiar `bar`, `line`, `scatter`, and `heatmap`) stay a small, semantic,
closed vocabulary. Do not add a new section kind, and do not invent a
`visual.type` for a custom form.

- Set `required_visual: true` on an asset only when that exact asset must appear
  as a reader-facing figure/SVG/canvas; it then may not be omitted.
- For a custom visual beyond the familiar and governed forms, express intent as
  free-text `visual_direction` on the asset (for example, "Build an annotated
  radial tournament path in SVG"), with optional `medium` of `"svg"`,
  `"canvas"`, or `"html"`. The creative author realizes it from the bounded
  aggregate data under the usual evidence and safety rules.

An unrecognized `visual.type` is now tolerated—folded into `visual_direction`
automatically—but `visual_direction` is the clean, intended channel.

## Optional constraints

Let the author decide when the user has not imposed a requirement.

- Use `requirements.story_arcs` only when specific questions or ordering are
  authoritative. Without them, the author chooses the narrative from the
  dossier.
- Use a design brief, tone, brand information, or required interaction only
  when supplied by the user or clearly required by the task.
- Describe analytical relationships and reader tasks instead of prescribing
  components. For example, say “compare before and after” or “allow team lookup,”
  not “use three KPI cards and a slopegraph.”
- Attach an exact `visual` mapping only for a governed advanced-visual form or
  when the mapping itself is part of the validated analytical contract. For a
  custom form outside that vocabulary, use `visual_direction`, not an invented
  `visual.type`.
- Familiar `bar`, `line`, `scatter`, and `heatmap` mappings may be supplied as
  either `chart` or `visual`; the host normalizes them as ordinary charts rather
  than treating them as bespoke advanced visuals.

## Evidence and analytical rigor

Every evidence reference must resolve to a registered target with the same
`kind` and id/ref. Keep audit provenance in the ledger and receipt; do not make
opaque notebook ids the main reader story.

For forecasts, predictions, simulations, or other model-based reports, include
`requirements.analysis_review` with the applicable completed baseline,
uncertainty, assumptions, sensitivity, path/distribution evidence, and
`export_runtime="local"`. A baseline needs status, method, result, and registered
typed evidence. The critique may flag missing work but never invent it.

Use `resolve_review_finding` for a genuine evidence-backed resolution. Use
`accepted_with_rationale` only with explicit user approval; the receipt retains
that decision.

## Existing reports and revisions

To redesign or upgrade an existing report, re-author from the underlying
validated outputs. There is no raw-HTML normalization path: assemble the
existing findings, aggregate assets, requirements, and evidence ledger and call
`report_design_report`.

For a creative-report revision, update the findings, aggregate assets,
requirements, or design brief and re-author from the storyboard's
`source_context` and persisted dossier. Exact HTML reproducibility is not
required; ledger identity, source coverage, and reviewed analytical meaning
are. Never edit generated HTML as the source of truth or after
`report_publish`, because the receipt binds its bytes and review contract.
The regeneration recipe sidecar is diagnostic audit context: publication
records it as verified, missing, invalid, or stale, but does not block on it.

## Completion criteria

Do not declare the report complete unless:

- the evidence review and artifact-safety validation pass;
- every required analytical finding is resolved or explicitly accepted by the
  user; editorial and layout warnings are reviewed but are not publication gates;
- material caveats, uncertainty, units, and denominators remain visible;
- browser review is approved for the exact HTML when the user explicitly opted
  into that review;
- `report_publish` returns a current receipt for the exact report bytes;
- artifact publication succeeds, or unavailable artifact tooling is stated
  plainly without inventing an id, version, or URL.

Skill freshness warnings are advisory context. Judge publication from the
report's evidence ledger, review results, safety checks, and receipt—not from
layout-skill reproducibility.
