# DataClaw V3 Release Progress Update

Generated: 2026-07-09
Audience: DataClaw team
Scope: progress against the planned DataClaw V3 release, compared with the current mainline baseline
Latest implementation snapshot: `structured-eda` at `e372b27`, `origin/main` at `42c4b97`

## Executive Summary

The V3 release has moved from planning into real implementation across the core artifact platform and the structured EDA workflow.

The biggest shipped progress is the artifact foundation: DataClaw can now publish, validate, serve, render, and export first-class analysis artifacts instead of leaving outputs as loose notebook/chat files. This includes a safer artifact serving path, artifact panel UI, app view, Plotly chart rendering, metric tiles, and the beginning of living-report event capture.

Structured EDA has also advanced substantially. It is no longer just a methodology or PRD. The current implementation includes a structured EDA plugin with hypothesis and finding ledgers, readiness evaluation, notebook evidence anchors, loop/multiplicity metadata, plan validation gates, risk-acceptance audit flow, skills, examples, and tests. The deterministic analysis-review lifecycle core has also landed: append-only review runs/findings, checklist checks, auto-review on completed high-risk/EDA-like steps, and plan-gate sync.

The latest work adds a storyboard-driven report designer. Instead of only appending report sections incrementally, DataClaw can now design a cohesive report plan, write a storyboard JSON, choose interactive section layouts, render the final HTML in one pass, and validate richer typed report sections.

The newest structured-EDA branch update hardens that reporting path. Final report design now fails by default on required quality regressions, requires at least one completed insight, catches chart-heavy noninteractive reports, and treats stale installed library skills as quality risks while using the current bundled skill instructions for the active turn.

The main remaining gaps are the reviewer sub-agent runtime, broader checklist coverage, the Findings/Review UI, the committed eval harness, OpenClaw alias validation, and public evidence examples for every release claim. Governed baseline regression and survey/secondary research are still not implemented and should not be claimed unless they land before release.

Recommended release posture: keep the V3 story narrow and evidence-backed. Ship first-class artifacts, safe serving, living-report foundation, Plotly/dashboarding primitives, and structured EDA if the remaining validation/review gaps are either completed or explicitly scoped as post-release follow-up.

## V3 Release Intent

The planned V3 release is about turning DataClaw from a chat-plus-notebook assistant into a more durable analyst workspace.

The release plan centers on these capabilities:

- First-class artifacts instead of loose output files.
- Safe artifact serving and previewing.
- Living reports that preserve the investigation story.
- Structured EDA with explicit hypotheses, findings, evidence, and readiness.
- Plotly visual output and dashboarding workflows.
- Advisory review/critic artifacts for analysis quality.
- Evidence packages that prove public release claims.

The current release plan does not require claiming a public Pack SDK, automated in-loop critic runtime, OpenRouter/model-routing improvements, or market-mapping functionality.

## Behavior Change: DataClaw 2 vs V3

DataClaw 2 on `origin/main` was primarily a notebook-first analyst assistant. It could inspect datasets, run notebook EDA, propose and update plans, display charts or cell outputs in chat, log MLflow runs, and summarize findings. The standard profiling path produced shape, schema, missingness, duplicates, summary statistics, distributions, correlations, and data-quality flags.

V3 changes the product behavior from "the agent did analysis in a notebook and summarized it" to "the agent records durable analytical objects that the product can inspect, render, gate, and preserve over time." The key shift is that hypotheses, findings, evidence, readiness, artifacts, and report events become first-class product state.

### Sample Questions And Expected Outputs

