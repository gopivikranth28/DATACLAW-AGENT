# DataClaw Release 3 — Branch Progress Report

| | |
|---|---|
| **Generated** | 2026-07-14 |
| **Branch reviewed** | `structured-eda` |
| **Implementation snapshot** | `6035f13` — `feat(report-design): add iterative editorial review gates` |
| **Scope** | Current repository implementation and local verification results; not a release-note promise |

## Executive summary

Release 3 has a real, code-backed analysis and reporting core. Structured EDA phases P0–P6 are shipped: durable hypothesis and finding ledgers, evidence anchors, loop and multiplicity controls, readiness, plan gates, deterministic review, a bounded reviewer sub-agent, and shared OpenClaw contract fixtures. The report-builder now has a structured HTML publishing boundary: a storyboard designer, raw-HTML normalization with source retention, bounded critique, evidence registry, rubric v3 gate, publish receipt, and browser-runtime smoke attempt.

The latest hardening pass closes defects found in a live low-level report: array-backed interactive tables are normalized before rendering, narrative headings and safe inline emphasis render correctly, untitled metric rows are excluded from the contents rail, and browser smoke detects blank tables or generic navigation labels. The UI now distinguishes draft, designed, and published report states. Report/dashboard/artifact plan steps require analysis review before becoming ready, and an automatic review failure revokes optimistic readiness.

The newest report-design pass adds an editorial architecture rather than merely more section types. The planner now establishes a **Hero → KPI summary → taxonomy/category cards (or a guided explorer) → hero visual → paired diagnostics → findings → explorer → methodology/evidence → footer** rhythm. It carries explicit hero, story-priority, and diagnostic-pair metadata; performs five bounded critique stages; and returns a persisted `design_review`. Publishing recomputes that review and blocks unresolved design warnings. The browser smoke now includes desktop/mobile geometry, overflow, floating-KPI, diagnostic-pair, control-retention, and screenshot-compositor checks when Playwright Chromium is available. A missing browser runtime is recorded as skipped, not presented as a visual pass.

The work is not feature-complete. The remaining committed Structured EDA phases are P7 (a dedicated Findings/Review UI) and P8 (the committed golden/live evaluation harness). For the report builder, DOCX/static-export fidelity remains explicitly open. Release evidence should therefore claim durable HTML reports and governed EDA only where the supplied tests and demos support the claim; it should not claim a finished review UI, live-model evaluation results, or faithful DOCX export.

## Current capability status

| Capability | Status | Evidence in the current code |
|---|---|---|
| Artifact platform and safe preview | Shipped foundation | Versioned artifact store, validation/wrapping, safe serving, artifact UI, report/living-report preview surfaces, and security/preview tests. |
| Report builder — structured HTML | Shipped and editorially hardened | Typed design/build/publish flow; five-stage storyboard critique; a consistent hero/KPI/cards/visual/diagnostic/explorer narrative; evidence-linked interpretation; responsive layout checks; and clear draft/designed/published UI states. |
| Report builder — DOCX/static fidelity | Pending | DOCX conversion is best effort. Interactive sections need static fallbacks and conversion diagnostics before export fidelity can be promoted. |
| Structured EDA P0–P4a | Shipped | EDA ledgers and tools, notebook evidence anchors, readiness, plan gates, skills, `loop_index`, and multiplicity/selection floors. |
| Structured EDA P5 | Shipped | Full deterministic review checklist, rerun handling, plan-gate sync, and unresolved-review-risk living-report surfacing. |
| Structured EDA P6 | Shipped | Registered bounded `analysis-reviewer`, structured capped context, rubric rendering from the current skill, JSON finding persistence, and explicit fallback labels. |
| Dedicated Findings/Review UI (P7) | Pending | Review REST routes and tool-result data exist; no dedicated frontend Findings/Review view was found. |
| Golden/live evaluation harness (P8) | Pending | Deterministic unit/contract tests exist; no committed `evals/` runner, live tier scoring, or judge report exists. |
| OpenClaw tool contracts and skill sync | Shipped and verified | The report-design and artifacts guides are synchronized across the bundled library, installed DataClaw skills, and OpenClaw extensions; their body hashes match. Existing tool-contract/manifest verification remains a separate recorded check. |

## Report-builder milestone

The report builder is now suitable for governed **HTML** report delivery. It is deliberately not a claim of production-grade DOCX export.

### Published flow

```text
Completed insights / typed analyses
  -> report_design_report
  -> editorial storyboard + five bounded critique stages + evidence registry
  -> persisted design_review (structure, interpretation, evidence, responsiveness)
  -> rendered HTML + rubric v3 gate
  -> report_publish
  -> fail-closed design re-review + rubric re-gate + runtime smoke + publish receipt
  -> optional artifact publication
```

