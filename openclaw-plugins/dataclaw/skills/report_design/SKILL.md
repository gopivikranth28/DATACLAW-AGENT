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
  references;
- methodology, data-quality limits, uncertainty, assumptions, definitions, and
  coverage risks;
- a non-empty evidence ledger in
  `requirements.evidence_registry.targets`, with matching typed references;
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
2. Call `report_design_report` with `presentation_mode="handcrafted"` (the
   default), `quality_gate="fail"`, and the full handoff.
3. Inspect `analytical_review`, `design_review`, `authoring_review`, source
   coverage, evidence-review status, and quality. Resolve required analytical
   findings with real evidence or obtain explicit user-approved risk acceptance.
4. When `requirements.publication.require_visual_review=true`, inspect the
   screenshots and call `report_review_visuals` with a named reviewer, decision,
   and rationale. Handcrafted final releases require a current approved review.
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
    presentation_mode="handcrafted",
    quality_gate="fail",
    insights=validated_findings,
    analyses=[change_asset, path_asset, scenario_lookup],
    requirements={
        "methodology": completed_methodology,
        "limitations": material_limitations,
        "evidence_registry": {"targets": completed_evidence_targets},
        "publication": {"require_visual_review": True},
    },
)
```

## Creative authoring contract

With a configured LLM and a non-empty ledger, handcrafted mode defaults to the
ledger-backed `creative` author. The exact Markdown dossier is persisted as
`*.author-dossier.md`. It includes the report brief, every completed finding,
bounded aggregate values, grain, units, denominators, definitions, caveats,
methods, evidence aliases, and optional constraints.

The author may write original supported prose and choose the complete story,
layout, typography, density, HTML/CSS, bespoke SVG/Canvas visuals, and small
safe DOM-local interactions. It may merge, split, reorder, or intentionally
omit supplied sources. Familiar charts are allowed when they communicate best;
custom visuals are allowed when the evidence supports them. The component
library and governed `advanced_visual` mappings are fallback tools, not quotas
or the authored report schema.

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
- Attach an exact `visual` mapping only for a governed deterministic visual or
  when the mapping itself is part of the validated analytical contract.

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

Use `build_report` for existing standard HTML. Publish only
`normalization.mode == "structured_rebuild"` or `"typed_preservation"`.
`preserved_low_confidence` retains unsupported source material and must be
rebuilt from validated insights and aggregate assets. Handcrafted upgrade from
raw HTML fails closed: `build_report(presentation_mode="handcrafted")` directs
the caller to `report_design_report` with the existing validated outputs.

For a creative-report revision, update the findings, aggregate assets,
requirements, or design brief and re-author from the storyboard's
`source_context` and persisted dossier. Exact HTML reproducibility is not
required; ledger identity, source coverage, and reviewed analytical meaning
are. Never edit generated HTML as the source of truth or after
`report_publish`, because the receipt binds its bytes and review contract.

## Bounded compatibility paths

Without a ledger, handcrafted mode falls back to bounded `runtime`. Use
`visual_author={"mode": "off"}` for deterministic-only output, `runtime` for
the legacy theme/surface selector, `required` to stop on bounded authoring
failure, or `provided` for a previously validated bounded spec.

`report_add_section` is a compatibility and draft helper only. Use it for a
scratch chart or incremental diagnostic with `quality_gate="warn"`; never use a
sequence of these calls as the polished final-report architecture.

## Completion criteria

Do not declare the report complete unless:

- the evidence review and artifact-safety validation pass;
- every required analytical or design finding is resolved or explicitly
  accepted by the user;
- material caveats, uncertainty, units, and denominators remain visible;
- required browser review is approved for the exact HTML;
- `report_publish` returns a current receipt for the exact report bytes;
- artifact publication succeeds, or unavailable artifact tooling is stated
  plainly without inventing an id, version, or URL.

Skill freshness warnings are advisory context. Judge publication from the
report's evidence ledger, review results, safety checks, and receipt—not from
layout-skill reproducibility.