| Sample question | DataClaw 2 behavior on `origin/main` | V3 behavior now or intended for this release |
| --- | --- | --- |
| "Explore this customer-events dataset for churn modeling. What should we check before modeling?" | Runs notebook EDA, profiles columns, checks missingness/duplicates/correlations, shows charts in chat, and summarizes caveats in the plan step. | Proposes a hypothesis ledger first, such as leakage risk, target imbalance, duplicate users, missingness by segment, and feature availability. Runs notebook checks, records findings with evidence anchors, and produces a modeling-readiness verdict. |
| "Did we check whether missingness is segment-specific?" | The agent would search the notebook or transcript, or rerun a missingness check, then answer in prose. | The agent can list hypotheses/findings and answer from the ledger: finding id, hypothesis id, status, evidence cell, validation state, caveat, and whether the question is resolved, rejected, or still open. |
| "Can we start modeling yet?" | The agent gives a qualitative answer in the chat or plan summary based on notebook observations. | `summarize_eda_readiness` evaluates required checks for modeling, lists blockers like leakage risk or missing target checks, and can block `ready_for_validation` until gates pass or a user accepts risk. |
| "Create a stakeholder-ready EDA report I can send." | Produces a notebook, markdown/report file, or chat summary with charts and findings. Outputs are mostly loose files or notebook cells. | Designs a report storyboard, writes the storyboard JSON, renders a cohesive artifact-backed HTML report in one pass, and includes typed sections for objective, metrics, charts, findings, evidence trace, caveats, and readiness. |
| "Show the top KPI trends as an interactive dashboard." | Generates charts in a notebook and displays images or cell outputs in chat. | Uses Plotly charts, metric tiles, and dashboarding/report sections inside the app/artifact view. The output can live as an artifact instead of a transient chat display. |
| "Can you storyboard the report before rendering it?" | No first-class storyboard step; the agent would plan in prose and then create notebook/report content manually. | `report_design_report` creates a storyboard JSON with section plan, layout plan, interaction plan, evidence plan, and quality checks, then renders the final HTML report from that storyboard. |
| "Build me a final report from these charts only." | The agent could create a chart-heavy notebook/report and explain the meaning in prose, with quality depending on manual discipline. | The report designer rejects no-insight final reports and fails chart stacks that lack interpretation or interactive explorer controls. Chart-only output can still be a low-level draft, but not the recommended polished deliverable. |
| "What changed after we filtered out internal test users?" | The agent updates the notebook and summarizes the changed result; preserving the old conclusion depends on manual note-taking. | The agent can supersede the old finding, keep the prior record append-only, link the replacement finding, and flag linked hypotheses for reevaluation. |
| "Which notebook cell supports this claim?" | The answer depends on notebook reading and manual citation. | Findings can carry notebook `cell_id` and source hash anchors, so the product can point back to the cell/evidence that produced a claim. |
| "This conclusion feels too strong. Did we validate it?" | The agent self-reviews and explains the caveat in prose. | Findings carry internal/external validation state. High confidence requires internal validation evidence; externally unverified claims are caveated and confidence-capped. The deterministic checklist now catches several structural validation gaps; reviewer sub-agent review is still pending. |
| "Review this analysis before I share it." | Manual agent review only; no persistent review gate. | V3 can run a deterministic analysis review, persist review findings, block plan validation through the `analysis_review` gate, and require explicit user approval before accepting unresolved review risk. Reviewer sub-agent review and UI cards/tabs remain pending. |
| "Give me the investigation history, not just the final answer." | The history is spread across chat, notebook cells, and plan summaries. | Living-report events, report notes, stable plan-step ids, findings, and supersede edges preserve more of the investigation story. End-to-end living-report examples still need to be completed. |

### What Users Can Ask For In V3

Users can now ask for more durable, reviewable outputs:

- "Run structured EDA and track the hypotheses you test."
- "Record findings with evidence and caveats, not just a prose summary."
- "Tell me what hypotheses were rejected and why."
- "Is this dataset ready for modeling, dashboarding, or only further cleanup?"
- "Publish the analysis as an artifact I can preview and export."
- "Storyboard the report first, then render the final artifact."
- "Show this as an interactive Plotly report with metric tiles."
- "Preserve the old finding, but supersede it with the new result after filtering."
- "Attach this conclusion to the notebook cell that produced it."
- "Block validation until the required review gates are resolved."

