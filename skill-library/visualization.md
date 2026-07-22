---
name: visualization
description: Create trustworthy notebook and chat visuals and prepare bounded, well-described aggregate evidence for report_design. Use for analytical charting, visual integrity checks, or packaging visual evidence; do not use it to choose a final report layout or component system.
tags: [visualization, charts, evidence, analysis]
---

## Role

Use this skill for analysis-time visualization and evidence preparation. Let
`report_design` own the final report's story, prose, layout, visual form,
interactions, and HTML.

Do not pre-compose the report. Do not prescribe a chart count, KPI count,
dashboard archetype, component library, page order, or final visual style. Do
not use `report_add_section` to assemble a polished report. A final report may
use a familiar chart, an interactive explorer, or a bespoke HTML/SVG/Canvas
visual; the report author decides from the supplied evidence.

## Analysis-time workflow

1. Establish the analytical question, comparison, grain, scope, baseline, and
   denominator before choosing an encoding.
2. Aggregate in the notebook. Never hand raw full datasets, secrets, connection
   strings, or unbounded row collections to a browser artifact.
3. Create a notebook visual only when it helps validate or understand the
   analysis. Ordinary Plotly is appropriate for this surface:

```python
fig = px.scatter(summary, x="exposure", y="outcome", color="segment")
fig.show()
```

4. Share useful notebook output in chat with `display_cell_output` and a concise
   caption. Use `display_metric` only for a genuinely useful progress or result
   headline, not to impose a KPI row on the final report. If the runtime exposes
   `dataclaw_display_cell_output` or `dataclaw_display_metric`, use that alias.
5. Record material conclusions in the appropriate finding/evidence ledger before
   report generation.

Notebook figures are analytical working evidence. They are not mandatory final
report visuals, and the report author need not reproduce their geometry.

## Prepare author-ready evidence

Pass `report_design_report` rich semantic assets rather than a predesigned page.
For each useful analysis, include what is available from:

- a clear title or analytical topic;
- bounded aggregate `records` or a compact Plotly figure when its exact geometry
  matters to the finding;
- `semantic_role` or a plain-language relationship such as ranking, change,
  distribution, range, comparison, path, lookup, or uncertainty;
- grain, population/scope, units, denominator, and field definitions;
- comparison baseline, time window, filters, and aggregation method;
- validated interpretation, material caveat, and uncertainty;
- stable `finding_id`/`claim_source_id` and typed evidence references.

Example:

```python
change_asset = {
    "title": "Qualification probability before and after the draw",
    "semantic_role": "two-state change",
    "records": contender_change.to_dict("records"),
    "grain": "one row per contender",
    "units": {"before_probability": "share", "after_probability": "share"},
    "denominator": "eligible simulated tournament paths",
    "field_definitions": {
        "team": "contender label",
        "before_probability": "pre-draw qualification probability",
        "after_probability": "post-draw qualification probability",
    },
    "interpretation": "The draw changed the ordering of the leading contenders.",
    "caveat": "Simulation outputs are descriptive scenarios, not causal effects.",
    "claim_source_id": "find-draw-change",
    "evidence": [{"kind": "notebook_cell", "cell_id": "cell-draw-change"}],
}
```

Describe the relationship; do not add a `chart` or `visual` mapping merely to
force a familiar form. Supply an exact mapping only when it is analytically
essential or when using the governed deterministic fallback.

## Visual integrity

Before handing off evidence, verify:

- labels, units, time windows, sample sizes, and denominators are explicit;
- magnitude encodings use an honest baseline and comparable scales;
- uncertainty or scenario spread is retained when available;
- cumulative and per-period measures are not conflated;
- color is not the only carrier of meaning;
- sparse or missing observations are not silently presented as zero;
- small groups, selection effects, and outliers are disclosed where material;
- descriptive or associational results are not framed as causal;
- the interpretation is supported by the same values sent to the report author.

## Final-report handoff

For a polished deliverable, fetch `report_design` and pass the completed
findings, author-ready assets, methodology, limitations, and
`requirements.evidence_registry.targets`. Story arcs, required controls, brand,
and visual direction are optional constraints; omit them when the author should
decide freely.

After `report_design_report`, follow its visual-review and `report_publish`
flow, then fetch `artifacts` to publish or revise the result. Do not edit the
generated report HTML as the source of truth.