`build_report` is compatible with existing raw HTML inputs, but it no longer treats them as an uninspected final report. It preserves the original as a sibling `.source.html`, extracts ordinary headings/prose/tables into a storyboard where possible, and records low extraction confidence instead of fabricating structure. A low-confidence raw source cannot silently pass the publish boundary.

### What shipped

- Typed storyboard generation through `report_design_report`, including completed-insight requirements, supported analytical section mappings, explicit `editorial_role`, `story_priority`, and diagnostic-pair controls.
- A component-rich renderer: dark editorial hero, floating KPI row, taxonomy/card grammar, interpretation panels, evidence chips, interactive tables, selector/filter/chart-table explorers, themed Plotly figures, responsive rail navigation, and evidence anchors/backlinks.
- Storyboard architecture that alternates orientation, detail, visualization, interpretation, and interaction. Categorical selectors can materialize as category cards while retaining their interactive explorer; reports without a useful taxonomy use a guided explorer instead of fabricating one.
- Five deterministic, bounded editorial critique stages: page architecture, visual hierarchy, card/section grammar, evidence and chart interpretation, and responsive/publish readiness. Their findings are persisted as `design_review` and displayed in the report UI.
- The design gate requires a visual-led report to supply local interpretation and evidence, not only a caption or data note. `report_publish` reruns that gate and blocks unresolved warning-level design findings.
- Rubric v3 with live fail conditions for raw/unstructured output, oversized payloads, plain-chart stacks/dumps, missing required explorer/insight structure, and stale installed skills; warnings disclose weaker evidence, captions, runtime, contrast, and portability conditions.
- Bounded critique that may add only safe context/caveats and records its changes rather than inventing evidence; it is idempotent across the five editorial passes.
- `report_publish` as the dedicated fail-closed boundary, writing a quality result and publish receipt. It recomputes the design review, then attempts a Playwright browser smoke test and records `passed`, `failed`, or `skipped`. When Chromium is available, the check covers desktop/mobile overflow, diagnostic-pair collapse, floating-KPI overlap, interactive control retention, chart mounts, and screenshot compositor output. A skipped browser check is explicitly disclosed, never represented as a pass.
- Interactive tables accept either keyed records or value arrays aligned with `columns`; normalized object rows prevent the blank-cell failure seen in the live report. The browser smoke also detects rendered blank tables and generic contents labels.
- `narrative_band` accepts `title` or `heading` and permits only safe inline `<b>/<strong>`, `<i>/<em>`, and `<code>` emphasis after escaping all other HTML.
- Low-level `report_add_section` results are visibly labeled **Draft · publish required**. Structured design results are **Designed · publish required**; only `report_publish` returns **Published**. The report-design tool is rendered as a report card and is included in the app report surface.
- Raw HTML normalization, evidence-registry resolution, and source preservation.
- OpenClaw manifest regeneration from the live tool registry, including `report_design_report` and the expanded report section schema.
- UI coverage for the published report result/preview path in the Playwright preview-surface suite.

### Remaining report-builder work

1. Create static fallbacks for interactive components before DOCX conversion.
2. Replace/upgrade best-effort DOCX conversion with explicit fidelity diagnostics.
3. Promote export-fidelity and selected runtime/evidence warnings only when their required runtime guarantees are available.
4. Build a release-quality real-data report example that exercises evidence anchors, interactions, and the publish receipt.
5. Provision a pinned Playwright Chromium runtime in CI and retain responsive screenshots so the layout-review path is routinely exercised rather than skipped locally.

## Structured EDA and analysis review

### Shipped P0–P6

| Phase | Delivered behavior |
|---|---|
| P0 — Plans gates | `ready_for_validation` gate enforcement, audit events, explicit `accept_gate_risk`, review policy for report/dashboard/artifact steps, and automatic readiness revocation when an automatic review fails. |
| P1 — EDA ledgers | Append-only hypothesis/finding stores, eight EDA tools, router, hooks, validation floors, and plan-step attribution. |
| P2 — Evidence | Notebook `cell_id` and source-hash anchors plus stale-evidence handling. |
| P3 — Readiness | Purpose/mode policies, hypothesis rollups, deferred-vs-unresolved distinction, and artifact/living-report readiness outputs. |
| P4 — Skills | Hypothesis-driven `structured_eda`, `insight_validation`, `analysis_review`, DataClaw routing, and OpenClaw mirrors. |
| P4a — Loop and multiplicity | Per-record `loop_index`; screening count, selection rule, and correction floors. This makes the exploration loop and multiple-hypothesis discipline auditable rather than prose-only. |
| P5 — Deterministic review | Append-only review store/tools/router; checks including multiplicity, stale evidence, MLflow reproducibility, and open required findings; gate sync and unresolved-risk publish surfacing. |
| P6 — Reviewer sub-agent | The bounded `analysis-reviewer` uses read-only metadata tools and a 50 KiB-capped context. It records parsed JSON findings, leaves the gate `unknown` for sub-agent-required degradation, and preserves deterministic findings if the provider or parser fails. |