### What V3 Produces Differently

V3 outputs are increasingly product-native rather than transcript-native:

- Hypothesis records instead of untracked assumptions.
- Finding records instead of only notebook markdown or chat bullets.
- Evidence anchors instead of vague references to prior analysis.
- Readiness verdicts instead of informal "looks good" judgments.
- Artifact reports instead of loose HTML/markdown/notebook outputs.
- Storyboard JSON plus one-pass report rendering instead of incremental report-cell accumulation for final deliverables.
- Report quality gates that catch thin chart dumps, missing primary insights, stale skill instructions, and oversized non-runtime payloads before publication.
- Living-report events instead of only final summaries.
- Gate state and audit trails instead of informal approval notes.

The implementation is not uniformly complete across all of these yet. The artifact platform, structured EDA ledgers, loop/multiplicity floors, and deterministic review core are the most concrete. Reviewer sub-agent review, Findings/Review UI, OpenClaw alias fixtures, and the full eval harness are the main remaining work.

## Progress Against Plan

| V3 Capability | Current Status | Team-Facing Summary |
| --- | --- | --- |
| First-class artifacts | Mostly implemented | Artifact publishing, validation, versioning, safe wrapping, serving, export, and UI surfaces are in place. |
| Safe artifact preview | Mostly implemented | Sandbox/preview hardening, file-preview security tests, Playwright preview-surface coverage, and Vite code-splitting setup exist. Needs final end-to-end validation. |
| Living report | Partially implemented | Manifest events, report notes, living routes, compiler, report shell, storyboard/report-designer work, and stricter report quality gates exist. Needs stronger end-to-end examples. |
| Structured EDA | Core implemented, hardening remains | Runtime plugin now exists with ledgers, tools, readiness, gates, evidence anchors, loop/multiplicity metadata, skills, examples, and tests. |
| Plotly visualization layer | Implemented enough for foundation | Plotly renderer, metric tiles, visualization skill, dashboarding skill, and app view exist. |
| Dashboarding workflow | Skill-level implementation | Dashboarding methodology exists; needs a public evidence/demo artifact. |
| Analysis review/advisory critics | Deterministic core implemented | Review plugin, append-only store, checklist tools, auto-review hook, gate sync, and approval guardrail exist. Reviewer sub-agent and Review UI are not built yet. |
| Evidence package | Partially implemented | Tests and structured EDA fixture exist; complete release evidence package is still pending. |
| Governed baseline regression | Not implemented | No `simple_regression` product workflow/plugin found. |
| Survey/secondary research | Not implemented | No `survey_secondary_research` product workflow/plugin found. |

## What Has Been Built

### 1. Artifact Platform

The V3 artifact foundation is the strongest completed area.

Implemented capabilities:

- Artifact publishing, reading, exporting, deletion, and report notes.
- Artifact validation, wrapping, versioning, manifest storage, and safe serving.
- Typed artifact/report sections for charts, metrics, findings, and structured report content.
- Richer typed sections for narrative bands, methodology blocks, evidence rails, ledger timelines, chart interpretation, interactive tables, filterable charts, chart/table explorers, selector panels, and entity-card grids.
- Artifact panel and app view in the UI.
- Publish-artifact result cards in chat.
- Plotly renderer and metric display components.
- Session-level Artifacts tab.
- Tests for artifact contracts, tool invocation, preview safety, and report-note/living-report behavior.
- Playwright preview-surface coverage for app report previews and chat living-report previews.

Why this matters:

DataClaw outputs can now become durable product surfaces instead of being trapped in transient chat text or notebook side effects.

Remaining work:

- Run a complete release evidence flow that creates artifacts from real analysis sessions.
- Confirm export/preview behavior across the main artifact types.
- Decide which artifact claims are safe to include in release notes based on tested examples.

### 2. Living Report Foundation

