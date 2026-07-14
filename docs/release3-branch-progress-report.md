# DataClaw Release 3 — Branch Progress Report

| | |
|---|---|
| **Generated** | 2026-07-13 |
| **Branch reviewed** | `structured-eda` |
| **Implementation snapshot** | `827debe` — `feat(reporting): harden structured report publishing` |
| **Scope** | Current repository implementation and local verification results; not a release-note promise |

## Executive summary

Release 3 has a real, code-backed analysis and reporting core. Structured EDA phases P0–P6 are shipped: durable hypothesis and finding ledgers, evidence anchors, loop and multiplicity controls, readiness, plan gates, deterministic review, a bounded reviewer sub-agent, and shared OpenClaw contract fixtures. The report-builder now has a structured HTML publishing boundary: a storyboard designer, raw-HTML normalization with source retention, bounded critique, evidence registry, rubric v3 gate, publish receipt, and browser-runtime smoke attempt.

The work is not feature-complete. The remaining committed Structured EDA phases are P7 (a dedicated Findings/Review UI) and P8 (the committed golden/live evaluation harness). For the report builder, DOCX/static-export fidelity remains explicitly open. Release evidence should therefore claim durable HTML reports and governed EDA only where the supplied tests and demos support the claim; it should not claim a finished review UI, live-model evaluation results, or faithful DOCX export.

## Current capability status

| Capability | Status | Evidence in the current code |
|---|---|---|
| Artifact platform and safe preview | Shipped foundation | Versioned artifact store, validation/wrapping, safe serving, artifact UI, report/living-report preview surfaces, and security/preview tests. |
| Report builder — structured HTML | Shipped and hardened | `report_design_report`, `build_report`, and `report_publish` form a typed design/build/publish flow with a v3 quality gate and receipt. |
| Report builder — DOCX/static fidelity | Pending | DOCX conversion is best effort. Interactive sections need static fallbacks and conversion diagnostics before export fidelity can be promoted. |
| Structured EDA P0–P4a | Shipped | EDA ledgers and tools, notebook evidence anchors, readiness, plan gates, skills, `loop_index`, and multiplicity/selection floors. |
| Structured EDA P5 | Shipped | Full deterministic review checklist, rerun handling, plan-gate sync, and unresolved-review-risk living-report surfacing. |
| Structured EDA P6 | Shipped | Registered bounded `analysis-reviewer`, structured capped context, rubric rendering from the current skill, JSON finding persistence, and explicit fallback labels. |
| Dedicated Findings/Review UI (P7) | Pending | Review REST routes and tool-result data exist; no dedicated frontend Findings/Review view was found. |
| Golden/live evaluation harness (P8) | Pending | Deterministic unit/contract tests exist; no committed `evals/` runner, live tier scoring, or judge report exists. |
| OpenClaw tool contracts | Shipped | Manifest regenerated from the live registry; shared fixture checks canonical and `dataclaw_...` alias schema parity. |

## Report-builder milestone

The report builder is now suitable for governed **HTML** report delivery. It is deliberately not a claim of production-grade DOCX export.

### Published flow

```text
Completed insights / typed analyses
  -> report_design_report
  -> storyboard + bounded critique + evidence registry
  -> rendered HTML + rubric v3 gate
  -> report_publish
  -> fail-closed re-gate + runtime smoke + publish receipt
  -> optional artifact publication
```

`build_report` is compatible with existing raw HTML inputs, but it no longer treats them as an uninspected final report. It preserves the original as a sibling `.source.html`, extracts ordinary headings/prose/tables into a storyboard where possible, and records low extraction confidence instead of fabricating structure. A low-confidence raw source cannot silently pass the publish boundary.

### What shipped