### Remaining P7–P8

| Phase | Not yet shipped | Exit evidence needed |
|---|---|---|
| P7 — Findings/Review UI | Read-only grouped findings/review views, inline cards, readiness pinning, and AG-UI handling. | Browser/manual flow showing cards and grouping by hypothesis/review status without silently changing a gate. |
| P8 — Evaluation harness | Committed EDA golden case, tiered scoring, opt-in live-model run, and qualitative judge output. | Reproducible smoke in CI plus recorded Tier 1/2 scores and judge report for the fixture. |

The shared acceptance fixtures are already present and exercised: canonical/alias schema identity, stable `plan_step_id`, and 20-row/50 KiB preview caps. They are building blocks for P8, not a replacement for it.

## What can be claimed now

- DataClaw can persist structured EDA hypotheses, findings, evidence anchors, readiness, and review state rather than keeping these only in chat or notebooks.
- The EDA methodology records rejected hypotheses, loop position, screening/multiplicity metadata, and unresolved caveats so exploratory work is inspectable.
- Plan validation can be governed by deterministic review findings and explicit recorded risk acceptance.
- A bounded reviewer sub-agent is available when its provider is configured; absence or parse failure is visibly labeled checklist-only/mixed and cannot silently satisfy a sub-agent-required gate.
- DataClaw can design, quality-gate, publish, and preview structured interactive HTML reports with a stored storyboard, evidence registry, persisted design review, and publish receipt.
- A report designer can enforce an editorial reading sequence, pair diagnostics with interpretation, and preserve an explorer for follow-up rather than shipping a stack of unrelated charts.

## Claims to defer

- A finished Findings/Review product UI.
- Published live-model EDA quality scores or judge results.
- Guaranteed high-fidelity DOCX/static export of interactive reports.
- A browser-layout pass on machines where Playwright Chromium is unavailable; the publish result records that check as skipped.
- A complete public release-evidence package for every artifact/dashboard claim.
- Governed regression, survey/secondary-research, or market-mapping workflows; none are represented by the reviewed implementation.

## Recommended release-close work

1. Build P7’s Findings/Review UI against the existing read-only review routes and verify it through the browser.
2. Add P8’s committed golden runner before treating the methodology as externally benchmarked.
3. Produce one end-to-end real-data structured EDA report, retain its storyboard/receipt, and use it as the release evidence example.
4. Keep DOCX fidelity as a separate report-builder follow-up unless static fallbacks and conversion verification land.
5. Provision Playwright Chromium in CI and require the desktop/mobile layout smoke, including its captured screenshots, for release-candidate report examples.
6. Keep the generated OpenClaw manifest/installed extension synchronized whenever report or EDA tools change. The installer now uses `openclaw config unset` for an orphan channel section on OpenClaw 2026.6, and installer tests isolate their snapshot so they cannot corrupt the user’s real drift status. Refresh a chat session after tool-schema changes so its tool filter is rebuilt.
7. Keep the UI preview/report renderer lazy-loaded and monitor the existing Vite vendor-bundle warning as a separate frontend hardening task.

## Verification basis

The latest local checks recorded for this branch and report-builder milestone were:

| Check | Result |
|---|---|
| Workspace report-builder regression tests (`test_report_rubric.py`, `test_tools.py`) | 64 passed |
| Artifact and skill-library regression tests | 23 passed in the combined artifacts/library check; a focused skill-library rerun passed 16 |
| OpenClaw install-service tests | 24 passed |
| UI build | `npm run build` passed |
| Browser layout/compositor smoke | Implemented and fail-closed on a failed result; local Playwright Chromium launch was unavailable, so this run was explicitly skipped rather than counted as a pass. |
| Runtime skill synchronization | `report_design` and `artifacts` installed and OpenClaw-extension bodies match their bundled-library hashes. |

These are implementation signals, not substitutes for P8’s live-model evaluation or a release evidence package.

## Traceability

- Primary report-builder architecture and remaining DOCX decision: [`docs/report-builder-architecture.md`](report-builder-architecture.md)
- Structured EDA phase status and requirements: [`docs/structured-eda-prd.md`](structured-eda-prd.md)
- Analysis-review component details: [`docs/analysis-review-prd.md`](analysis-review-prd.md)
- Report publishing implementation: `plugins/dataclaw-workspace/dataclaw_workspace/{tools.py,report_renderer.py}`
- Editorial design, review, and runtime layout checks: commit `6035f13` (`feat(report-design): add iterative editorial review gates`)
- EDA and review implementation: `plugins/dataclaw-eda/` and `plugins/dataclaw-analysis-review/`