The living-report work is partially implemented and is now connected to the artifact layer.

Implemented capabilities:

- Manifest/event storage for report activity.
- `report_note` support.
- Living-report compiler and routes.
- Raw report chart rendering.
- Reusable workspace report renderer with typed report sections, report shell CSS/script, Plotly runtime support, storyboard rendering, and preview/document helpers.
- `report_design_report`, which plans the story/layout/interactions, writes a storyboard JSON, runs report quality checks, and renders the final report in one pass.
- Default-fail report quality gating for final report design, including completed-insight requirements, missing-primary-insight detection, chart-dump detection, interactive-explorer requirements for multi-chart reports, and stale-skill checks.
- Report size checks now ignore the embedded Plotly runtime when evaluating payload bloat, so the gate focuses on report-specific content rather than shared chart runtime code.
- Plan-step identity support so report events can attach to stable step ids.

Why this matters:

The product is moving toward preserving the investigation story: what was tried, what changed, what evidence supports a conclusion, and what is still unresolved.

Remaining work:

- Produce an end-to-end living-report demo from a real analysis workflow.
- Prove materialized checkpoints and report pages across multiple plan steps.
- Make review risks and unresolved questions visible in the report story.

### 3. Structured EDA

Structured EDA is now the most advanced V3 product workstream after artifacts.

Implemented capabilities:

- A new `dataclaw-eda` plugin with registered tools, router, hooks, store, evidence helpers, and readiness logic.
- Hypothesis ledger tools:
  - `propose_eda_hypotheses`
  - `update_eda_hypothesis`
  - `list_eda_hypotheses`
- Finding ledger tools:
  - `record_eda_finding`
  - `supersede_eda_finding`
  - `list_eda_findings`
  - `read_eda_finding`
- Readiness tool:
  - `summarize_eda_readiness`
- Append-only hypothesis and finding ledgers.
- Evidence anchors for notebook cells, artifact sections, dataset profiles, query cards, inline summaries, and interpretive notes.
- Notebook execution support for `cell_id` and source hash evidence.
- Validation floors:
  - hypothesis batches capped at 7
  - at most 3 high-priority hypotheses per batch
  - `data_signal` hypotheses require rationale
  - high confidence requires internal validation evidence
  - confirmed hypotheses require linked validated findings
  - rejected hypotheses require rejecting evidence
  - externally unverified findings are caveated and confidence-capped
- Loop observability through `loop_index` on hypothesis/finding records.
- Multiplicity metadata and floors for screened findings, including `screened_n`, selection rule, and correction requirements.
- Readiness checks for query, dashboard, and modeling purposes.
- Blockers for missing checks, open high-priority hypotheses, blocker findings, and unresolved domain input.
- Plan gate infrastructure, including required gate status, audit events, and `accept_gate_risk`.
- Guardrail requiring explicit user approval before accepting validation risk.
- Structured EDA, insight validation, and analysis review skills.
- DataClaw skill instructions now route polished visual/report deliverables through `report_design_report` with completed insights and typed aggregate assets, keeping `report_add_section` for drafts or compatibility snippets.
- Stale installed library skills are detected more reliably, including legacy unmarked copies, and the agent can use the bundled current skill body instead of stale local instructions.
- Example structured EDA fixture and expected behavior document.
- Tests for EDA tools, skill routing, PRD alignment, notebook evidence, plan gates, and related preview/security behavior.

Why this matters:

This moves EDA from prose and notebook inspection into a durable analysis system. The agent can now record what it expected, what it tested, what it found, what it rejected, what evidence supports the finding, and whether the dataset is ready for modeling, dashboarding, or further analysis.

Structured EDA phase status:

| Phase | Scope | Status |
| --- | --- | --- |
| P0 | Plan gates, `ready_for_validation`, risk acceptance, audit | Shipped |
| P1 | Hypothesis/finding ledgers, 8 EDA tools, router, hooks | Shipped |
| P2 | Notebook evidence anchors with cell ids/source hashes | Shipped |
| P3 | Readiness policies and readiness findings | Shipped, with artifact/report wiring still being hardened |
| P4 | Structured EDA, insight validation, analysis review skills | Shipped |
| P4a | Loop observability and multiplicity discipline | Shipped |
| P5 | Deterministic analysis-review checklist | Core shipped; checklist expansion remains |
| P6 | Reviewer sub-agent workflow | Not started |
| P7 | Findings/Review UI | Not started |
| P8 | Committed eval harness and live eval path | Not started |

Remaining work:

- Expand deterministic checklist coverage beyond the current core checks.
- Add reviewer sub-agent workflow if it remains in Release 3 scope.
- Build the read-only Findings and Review UI surfaces.
- Add OpenClaw alias/manifest validation for the new tools.
- Build the committed eval harness and run the structured EDA golden case.

### 4. Visualization And Dashboarding

Implemented capabilities:

- Plotly visual rendering in the app view.
- Metric tile rendering.
- Visualization skill updates.
- Dashboarding skill.
- Artifact-backed visual output path.
- Storyboard-driven report composition for dashboard/report deliverables.
- Interactive section types for filterable charts, sortable/searchable tables, chart-table explorers, selector panels, and entity-card grids.

Why this matters:

V3 can show analytical outputs as product-grade artifacts instead of raw notebook output.

Remaining work:

- Create one strong dashboarding example as release evidence.
- Validate that charts, metric tiles, and report sections render correctly across the intended artifact surfaces.
- Make sure final visual claims cite structured findings where appropriate.
- Run the new Playwright preview-surface coverage in CI and keep report/rendering bundles split cleanly.

### 5. Advisory Review / Critics

This area now has a deterministic product core, but it is not yet the full advisory critic experience.

Implemented or drafted:

- Analysis review skill/rubric.
- Plan gate infrastructure that can block validation when required gates fail or are unknown.
- Human risk-acceptance flow with audit trail.
- `dataclaw-analysis-review` plugin with append-only review runs/findings.
- Deterministic checklist tools, router, context collectors, auto-review hook, and plan-gate sync.
- Rerun auto-resolution for disappeared checklist findings.
- Guardrail requiring user approval before accepting unresolved review findings.
- PRD/design material for deterministic checklist and reviewer sub-agent.

Remaining work:

- Expand checklist coverage for MLflow/reproducibility, stale artifact evidence, export/security, denominator/grain, and richer artifact/report checks.
- Add reviewer sub-agent execution path.
- Add UI review cards and Review tab.
- Connect unresolved review risks into artifact/living-report output.

Release implication:

It is safe to say V3 has deterministic analysis-review gates and persisted review findings. It is not yet safe to claim a full reviewer/critic system until P6 reviewer execution and P7 review UI land.

## Recommended Release Scope

Recommended claims for V3 if current work lands and passes validation:

- DataClaw now supports first-class analysis artifacts.
- Artifacts can be safely served, previewed, versioned, and exported.
- DataClaw has a living-report foundation for preserving analysis history.
- Structured EDA can persist hypotheses, findings, evidence, caveats, and readiness.
- Plotly charts and metric tiles can be rendered as artifact-backed outputs.
- Dashboarding methodology is available as a guided workflow.

Claims to avoid unless more work lands:

- Fully automated critic/reviewer runtime.
- Public Pack SDK or installable public bundles.
- Generic model training or governed regression workflow.
- Survey/secondary research workflow.
- Market mapping.
- New runtime/model-routing platform claims.

## Risks And Decisions

1. Structured EDA scope needs a release decision.
   The core ledgers/gates/readiness/review-checklist work is real, but review UI, reviewer sub-agent execution, and evals are still open. We should decide whether V3 requires those before launch or whether they become follow-up hardening.

2. Evidence package is the release blocker for public claims.
   The code and tests are promising, but each public claim needs a runnable example or validation note. Without that, release notes should be conservative.