- Typed storyboard generation through `report_design_report`, including completed-insight requirements and supported analytical section mappings.
- A component-rich renderer: interpretation panels, evidence chips, interactive tables, selector/filter/chart-table explorers, themed Plotly figures, responsive rail navigation, and evidence anchors/backlinks.
- Rubric v3 with live fail conditions for raw/unstructured output, oversized payloads, plain-chart stacks/dumps, missing required explorer/insight structure, and stale installed skills; warnings disclose weaker evidence, captions, runtime, contrast, and portability conditions.
- Bounded critique that may add only safe context/caveats and records its changes rather than inventing evidence.
- `report_publish` as the dedicated fail-closed boundary, writing a quality result and publish receipt. It attempts a Playwright browser smoke test and records `passed`, `failed`, or `skipped`; a skipped browser check is disclosed as a warning, never represented as a pass.
- Raw HTML normalization, evidence-registry resolution, and source preservation.
- OpenClaw manifest regeneration from the live tool registry, including `report_design_report` and the expanded report section schema.
- UI coverage for the published report result/preview path in the Playwright preview-surface suite.

### Remaining report-builder work

1. Create static fallbacks for interactive components before DOCX conversion.
2. Replace/upgrade best-effort DOCX conversion with explicit fidelity diagnostics.
3. Promote export-fidelity and selected runtime/evidence warnings only when their required runtime guarantees are available.
4. Build a release-quality real-data report example that exercises evidence anchors, interactions, and the publish receipt.

## Structured EDA and analysis review

### Shipped P0–P6

| Phase | Delivered behavior |
|---|---|
| P0 — Plans gates | `ready_for_validation` gate enforcement, audit events, and explicit `accept_gate_risk` approval path. |
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
- DataClaw can design, quality-gate, publish, and preview structured interactive HTML reports with a stored storyboard, evidence registry, and publish receipt.

## Claims to defer

- A finished Findings/Review product UI.
- Published live-model EDA quality scores or judge results.
- Guaranteed high-fidelity DOCX/static export of interactive reports.
- A complete public release-evidence package for every artifact/dashboard claim.
- Governed regression, survey/secondary-research, or market-mapping workflows; none are represented by the reviewed implementation.

## Recommended release-close work

1. Build P7’s Findings/Review UI against the existing read-only review routes and verify it through the browser.
2. Add P8’s committed golden runner before treating the methodology as externally benchmarked.
3. Produce one end-to-end real-data structured EDA report, retain its storyboard/receipt, and use it as the release evidence example.
4. Keep DOCX fidelity as a separate report-builder follow-up unless static fallbacks and conversion verification land.
5. Keep the generated OpenClaw manifest/installed extension synchronized whenever report or EDA tools change; refresh a chat session after tool-schema changes so its tool filter is rebuilt.
6. Keep the UI preview/report renderer lazy-loaded and monitor the existing Vite vendor-bundle warning as a separate frontend hardening task.

## Verification basis

The latest local checks recorded for this branch and report-builder milestone were:

| Check | Result |
|---|---|
| Workspace report-builder tests | 48 passed |
| Structured EDA/skill/tool-contract/PRD fixture suite | 41 passed |
| OpenClaw install-service tests | 23 passed |
| UI build | `npm run build` passed |
| UI preview/report Playwright suite | 3 passed |
| OpenClaw plugin | Generated manifest and installed extension matched; plugin enabled after gateway restart. Gateway remote probing still requires pairing/scope approval. |

These are implementation signals, not substitutes for P8’s live-model evaluation or a release evidence package.

## Traceability

- Primary report-builder architecture and remaining DOCX decision: [`docs/report-builder-architecture.md`](report-builder-architecture.md)
- Structured EDA phase status and requirements: [`docs/structured-eda-prd.md`](structured-eda-prd.md)
- Analysis-review component details: [`docs/analysis-review-prd.md`](analysis-review-prd.md)
- Report publishing implementation: `plugins/dataclaw-workspace/dataclaw_workspace/{tools.py,report_renderer.py}`
- EDA and review implementation: `plugins/dataclaw-eda/` and `plugins/dataclaw-analysis-review/`