3. Advisory review should be framed carefully.
   The deterministic checklist product exists, but reviewer sub-agent review does not. Checklist-only review can clear ordinary deterministic blockers, while scopes explicitly marked `require_subagent` remain `unknown`; deciding whether high-risk model/export steps should automatically require sub-agent review is a larger P6 policy change.

4. Regression and survey workflows should be deferred unless built quickly.
   There is no implementation evidence yet for `simple_regression` or `survey_secondary_research`.

5. Report quality gates are now intentionally strict.
   `report_design_report` defaults to `fail`, requires completed insight payloads, catches missing primary insights, and fails multi-chart reports without interactive or interpretive sections. This improves release quality, but demo scripts and evidence examples need real finding/evidence payloads rather than chart dumps.

6. Frontend preview and bundle hardening has started.
   Vite manual chunking and Playwright preview-surface tests have landed for report previews and living-report previews. Keep this as a hardening track: run the Playwright suite in CI, watch Plotly/preview bundle size, and keep preview/renderers lazy-loaded where possible.

7. Integration base should be chosen deliberately.
   If structured EDA is in V3, the structured EDA implementation branch is the right integration base because it already includes the artifact platform plus EDA runtime work.

## Recommended Next Steps

1. Keep the full pytest suite green as review/plugin changes land.
2. Produce one end-to-end structured EDA demo using the committed example dataset.
3. Expand or explicitly defer the remaining P5 checklist coverage.
4. Decide whether P6 reviewer sub-agent execution is in Release 3 scope.
5. Build the Findings/Review UI or mark it post-release.
6. Refresh installed skills in the demo environment so the bundled structured EDA, dashboarding, visualization, and artifact instructions are current.
7. Create the release evidence package:
   - artifact publishing example
   - living report example
   - structured EDA example
   - Plotly/dashboarding example
   - security/preview validation note
8. Update release notes to claim only what the evidence package proves.

## Implementation Traceability

This section is for engineers who want to map the team-facing status back to implementation branches.

Baseline:

- Current mainline baseline: `origin/main`
- Baseline commit: `42c4b97`

Implementation branches reviewed:

| Branch | Delta vs `origin/main` | Summary |
| --- | --- | --- |
| `release3` | 16 commits, 75 files, +8216 / -591 | Core artifact platform, app view, plan identity, living report start |
| `structured-eda` | 29 commits, 124 files, +19397 / -792 | `release3` plus structured EDA runtime, review lifecycle, gates, storyboard report designer, stricter report quality gates, skill freshness fallback, skills, tests |
| `ui_upgrade` | 11 commits, 37 files, +4493 / -38 | Design/PRD material and chat redesign mockups; useful reference, not current integration base |

`structured-eda` is 13 commits ahead of `release3` and adds the current structured EDA implementation work, including the latest review lifecycle, workspace report renderer, storyboard report-designer, report quality gate, and skill-freshness commits. `ui_upgrade` is primarily useful as product/design reference material and should be cherry-picked selectively.

## Verification Basis

This report is based on static branch comparison and file inspection, including branch diffs, commit logs, PRDs, skills, plugin registration, EDA tools, gates, readiness code, evidence helpers, review lifecycle code, workspace report-renderer/storyboard code, report quality checks, skill freshness handling, UI report preview helpers, Playwright preview-surface tests, Vite config, and tests.

Local validation completed on 2026-07-09:

- Python tests passed using the repository's documented split across core and plugin suites: 492 passed, 10 skipped. `plugins/dataclaw-codex/tests` currently has no test files.
- `npm run build` passed for the UI, with the existing Vite large-chunk warning for vendor bundles.
- `npm run test:e2e` passed for the UI Playwright preview-surface suite: 2 passed.

A single unsplit `pytest` invocation still collides on plugin test package names during collection, so the split test run above is the reliable full local signal for this branch.
