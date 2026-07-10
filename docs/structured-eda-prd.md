# DataClaw Structured EDA Module — PRD & Solution Architecture

| | |
|---|---|
| **Status** | In build (rev 6 — status refreshed 2026-07-10; P5 complete incl. checklist expansion + FR-30a publish surfacing) |
| **Owner** | Nandini Mathan |
| **Last updated** | 2026-07-10 |
| **Branch** | `structured-eda` (base: `release3` + cherry-picked structured-EDA skill from `eda-upgrade`) |
| **Ships as** | `plugins/dataclaw-eda/`, `plugins/dataclaw-analysis-review/`, patch to `plugins/dataclaw-plans/`, patch to `plugins/dataclaw-notebooks/`, `skill-library/{structured_eda,insight_validation,analysis_review,dataclaw}.md`, `ui/src` Findings surfaces, `evals/` harness |
| **Composes with** | `plugins/dataclaw-plans`, `plugins/dataclaw-notebooks`, `plugins/dataclaw-artifacts`, `plugins/dataclaw-projects` (sub-agent registry), MLflow tooling |
| **Supersedes** | The EDA slice of `docs/eda-findings-prd.md`, `docs/analysis-review-prd.md`, and `docs/plans-contract-prd.md` §P3, integrating all three under a hypothesis-driven methodology |

---

## Release-note-first framing

DataClaw now runs **hypothesis-driven EDA with a durable, validated evidence trail**. Before deep exploration, the agent proposes explicit hypotheses — from the user's goal, the EDA mode's expected risks, domain priors, and surprises in the initial profile — and records them in a persistent ledger. Each insight loop tests the highest-value open hypothesis, validates candidate findings on two axes (internal recomputation and real-world plausibility), and records a disposition: confirmed, rejected, or needs-domain-input. Rejected hypotheses are kept, not discarded, so "did you check X?" always has an answer. Readiness verdicts cite hypothesis dispositions. A deterministic checklist plus an optional reviewer sub-agent audit the work and gate plan steps before the human spends scarce validation time. Quality is proven by behavioral tests in CI and a committed, opt-in live-model eval whose scorer reads dispositions straight from the ledger — with an LLM judge for the qualitative criteria machines can't check.

## Validation gate & degradation rule

- **Golden acceptance check:** a structured-EDA run over `examples/structured_eda/customer_events_sample.csv` must (1) propose ≥4 hypotheses spanning ≥3 sources with ≥1 later rejected-and-kept; (2) record distribution, missingness/quality, segment-comparison, and rejected-hypothesis findings, each anchored to a notebook cell id + source hash and `plan_step_id`; (3) produce a modeling-readiness verdict of `blocked` citing the leakage hypothesis as `unresolved_needs_domain_input`; (4) have the review checklist flag a seeded unsupported claim and a completed step with an open high-priority hypothesis while leaving a valid chart alone; (5) block `ready_for_validation` until findings are resolved or explicitly accepted.
- **Degradation rule:** if ledger persistence fails, EDA may continue in the notebook, but the plan step cannot be marked "EDA summarized", readiness is at best `unknown`, and artifacts/review must label the EDA section notebook-only/unstructured. If no reviewer sub-agent is configured, review degrades to checklist-only and is labeled as such; checklist-only review can never yield a `pass` gate for scopes that require a sub-agent. Degraded evidence never satisfies plan, artifact, review, or human-validation gates.

## Convergence checklist

| Surface | How this PRD uses it |
|---|---|
| Plugin | `plugins/dataclaw-eda/` and `plugins/dataclaw-analysis-review/`, auto-discovered; patches to `dataclaw-plans` and `dataclaw-notebooks` |
| Tools | EDA: `propose_eda_hypotheses`, `update_eda_hypothesis`, `list_eda_hypotheses`, `record_eda_finding`, `supersede_eda_finding`, `list_eda_findings`, `read_eda_finding`, `summarize_eda_readiness`. Review: `request_analysis_review`, `list_review_findings`, `resolve_review_finding`, `get_review_gate`. Plans: `accept_gate_risk`. Canonical unprefixed names in the shared registry |
| Hooks | `preToolCallHook` context injection; `postToolCallHook` evidence stash, auto-checklist on step completion |
| Skills | `structured_eda` (restructured hypothesis-driven), new `insight_validation`, new `analysis_review`, routing updates to `dataclaw` |
| UI | AG-UI custom events, inline finding/review cards, read-only Findings tab (read-right/act-left) |
| Sub-agents | reviewer registered through the existing sub-agent registry; sequential, bounded |
| OpenClaw | generated OpenClaw manifest/allowlist exposes canonical names or `dataclaw_...` aliases with identical schemas (auto-generated from the live registry on Install/Update) |
| Validation | golden acceptance check + OpenClaw alias/manifest check; deterministic behavioral suites in CI + committed `evals/` harness (hypothesis-disposition scoring + LLM judge, opt-in live) |

## Baseline: what this branch already provides

Verified on `structured-eda` (release3 base):

- **Plans P1/P2 done:** steps carry stable `plan_step_id` (`step-<hex8>`; legacy `id` coerced and stripped); `active_plan_context_hook` injects `session_id`/`proposal_id` and publishes `state["active_plan_step_id"]`; `update_plan` persists `ready_for_validation` and `gates` fields per step (`dataclaw_plans/tools.py:197`) — **but nothing enforces transitions (P3 is this PRD's scope)**.
- **Artifacts spine done:** validator/wrapper hardening, versioned store with append-only living-report events, typed sections incl. a `findings` kind with `plan_step_id`, `data_policy`, preview caps (`TABLE_PREVIEW_MAX_ROWS = 20`, `TABLE_PREVIEW_MAX_BYTES = 50 KiB` in `dataclaw_artifacts/sections.py`).
- **Skill + fixture cherry-picked:** `skill-library/structured_eda.md` (modes, insight-loop protocol, readiness verdicts — pure prose today), `examples/structured_eda/` (customer-events sample with seeded leakage/duplicate/negative-revenue/missingness issues + `expected_behavior.md`), `tests/test_structured_eda_skill.py`.
- **Sub-agent infra exists:** `dataclaw/providers/sub_agent/{provider,registry}.py`, `DefaultSubAgentProvider` (`agent_type="llm"`), definitions CRUD in `dataclaw-projects`; sequential delegation only; no reviewer registered.
- **Gaps this PRD fills:** no hypothesis or finding persistence; no analytical validation anywhere (artifacts validator is content-security only); no gate enforcement; notebooks tools do not return nbformat `cell_id`; no behavioral eval harness (skill tests are string containment).

**Status update (2026-07-09):** P0–P4a and the P5 review-lifecycle core are now shipped on this branch — `plugins/dataclaw-eda/` (both ledgers, all 8 tools with floors, evidence anchoring, readiness, router, hooks, tool-level tests, loop observability, and multiplicity floors), `plugins/dataclaw-analysis-review/` (append-only review store, deterministic checklist tools/router, rerun auto-resolution, plan-gate sync, auto-checklist hook), `dataclaw_plans/gates.py` with `accept_gate_risk` and the PlanCompletion guardrail wiring, the notebooks `cell_id` patch, the hypothesis-driven `structured_eda` + new `insight_validation`/`analysis_review` skills, and the FR-34a adjacent-skill touch-ups. Still open: P5 checklist expansion, P6 (reviewer sub-agent), P7 (UI), P8 (evals), and the OpenClaw alias fixture. See the phasing table's Status column.

**Status update (2026-07-10):** P5 is complete. The checklist expansion shipped — `CHK-stale-evidence` (artifact-cited EDA findings with stale evidence anchors), `CHK-mlflow-repro` (model-scope runs missing params/metrics/non-system tags, read via a new sync failure-tolerant `session_run_metadata` helper in `dataclaw_plans/mlflow_tools.py`), and `CHK-open-required-on-ready` (a step marked `ready_for_validation` with open required review findings; excludes its own prior findings so it converges) — plus the FR-30a publish surfacing: a `surface_unreviewed_publish_hook` post-hook appends an "unresolved review risk" living-report event (log page, naming finding ids) when `publish_artifact` runs with open required findings, unless the step's gate risk carries an explicit acceptance. Still open: P6 (reviewer sub-agent), P7 (UI), P8 (evals), and the OpenClaw alias fixture.

---

# Part 1 — Product Requirements

## 1. Problem

Structured EDA exists as a prose skill and notebooks compute rich exploration, but nothing the methodology prescribes is persisted or enforced:

- **Insights are transcript prose.** Observations, caveats, rejected hypotheses, and readiness judgments live in notebook markdown and chat text. "What did we learn?", "did you check missingness?", and "which evidence supports this?" require replaying the whole session.
- **The insight loop has no ledger.** The skill says "keep an insight log" — there is nowhere structured to keep it, so loops are undocumented and unauditable.
- **Exploration is not hypothesis-driven.** The agent explores reactively; there is no up-front statement of what it expects to find or check, so coverage is unmeasurable and confirmation bias is invisible.
- **Validation was unenforced pre-PRD.** Nothing distinguished a claim the agent recomputed and sanity-checked from one it eyeballed. This branch now blocks `ready_for_validation` through plan gates and the review lifecycle core; remaining work expands checklist coverage, UI, and sub-agent review.
- **Quality is untested.** The golden fixture exists but no harness runs it; skill tests assert markdown strings, not behavior.

Human validation bandwidth is the binding constraint (per the portfolio PRD). The module's job is to shrink the human's validation surface to: the hypotheses, their dispositions, the evidence, and the unresolved risks.

## 2. Goals

- **G1** — Make EDA hypothesis-driven: explicit, prioritized, persisted hypotheses proposed before deep exploration and dispositioned through insight loops.
- **G2** — Capture observations as durable finding cards with evidence anchors (notebook cell id + source hash, dataset, `plan_step_id`) and two-axis validation state.
- **G3** — Preserve rejected hypotheses and superseded findings append-only; belief changes and evidence changes are separately auditable.
- **G4** — Make readiness purpose- and mode-specific, machine-evaluated, and citing hypothesis dispositions.
- **G5** — Gate `ready_for_validation` on review state with an append-only audit trail and an explicit human escape hatch.
- **G6** — Review analysis deterministically first (checklist), with an optional scoped reviewer sub-agent; checklist-only review is visibly degraded.
- **G7** — Prove behavior with deterministic CI tests and a committed opt-in live eval whose scorer reads ledger dispositions; LLM judge for qualitative criteria.
- **G8** — Keep the split: skills decide, plugins execute and persist; notebooks compute; the plan is the spine; the right panel reads, the chat acts.

## 3. Non-goals

- No automated exhaustive EDA engine; the skill's judgment (modes, loop budget, stop rules) still governs.
- No causal-claim proving; validation raises confidence floors, it does not certify correctness.
- No parallel multi-agent orchestration in this pass; the reviewer is one sequential, bounded sub-agent. The concurrency model (§8, D13) names what parallelizes now (evals, batched routine checks), next (async review), and later (reviewer panel, hypothesis workers) — and the prerequisites for each.
- No dataset versioning/profiling plugin (intake), query cards, or model cards in this pass — schemas leave room, collectors scope to what exists.
- No cross-session/dataset-level findings aggregation in this pass (explicit deferral — see Open Questions).
- No chart rendering surface; artifacts owns final visuals.

## 4. Users & Use Cases

| # | Use case | What must be true |
|---|---|---|
| U1 | "Explore this dataset for churn modeling" | Agent proposes hypotheses (goal + mode risks + domain priors), tests them in loops, records dispositions |
| U2 | "What did we learn? What did you rule out?" | Findings panel lists findings and hypotheses by disposition; rejected hypotheses are first-class |
| U3 | "Did you check missingness?" | A missingness finding or a rejected/covered hypothesis is searchable in the ledger |
| U4 | "This finding changed after filtering" | Old finding superseded with reason; linked hypothesis flagged for re-evaluation |
| U5 | "Can we model yet?" | Readiness verdict cites blockers: findings, missing required checks, open high-priority hypotheses |
| U6 | "Why is this step not ready?" | Gate state names blocking review findings; audit shows who set what, when, why |
| U7 | "Which cell produced that?" | Finding anchors to nbformat cell id + source hash; stale anchors are flagged |
| U8 | "Don't overstate this" | Confidence is capped without internal validation evidence; unverified-external carries a mandatory caveat |
| U9 | "No reviewer model configured" | Checklist-only review runs, is labeled, and cannot pass sub-agent-required gates; user can explicitly accept |
| U10 | "Is the module actually good?" | `evals/` runs the golden case live, scores dispositions deterministically, judge reports qualitative criteria |

## 5. Functional Requirements

### 5.1 Hypothesis ledger (`plugins/dataclaw-eda`)

- **FR-1** `propose_eda_hypotheses(hypotheses, dataset_id, ...)` records a batch. Each entry: `statement`, `rationale`, `source ∈ {user_goal, mode_expected_risk, domain_prior, data_signal, prior_finding, reviewer}`, `priority ∈ {high, medium, low}`, optional `covers_checks`.
- **FR-1a** Position in the plan flow (aligns with `dataclaw.md` steps 4/7): the initial batch (`user_goal`/`mode_expected_risk`/`domain_prior` sources) is proposed **during pre-plan initial EDA** — hypothesis proposal is a ledger write, exempt from plan approval like minor EDA. `plan_markdown` must cite the initial hypothesis set under "what is already known from previous inspection", so approving the plan implicitly ratifies the hypothesis set. `data_signal`, `prior_finding`, and `reviewer` hypotheses accrue during execution. If the user denies or materially revises the plan, hypotheses tied to the abandoned direction are transitioned `out_of_scope` with the revision as the reason — the ledger never silently carries a rejected direction forward. Pre-plan hypotheses naturally carry no `plan_step_id`; step attribution attaches at test time through the finding that dispositions them — the `unattributed_step` degradation rule (FR-11) governs finding evidence, not hypothesis proposals.
- **FR-2** The initial batch is capped at **7 hypotheses** and at most **3 may be `high` priority** (aligned with the loop budget — see D3). The tool rejects larger batches with a structured error telling the agent to prioritize. Later batches are allowed (new `data_signal` hypotheses legitimately emerge), but the per-batch cap cannot be evaded into spam: the tool returns a warning once a dataset's open-hypothesis count exceeds 10, and the eval's precision penalty (FR-40) is the behavioral backstop.
- **FR-3** `source="data_signal"` hypotheses must cite the prompting observation in `rationale` (non-empty, referencing a column/statistic); the tool rejects empty rationales for this source.
- **FR-4** `update_eda_hypothesis(hypothesis_id, status, disposition_reason, linked_finding_ids, priority)` appends a transition record. Statuses: `open, testing, confirmed, rejected, unresolved_needs_domain_input, out_of_scope`. Effective state is a fold of the append-only log; odd transitions (e.g. `rejected → confirmed`) are recorded with a warning, never blocked — history is the audit.
- **FR-5** `confirmed` requires ≥1 linked finding whose `validation.internal.status == "validated"`; `rejected` requires ≥1 linked finding (the rejecting evidence, `finding_type: rejected_hypothesis`). Enforced by the plugin.
- **FR-6** `list_eda_hypotheses(filters)` filters by dataset, plan step, status, source, priority.

### 5.2 Finding cards

- **FR-7** `record_eda_finding(title, finding_type, summary, evidence, dataset_id, ...)` per the EDA-findings PRD, extended with: `hypothesis_id` + `hypothesis_status` (records the finding and the hypothesis link/transition atomically in one call), `disposition ∈ {confirmed, weakened, rejected, unresolved, blocked}`, `validation` (below), `covers_checks`.
- **FR-8** Finding types: `distribution, missingness, outlier, segment_difference, correlation_candidate, leakage_risk, readiness, rejected_hypothesis, data_quality, caveat`. When `hypothesis_status="rejected"` is passed, `finding_type` is auto-set to `rejected_hypothesis` — the agent never juggles the three "rejected" vocabularies by hand (D9).
- **FR-9** Two-axis validation state on every finding:
  `validation.internal ∈ {validated, failed, not_checked}` with `method` and `evidence_refs`; `validation.external ∈ {validated, unverified, implausible, not_checked}` with `basis ∈ {domain_prior, reference_lookup, user_confirmation, none}` and `note`.
- **FR-10** Plugin-enforced floors (deterministic, not judgment): `confidence="high"` requires `validation.internal.status="validated"` **with non-empty `evidence_refs`** (a real anchor — self-report without evidence is rejected); `validation.external.status="unverified"` auto-appends the caveat *"unverified against external evidence"* and caps confidence at `medium`. These are floors, not proofs — the review layer and evals are the backstop for honesty (D4).
- **FR-10a** Multiplicity discipline (statistical): when a hypothesis or finding originates from screening many candidates — segment sweeps, correlation scans, `data_signal` surprises spotted while browsing — records carry optional selection metadata `selection: {screened_n, selection_rule, correction: none|fdr_bh|bonferroni|holdout_confirmed}`. Floors: internal validation of a screened insight does not count as `validated` unless the confirmation accounts for selection — a correction across the screen, or confirmation on an independent slice (the FR-32 independent-slice recompute doubles as split-sample confirmation, `correction: holdout_confirmed`); `confidence="high"` with `selection.screened_n > 5` requires `correction != "none"`. Findings that report significance prefer effect sizes with uncertainty over bare p-values. Without this, an agent testing 7 ledger hypotheses plus ad-hoc segment scans on one dataset will inevitably "confirm" spurious patterns — the garden of forking paths, mechanized.
- **FR-11** Evidence anchors: `notebook_cell` (nbformat `cell_id` + `source_sha256`, `stale` flag), `artifact_section`, `dataset_profile`, capped `inline_summary` (shared 20-row/50-KiB caps), `interpretive_note`; `query_card` is a reserved kind for the future Query Lab plugin (schema stays portfolio-compatible without it existing). Cell references never rely on index alone. Evidence recorded without a `plan_step_id` (no active plan) is labeled `unattributed_step` and cannot satisfy plan, artifact, review, or human-validation gates (portfolio degradation rule).
- **FR-11b** Loop observability: `record_eda_finding` and `update_eda_hypothesis` accept an optional `loop_index` (1-based within the current EDA pass), persisted on the records. This makes the loop budget (≤3 per pass) and the reserved-surprise rule machine-checkable from the ledgers (Tier 1/2) rather than judge-narration-only; the skill passes it at the Decide step. Runtime note: the insight loop is not a code construct — it is enacted by the main agent across LangGraph turns under the skill's protocol, so `loop_index` is the only durable trace a loop leaves.
- **FR-12** `supersede_eda_finding(finding_id, reason, replacement_id?)` appends a supersede edge; never deletes. If the superseded finding was linked evidence for a `confirmed`/`rejected` hypothesis, the supersede call **also appends a `hypothesis_update` record** flagging `needs_reevaluation: true` (written at supersede time, same write-order rules as NFR-2 — the hypothesis fold never has to scan the findings store), and the review checklist flags it (D8).
- **FR-13** `list_eda_findings(...)` (incl. `hypothesis_id` filter) and `read_eda_finding(finding_id)` support review and reporting.
- **FR-13a** Findings-as-sections contract closure: the `findings`-kind artifact section item schema (in `dataclaw_artifacts/sections.py` and the `visualization` skill's section contract) gains optional `finding_id` and `hypothesis_id` fields so published findings sections can anchor back to ledger records. Without this, agents faithfully following the `visualization` skill would emit unanchored findings sections and `CHK-unsupported-claims` would misfire. Section meta gains a `section_schema` integer so the check can scope by era: it applies only to sections with `section_schema ≥ 2` (created after this ships).

### 5.3 Readiness

- **FR-14** `summarize_eda_readiness(dataset_id, purpose, required_checks?, mode?)` evaluates purpose defaults (`query`/`dashboard`/`modeling`) plus mode overlays (one per structured_eda mode); the skill passes `mode`/`required_checks` at verdict time — skill configures, plugin evaluates.
- **FR-15** A named check is satisfied by an active finding whose `finding_type` maps to it or whose `covers_checks` names it — a rejected hypothesis covering "leakage_risk" counts as "we looked".
- **FR-16** Statuses: `ready, ready_with_caveats, blocked, unknown`. `blocked` on: active blocker-severity findings, missing required checks, or **high-priority hypotheses still `open`/`testing`**. Hypotheses that are open **because the loop budget ran out** (untested, agent so marks them via `update_eda_hypothesis(status="open", disposition_reason="deferred: loop budget")`) surface as *caveats with a named next action*, not blockers — only genuinely unresolved evidence blocks (D3).
- **FR-17** The verdict includes a hypothesis rollup (counts per status + cited entries) and persists as a supersedable `readiness`-type finding record. `unresolved_needs_domain_input` hypotheses always surface as explicit questions for the user.

### 5.4 Plans gate enforcement (patch to `dataclaw-plans`)

- **FR-18** New `dataclaw_plans/gates.py`: `set_step_gate(...)` patches a step's `gates` metadata and snapshots (`trigger="gate"`); every transition appends to `plugin_data_dir("plans")/gate_events.jsonl` (actor, previous, new, reason) — append-only audit.
- **FR-19** `GATE_RESOLVERS` registry: other plugins register live gate evaluators by name; plans never imports review (no cycle).
- **FR-20** `update_plan` rejects a patch setting `ready_for_validation: true` when any **required** gate is `fail` or `unknown` (stored or live-resolved), returning structured `{error: {code: "gate_blocked", plan_step_id, blocking_gates}}`. Setting `false` is always allowed. Both outcomes are audited.
- **FR-21** **Gate policy (which steps require review):** default `required: false`. A gate becomes required when (a) the step's `outputs`/description mark it as modeling, export, or external-share work (policy list in `gates.py`), (b) the review plugin's auto-checklist found `required`-severity findings on it, or (c) the user/skill explicitly sets it. Trivial steps are never blocked by default (resolves the "gates block everything or nothing" hole).
- **FR-22** **Escape hatch:** `accept_gate_risk(proposal_id, plan_step_id, gate_name, rationale)` records an explicit acceptance in the audit log and unblocks the transition. **It requires user approval**: the tool is registered behind the existing guardrail approval flow (the same mechanism that gates other high-risk tools in `chat.py`), so the agent cannot silently self-accept a gate it is blocked on — in auto mode with no user present, the call fails with a structured "requires user approval" error. The `analysis_review` rubric and the eval judge both treat agent-initiated acceptance without user instruction as a violation. Checklist-only degradation plus acceptance is visible in the plan panel and final artifacts — an unknown gate is never a silent dead end (resolves the deadlock).
- **FR-23** **Consumption:** the existing `PlanCompletion` guardrail is extended — when the agent produces a final summary while approved-plan steps lack `ready_for_validation` (and their gates are required), the guardrail injects a warning the agent must surface. Delivery is not silently blocked; unreadiness is made visible (resolves "nothing consumes the flag").
- **FR-24** `update_plan`'s schema declares `ready_for_validation` and `gates` (currently applied but undeclared); `GET /plans/{id}/gates` exposes per-step gate state + recent audit events.

### 5.5 Analysis review (`plugins/dataclaw-analysis-review`)

- **FR-25** Tools per the analysis-review PRD: `request_analysis_review(scope, target_id?, plan_step_id?, severity_floor, require_subagent)`, `list_review_findings(...)`, `resolve_review_finding(finding_id, status, rationale, evidence_link?)` (append-only resolutions), `get_review_gate(scope, target_id)`. Valid scopes in this pass: `plan_step`, `artifact`, `living_report`, `session`; `query_card` and `modeling_spec` are reserved for the future Query Lab / Modeling plugins. Finding categories keep the full analysis-review enum — `unsupported_claim`, `data_quality_caveat`, `denominator_grain`, `reproducibility_gap`, `misleading_visualization`, `broken_link`, `security_export_risk`, plus `hypothesis_hygiene` (new), with `query_risk` and `modeling_comparability` reserved. Resolution statuses: `open`, `resolved`, `accepted_with_rationale`, `dismissed_as_not_applicable`.
- **FR-26** Context is structured extraction only — plan step record, EDA hypotheses + findings (full records), artifact section metadata parsed from `data-dc-section-meta` JSON blocks, living-report events, notebook cell summaries, MLflow run metadata. Raw artifact HTML is never given to the reviewer. Excerpts capped at 50 KiB.
- **FR-27** Deterministic checklist (P1), each check id-tagged (`source: "checklist:<id>"`):

| id | Check | Severity |
|---|---|---|
| CHK-artifact-validation | artifact has unresolved validation errors | required |
| CHK-step-no-findings | step `completed` with zero findings and no "no material findings" caveat record | required |
| CHK-open-hypotheses | step `completed` with linked high-priority hypotheses still `open`/`testing` (excluding budget-deferred) | required |
| CHK-hypothesis-no-evidence | hypothesis `confirmed`/`rejected` with empty `linked_finding_ids` | required |
| CHK-hypothesis-stale-evidence | hypothesis marked `needs_reevaluation` (evidence superseded) | required |
| CHK-unvalidated-confirmed | finding `disposition="confirmed"` with internal validation `not_checked` | required |
| CHK-overconfident-unverified | external `unverified` with `confidence="high"` or missing the mandatory caveat | warning |
| CHK-unsupported-claims | `findings`-kind artifact sections (created after FR-13a ships) whose items carry no finding id/evidence anchor | required |
| CHK-stale-evidence | artifact-cited finding evidence marked `stale` | warning |
| CHK-chart-metadata | chart sections missing title/caption in section meta | warning |
| CHK-readiness-missing | step claims EDA done with no readiness record, or readiness `blocked`/`unknown` | required |
| CHK-mlflow-repro | model-scope MLflow runs missing params/metrics/tags | warning |
| CHK-multiplicity | `confirmed` finding from a screen (`data_signal` source) with missing `screened_n` or `correction: none` | warning |
| CHK-open-required-on-ready | `ready_for_validation` requested with open required review findings | required |

- **FR-28** Reviewer sub-agent (P2): definition `analysis-reviewer` (agent_type `llm`, `max_turns: 6`) registered via `dataclaw-projects`; the system prompt is rendered from `analysis_review.md` **at request time, not registration time**, so rubric edits take effect without re-registration. Allowed tools are read-only metadata only: `list_eda_hypotheses, list_eda_findings, read_eda_finding, get_plan, list_review_findings, list_artifacts` — **not** `read_artifact` (raw HTML is an injection surface) and **no data-query tools**. Consequence, stated plainly: the reviewer audits *coherence between claims, ledger state, and evidence anchors*; it cannot independently recompute results. Golden expectations are set accordingly (D7): it must catch unsupported claims, ledger hygiene violations, and internally-contradictory findings — not arbitrary numerical errors. A capped read-only query tool is a deliberate deferral (Open Questions).
- **FR-29** Reviewer output: fenced JSON findings array; parse failures keep checklist findings and label the run `mixed` with `subagent_parse_error`. Reviewer-proposed hypotheses arrive as review findings; only the main agent records them (`propose_eda_hypotheses(source="reviewer")`) — the reviewer never mutates analysis state.
- **FR-30** Gate computation: `fail` on open required findings; `unknown` when no run exists or checklist-only ran where a sub-agent is required; else `pass`. Every run/resolution writes the plans gate via `set_step_gate` and registers the live resolver. Auto-trigger: checklist only, on step completion; sub-agent review is always explicit.
- **FR-30a** Publish/export surfacing (analysis-review FR-13): when `publish_artifact` runs while unresolved `required` review findings exist for the session/step, the post-hook appends an "unresolved review risk" living-report event naming the finding ids, and the artifact's living-report section is labeled accordingly — unless the findings were explicitly `accepted_with_rationale` or the gate risk was accepted via `accept_gate_risk`. Unreviewed exports are never silently clean.

### 5.6 Skills (decide; plugins persist)

- **FR-31** `structured_eda.md` restructure: a **Hypothesis ledger** step lands after the column role map — enumerate candidates from the four sources (with a per-mode expected-risk seed table aligned to the readiness overlays), prioritize within the FR-2 caps, one `propose_eda_hypotheses` batch; untestable/irrelevant candidates are recorded and immediately `out_of_scope` with a reason. Insight loops become hypothesis tests: pick the top open hypothesis **or a new data-signal surprise (at least one loop is reserved for emergent surprises when any exist — anti-tunnel-vision rule, D2)**; Validate via `insight_validation`; Decide via `record_eda_finding(hypothesis_id, hypothesis_status, disposition)`; Update via supersede + re-prioritization. **Loop budget and stop rules unchanged** (max 3 per pass; routine mode-required checks — missingness sweep, duplicate scan — run in the standard sequence and do not consume loops). Untested leftovers are explicitly deferred (`disposition_reason: "deferred: loop budget"`), which readiness treats as caveats, not blockers. Readiness step calls `summarize_eda_readiness(purpose, mode)` and presents the disposition rollup.
- **FR-32** New `insight_validation.md`: two-axis validation before any `confirmed`. Internal: recompute on an independent slice (segment/time/missingness cohort); check denominator/grain against the unit-of-observation statement; scan `list_eda_findings`/`list_eda_hypotheses` for contradictions and supersede candidates; check plan assumptions; `query_mlflow_runs` for model claims — record method + evidence refs. External: magnitude/direction sanity against the mode's domain priors; known constraints (valid ranges, business/regulatory definitions, sampling design); external reference lookup only where deployment tools exist (`basis: reference_lookup`); user confirmation (`basis: user_confirmation`); otherwise the mandatory unverified caveat + confidence cap (the plugin enforces the floor; the skill explains it). Decision matrix maps outcomes to dispositions. One loop, one check, one decision.
- **FR-32a** Multiplicity step in internal validation: before any `confirmed`, state how the candidate was found — a targeted test of a pre-registered hypothesis, or a screen across many candidates. For screened candidates, record `screened_n`/`selection_rule` and choose correction-or-holdout per FR-10a. A pre-registered hypothesis (proposed before looking at the pattern) needs no correction — that asymmetry is the payoff of the hypothesis-first design: the ledger *is* the pre-registration record.
- **FR-33** New `analysis_review.md` (rubric, rendered into the reviewer's system prompt): audit hypothesis-ledger coverage first (mode-expected risks enumerated? open high-priority on completed steps? confirmed/rejected without linked evidence? stale-evidence flags?), then claims→anchors, denominators/grain *as represented in the evidence*, repro fields, visualization honesty, caveat completeness, both validation axes. Output contract and no-mutation rule stated explicitly.
- **FR-34** `dataclaw.md` routing (+ OpenClaw skill mirrors): initial hypotheses proposed during pre-plan EDA and cited in `plan_markdown` (FR-1a); readiness before proposing modeling/dashboard work; `request_analysis_review` + `get_review_gate` before `ready_for_validation`; `accept_gate_risk` only on explicit user instruction.
- **FR-34a** Adjacent-skill contract touch-ups (same phase, small additive edits): `artifacts.md` — for EDA findings, `record_eda_finding` **is** the living-report entry; `report_note` remains for non-EDA interpretation, decisions, and course changes (prevents double-logging on the analyses page, superseding its "one note per finding" guidance for EDA). `visualization.md` — document the `finding_id`/`hypothesis_id` fields on findings-section items (FR-13a) and fix the section-contract example's `plan_step_id` to the real `step-<hex8>` format. `dashboarding.md` — name the findings ledger and readiness verdict as the canonical inputs for the "exploratory briefing" (ranked findings, evidence per finding) and "data quality report" (readiness verdict) archetypes.

### 5.7 UI (read-right / act-left)

- **FR-35** Inline renderers: `EdaFindingCard` (compact; severity-colored; expandable evidence/caveat/validation; supersede and readiness variants) and `ReviewCard` (gate tag; **prominent "checklist-only" badge** — degraded review can never masquerade); dispatch in `ToolResultRenderer` with a `dataclaw_` prefix-normalization helper so OpenClaw-aliased calls hit the same renderers.
- **FR-36** One new sidebar tab **Findings** hosting an EDA view (hypotheses grouped with their findings; group-by hypothesis/plan-step/dataset/severity plus type and status filters, per the EDA-findings PRD FR-12; supersede history collapsed with strikethrough; pinned readiness block naming open-hypothesis blockers and deferred items) and a Review view (runs newest-first, reviewer-type badges, findings by severity/category). Strictly read-only; no action buttons; unread badge, no auto tab-switch.
- **FR-37** Hooks `useFindings`/`useReviews` mirror `usePlans` (poll backstop + refresh on stream tool results). AG-UI custom events (`eda_hypothesis_proposed|updated`, `eda_finding_recorded|superseded`, `eda_summary_ready`, `analysis_review_*`) handled like `artifact_published` (synthesize completed tool calls when none live; dedupe by id; event counters trigger REST refresh).

### 5.8 Evaluation (`evals/` in the committed tree + CI suites)

- **FR-38** Deterministic behavioral suites run in default CI: plugin tool-level goldens (record/supersede/fold/readiness/caps; checklist precision — flags seeded issues, leaves valid work alone; gate matrix incl. checklist-only-never-pass), scripted-agent loop tests over real tool callables + hooks, TestClient `/api/tools/.../invoke` tests pinning REST shapes, AG-UI emit tests. The three portfolio shared acceptance fixtures are implemented as reusable helpers: `assert_openclaw_tool_aliases` (live `write_tool_manifest`, schema identity for all 13 tools), `assert_preview_cap` (rendered cards/sections obey the shared caps), `assert_plan_step_identity` (persisted evidence uses `plan_step_id`; names are display-only). `tests/test_prd_alignment.py` is extended to cover this PRD's contracts and to skip gracefully when local-only planning PRDs are absent.
- **FR-39** Committed `evals/` package: runner CLI, harness (isolated `DATACLAW_HOME`; `TestClient(create_app())` for full plugin discovery; agent/judge LLMs via `llm_from_config` env overrides with a **guard against its silent mock fallback**; workspace seeding; `run_loop_streaming` with per-case turn/wall-clock budgets; auto plan-approval; snapshots via REST + raw JSONL), per-case fixture directories (`case.yaml`, `hypotheses.yaml`, `expected.yaml` referencing — not copying — `examples/` data).
- **FR-40** Hypothesis-driven scoring, three tiers: **Tier 1 (required)** deterministic assertions over persisted records (required finding types, anchors present, readiness verdict matches, enum coverage — enums imported from `dataclaw_eda.store`, never re-declared). **Tier 2 (required)** seeded-hypothesis disposition matching read directly from the ledger; matchers structured-first (columns + finding_type), keyword fallback; **expected dispositions are sets** (e.g. leakage → `{unresolved_needs_domain_input, rejected}`) and the tier passes at a threshold (default ≥ 4/5), with **precision counter-pressure**: >2× seeded-hypothesis count in the ledger, or >40 % generic/boilerplate entries as judged in Tier 3, fails the hypothesis-quality criterion (anti-spam, D2). **Tier 3 (advisory at first)** LLM judge — separate configurable model, structured `JudgeVerdict` (per-criterion pass/score/rationale/evidence refs), rubric derived from `expected_behavior.md` + the skill; judge is reserved for qualitative criteria (overstatement, caveat quality, hypothesis specificity, multiplicity awareness in prose) — anything machine-checkable stays in Tiers 1–2; with FR-11b, loop-budget adherence moves from judge narration to a Tier-1 ledger assertion.
- **FR-41** Gating: pytest marker `live_eval` + `DATACLAW_LIVE_EVAL=1`; default CI runs a harness smoke test with a scripted agent + fake judge (asserts scorer sensitivity: omitting the leakage finding fails Tier 2). Results dir gitignored; per-run `summary.md` + JSON reports; runner exits nonzero on required-tier failure.

## 6. Non-functional Requirements

- **NFR-1 Durability** — all ledgers append-only with atomic writes; indexes rebuildable from the logs; corrupt trailing lines tolerated (skip + warn), never session-fatal.
- **NFR-2 Cross-store consistency** — no cross-file transactions exist; write order is fixed (finding first, hypothesis link second, living-report event last) and readers/index-rebuilds tolerate and heal dangling links. Documented as a known property, not discovered as a bug.
- **NFR-3 Reproducibility** — every finding carries evidence refs or is marked interpretive; `validated` without evidence refs is rejected at the tool boundary.
- **NFR-4 Privacy/caps** — inline evidence obeys the shared 20-row/50-KiB caps with control-character redaction; no raw row dumps.
- **NFR-5 Signal, not transcript** — hypothesis caps (FR-2), loop budget, compact-by-default cards, and eval precision pressure keep the ledger smaller than the chat, or the design has failed.
- **NFR-5a Performance** — listing/filtering handles hundreds of findings and dozens of hypotheses per session (index-backed reads; panel group-collapses by default).
- **NFR-6 Honesty boundary (stated)** — validation fields are agent-reported. Plugin floors verify *shape* (evidence present), the checklist verifies *consistency*, the reviewer verifies *coherence*, evals verify *outcomes*. No layer proves correctness; each narrows the gap.
- **NFR-7 Cost** — checklist review is free (deterministic) and auto-runs; sub-agent review is explicit and bounded (6 turns); judge is one non-streaming call; live evals are opt-in with per-case budgets.
- **NFR-8 Concurrency** — per-request context flows through `tool_input` injection (race-free); the single evidence stash follows the codebase's existing module-global pattern, keyed by session, with the risk commented (accepted, consistent tech debt).

## 7. Phasing & Exit Criteria

Status column updated against the current structured-EDA branch state on 2026-07-09.

| Phase | Scope | Exit test | Status |
|---|---|---|---|
| P0 — Plans gates | `gates.py`, `update_plan` enforcement, gate policy + `accept_gate_risk`, audit log, schema declaration, PlanCompletion extension | rename/update/gate golden: attribution stable; blocked → accepted via escape hatch; audit complete | **Shipped** (`dataclaw_plans/gates.py`, guardrail wired to `plan_completion_warnings_sync`, plans tests) |
| P1 — EDA ledgers | plugin skeleton, both stores + enum constants, 8 tools + floors, AG-UI events, router, context hook | tool-level goldens green; caps + floors enforced; alias fixture passes | **Shipped** (`plugins/dataclaw-eda/`: store/tools/router/hooks + `tests/test_eda_tools.py`); alias fixture still pending |
| P2 — Evidence | notebooks `cell_id` patch, anchor resolution, evidence stash, stale flags | finding links to producing cell by id+hash; stale path covered | **Shipped** (`dataclaw_eda/evidence.py`, notebooks `cell_id` patch) |
| P3 — Readiness | purpose/mode policies, hypothesis rollup, deferred-vs-unresolved distinction, artifact sections + living-report events | leakage blocks modeling; budget-deferred hypothesis is caveat not blocker; verdict persists supersedable | **Shipped** (`dataclaw_eda/readiness.py`; sections wiring partially in WIP) |
| P4 — Skills | `structured_eda` restructure, `insight_validation`, `analysis_review`, `dataclaw` routing, OpenClaw mirrors, skill tests | skill tests assert hypothesis step, loop wiring, reserved-surprise-loop rule, caveat rule | **Shipped** (hypothesis-driven `structured_eda`, new `insight_validation`/`analysis_review`, routing + mirrors, FR-34a touch-ups) |
| P4a — Loop observability & multiplicity | `loop_index` on ledger records (FR-11b), selection/multiplicity metadata + floors (FR-10a), skill multiplicity step (FR-32a) | loop budget and multiplicity discipline machine-checkable from the ledgers | **Shipped** (`loop_index` + `selection` schemas/persistence/floors in `dataclaw_eda`; structured_eda loop paragraph; tests) |
| P5 — Review checklist | review store/tools/router, context collectors, deterministic checks (+`CHK-multiplicity`), gates wiring, auto-checklist hook, FR-30a publish surfacing | checklist golden: flags seeded issues; gate blocks, clears by resolution, and auto-resolves disappeared checklist findings on rerun; unreviewed publish is labeled | **Shipped** (full FR-27 catalog incl. `CHK-stale-evidence`/`CHK-mlflow-repro`/`CHK-open-required-on-ready`, `surface_unreviewed_publish_hook`, `session_run_metadata` in `dataclaw_plans/mlflow_tools.py`; covered in `tests/test_review_tools.py`) |
| P6 — Reviewer sub-agent | definition + rubric rendering, direct-provider run, JSON parsing, degradation labeling | seeded fixture: unsupported claim + ledger-hygiene finding caught; checklist-only never passes required gate | **Not started** (`analysis_review.md` rubric exists) |
| P7 — UI | hooks, inline cards, Findings tab (EDA + Review views), AG-UI handlers | manual: cards stream, panel groups by hypothesis, readiness pinned, badge not auto-switch | **Not started** |
| P8 — Evals | `evals/` package, golden case, three tiers, smoke test, live run | smoke green in CI; live run Tiers 1–2 pass at thresholds; judge report generated | **Not started** |

Deterministic tests land inside each phase, not as a trailing phase. P0/P1 are parallel-safe; P4 requires P1's tool names frozen; P5 needs P0+P1 (+P3 for the readiness check); P7 needs P1/P5 REST shapes; P8 needs P1–P6.

## 8. Success Metrics

- Every completed EDA plan step has ≥1 finding or an explicit "no material findings" record, and no non-deferred high-priority hypothesis left open — enforced by checklist, measured by evals.
- "Did you check X?" is answerable from the ledger (rejected hypotheses present) without replaying the transcript.
- Final artifacts cite finding ids instead of copying notebook prose; unsupported-claim checklist findings on golden notebooks → zero after fixes.
- Live eval Tier 1–2 pass at thresholds on the golden case; hypothesis precision does not degrade as the skill is tuned (anti-theater metric).
- Human validation time falls: the plan panel + Findings tab + review card suffice to approve or bounce a step without reading the whole notebook.

---

# Part 2 — Solution Architecture

## 1. System context

| Piece | Role |
|---|---|
| `skill-library/structured_eda.md` | decides modes, hypothesis generation, loop usage, when to record/supersede/summarize |
| `skill-library/insight_validation.md` | decides how a candidate insight earns `confirmed` (two axes) |
| `skill-library/analysis_review.md` | review lifecycle guidance and reviewer rubric; rendered into the sub-agent system prompt for P6 |
| `plugins/dataclaw-eda` | persists hypotheses + findings + readiness; enforces floors; emits events |
| `plugins/dataclaw-plans` (patch) | gate enforcement, audit, escape hatch, resolver registry |
| `plugins/dataclaw-analysis-review` | checklist + reviewer sub-agent; review cards; writes plan gates |
| `plugins/dataclaw-notebooks` (patch) | returns nbformat `cell_id` for evidence anchoring |
| `plugins/dataclaw-artifacts` | consumes findings as typed sections; living-report event log |
| `evals/` | committed harness: hypothesis-disposition scoring + LLM judge |

## 2. Workflow and agent interactions

### 2.1 Pipeline summary

```
GOAL       structured_eda: mode + unit-of-observation + role map
PROPOSE    propose_eda_hypotheses (≤7, ≤3 high; 4 sources)        → hypotheses.jsonl
EXPLORE    notebook cells compute; routine mode checks (no loop cost)
LOOP ×≤3   pick top open hypothesis | emergent surprise (≥1 reserved)
  VALIDATE insight_validation: internal recompute + external plausibility
  DECIDE   record_eda_finding(hypothesis_id, hypothesis_status,
           disposition, validation, evidence)                     → findings.jsonl (+ link)
  UPDATE   supersede_eda_finding / re-prioritize; deferred leftovers marked
VERDICT    summarize_eda_readiness(purpose, mode)                 → readiness record (cites dispositions)
REVIEW     auto checklist on step completion; explicit sub-agent   → review findings → set_step_gate
GATE       update_plan(ready_for_validation) blocked on required fail/unknown
           accept_gate_risk = audited human escape hatch
SURFACE    inline cards; Findings tab; living report; artifact sections
EVAL       evals/: Tier1 records, Tier2 dispositions (thresholded sets), Tier3 judge
```

### 2.2 Runtime actors

One main agent, one optional bounded sub-agent, deterministic plugins between them. Skills are fetched
instructions, not processes — they change what the main agent decides, never who executes.

```
┌─ LEFT: chat (acts) ────────────────────┐      ┌─ RIGHT: panels (read-only) ───────────────┐
│  user ⇄ main agent (LangGraph loop)    │      │  Plan panel · Findings tab (EDA | Review) │
│  skills fetched into context:          │      │  Artifact library / living report         │
│   dataclaw → structured_eda →          │      └───────────▲───────────────────────────────┘
│   insight_validation → visualization/  │            REST reads + AG-UI custom events
│   dashboarding/artifacts               │
└───────────────┬────────────────────────┘
                │ tool calls   (preToolCallHook injects session/proposal/plan_step_id;
                ▼              postToolCallHook stashes evidence, auto-runs checklist)
  plugins (persist / enforce)
    dataclaw-eda ············ hypotheses.jsonl · findings.jsonl · readiness records
    dataclaw-plans ·········· proposals + snapshots · gate_events.jsonl · blocks ready_for_validation
    dataclaw-analysis-review · review runs + findings · checklist · delegates to reviewer
    dataclaw-notebooks ······ kernel + cells (evidence: cell_id + source hash) · MLflow env
    dataclaw-artifacts ······ published artifacts · living report (sections cite finding ids)
                │
                ▼ delegated by dataclaw-analysis-review (sequential, ≤6 turns)
  reviewer sub-agent (read-only tools; structured context manifest; returns JSON findings)
```

### 2.3 End-to-end sequence

**Phase A — goal and hypotheses (pre-plan, FR-1a)**

```
user  → agent   "is this dataset ready for a churn model?"
agent → skills  fetch_skill(dataclaw) → fetch_skill(structured_eda)
agent → data    preview/profile/describe (initial EDA; quick inspection tools)
agent → eda     propose_eda_hypotheses(batch ≤7, ≤3 high; user_goal/mode_expected_risk/domain_prior)
                → hypotheses.jsonl; AG-UI eda_hypothesis_proposed → Findings tab
```

**Phase B — plan approval (human interaction #1)**

```
agent → plans   propose_plan(steps, plan_markdown citing the hypothesis set)
UI    ← plans   pending-plan banner (left chat card; right panel mirrors read-only)
user  → agent   approve / deny / revise (plain chat message)
agent → eda     on deny/revision: update_eda_hypothesis(out_of_scope, reason=revision)
```

**Phase C — execution and insight loops (per approved step)**

```
agent → notebooks  execute_cell(...)            postToolCallHook stashes {cell_id, source_sha256}
agent (loop ≤3)    pick top open hypothesis — or propose_eda_hypotheses(source=data_signal) first
agent → skills     fetch_skill(insight_validation)   [Validate: internal recompute + external plausibility]
agent → notebooks  execute_cell(independent-slice recompute)
agent → eda        record_eda_finding(hypothesis_id, hypothesis_status, disposition, validation, evidence)
                   preToolCallHook injects plan_step_id; plugin enforces floors (FR-10)
                   → findings.jsonl + hypothesis_update link + living-report event (analyses)
                   → AG-UI eda_finding_recorded → inline card + Findings tab refresh
agent → eda        supersede_eda_finding(...) when evidence changes → needs_reevaluation flag (FR-12)
```

**Phase D — verdict and step completion**

```
agent → eda     summarize_eda_readiness(dataset, purpose, mode) → readiness record citing dispositions
agent → plans   update_plan(step completed, summary, outputs)
hooks → review  postToolCallHook auto-runs the deterministic checklist (never the sub-agent)
review→ plans   set_step_gate("analysis_review", pass|fail|unknown) → gate_events.jsonl audit
```

**Phase E — review and gates (agent ↔ sub-agent interaction)**

```
agent  → review    request_analysis_review(scope=plan_step, ...)      [explicit; or required by policy]
review → context   collect manifest: plan step + ledgers + section metas + cell summaries + MLflow
review → reviewer  delegate (SubAgentContext, read-only tools, rubric from analysis_review.md)
reviewer → review  fenced JSON findings (claims vs anchors, ledger hygiene, both validation axes)
review → plans     set_step_gate(...); AG-UI analysis_review_* events → ReviewCard + Review panel
agent  → plans     update_plan(ready_for_validation=true)
plans  → agent     allowed — or gate_blocked {blocking_gates} (FR-20)
agent  → user      if blocked: resolve findings, or ask the user
user   → agent     "accept the risk" → accept_gate_risk (guardrail approval flow, FR-22; audited)
```

**Phase F — publish and delivery**

```
agent → artifacts  publish_artifact(report assembled from typed sections; findings sections cite finding ids)
review hook        unresolved required findings at publish → "unresolved review risk" living-report event (FR-30a)
agent → user       final summary; PlanCompletion guardrail warns on steps lacking ready_for_validation (FR-23)
```

**Offline — evals (no user in the loop)**

```
harness → app      TestClient(create_app()) with isolated home; scripted or live agent runs Phases A–F
scorer  → ledgers  Tier 1 asserts records; Tier 2 matches seeded↔agent hypotheses, reads dispositions
judge   → bundle   Tier 3 scores qualitative criteria (separate model); reports per run
```

### 2.4 Agent-interaction contract and trust boundaries

```
main agent ──── delegates via dataclaw-analysis-review ────► analysis-reviewer (llm, ≤6 turns)
    ▲             context: structured manifest only (FR-26)      │
    │             never raw artifact HTML; no data-query tools   │ tools (read-only):
    │                                                            │  list_eda_hypotheses · list_eda_findings
    │ review findings (fenced JSON; parse-guarded)               │  read_eda_finding · get_plan
    └────────────────────────────────────────────────────────────┘  list_review_findings · list_artifacts
```

- The reviewer **never mutates** analysis state: it returns findings; only the main agent records
  hypotheses (`source=reviewer`) or resolves review findings (FR-29).
- All mutations flow through the main agent's tool calls, so hooks, guardrails, gates, and audit
  logs see everything; the sub-agent cannot bypass them.
- Today the delegation is sequential and blocking; §8/D13 name the async-review extension and the
  parallel-panel prerequisites. The interaction contract above is unchanged by either.

### 2.5 Ledger state machines

Hypothesis (fold of append-only `hypothesis` + `hypothesis_update` records):

```
 propose ──► open ──► testing ──► confirmed      (requires ≥1 linked internally-validated finding)
              │  ▲        ├─────► rejected       (rejecting finding kept as rejected_hypothesis)
              │  │        ├─────► unresolved_needs_domain_input   (surfaces as question to user)
              │  └────────┘      (back to open: "deferred: loop budget" — readiness caveat, not blocker)
              └─────► out_of_scope               (untestable / plan revised away)
 any state + linked evidence superseded ──► needs_reevaluation flag (checklist CHK-hypothesis-stale-evidence)
```

Finding: `active ──► superseded` (edge record with reason + optional replacement; history immutable).
Readiness verdicts persist as `readiness`-type findings — supersedable like any other.

### 2.6 Gate lifecycle (per step × gate name)

```
 (no review run) unknown ──checklist/sub-agent run──► fail ◄──new required findings── pass
        │                                              │                                ▲
        │ required gate: blocks ready_for_validation   │ resolve/accept findings ───────┘
        └──► accept_gate_risk (user-approved, audited) ─────────────────────────────────┘
 checklist-only where sub-agent required: capped at unknown — never pass (degradation rule)
```

Every transition appends to `gate_events.jsonl` with actor, previous, new, and reason (FR-18).

## 3. Key decisions

| ID | Decision | Why | Rejected alternative |
|---|---|---|---|
| D1 | Hypotheses are first-class objects, separate from findings | lifecycle precedes evidence; 1-hypothesis→N-findings; belief changes ≠ evidence changes; eval reads coverage and honesty separately | placeholder findings; hypothesis fields folded into finding records |
| D2 | Anti-theater pressure is built in: batch caps, rationale requirements, one loop reserved for emergent surprises, eval precision penalty | LLMs generate plausible boilerplate; recall-only scoring rewards spam; hypothesis-first risks tunnel vision | uncapped ledger scored on recall alone |
| D3 | Loop budget reconciled with readiness: ≤3 high-priority hypotheses per pass; routine checks don't consume loops; budget-deferred ≠ unresolved (caveat, not blocker) | otherwise 3 loops vs N open hypotheses deadlocks readiness and incentivizes priority-gaming | blocking on every open hypothesis; unlimited loops |
| D4 | Validation floors verify shape, not truth — and say so | `validated` is self-reported; requiring evidence refs + checklist consistency + reviewer coherence + eval outcomes narrows the honesty gap honestly | pretending plugin guards prove correctness |
| D5 | Gates block `ready_for_validation`, not execution; required-ness is policy-scoped; `accept_gate_risk` is the audited escape hatch | agent iteration must continue; unknown-gate deadlock (no reviewer configured) needs a human path that leaves a trail | blocking all work; silent auto-pass; unresolvable `unknown` |
| D6 | `PlanCompletion` guardrail surfaces unready steps at delivery | a flag nothing consumes is decoration; visible warning beats silent block | hard-blocking final delivery; leaving the flag unconsumed |
| D7 | Reviewer is metadata-only in this pass; golden expectations scoped to coherence | no data access = can't recompute; pretending otherwise sets the golden test up to fail; capped query tool is a scoped future decision | data-query reviewer now (injection + cost + scope creep) |
| D8 | Superseding linked evidence flags the hypothesis `needs_reevaluation` | confirmed beliefs must not outlive their evidence silently | supersede and ledger fully decoupled |
| D9 | `finding_type=rejected_hypothesis` auto-derived from `hypothesis_status=rejected` | three overlapping "rejected" vocabularies guarantee agent misuse | agent-managed consistency across three enums |
| D10 | Session-scoped stores now; dataset-scoped aggregation deferred explicitly | matches every existing store; cross-session querying is real but separable | project-level store redesign in this pass |
| D11 | Evals: disposition **sets**, Tier-2 threshold, judge advisory-first and qualitative-only | paraphrase/merging is legitimate agent behavior; all-or-nothing + judge-gating = flaky harness nobody trusts | exact-match dispositions; judge as a required gate on day one |
| D12 | Reviewer runs via direct provider use (registry), not the `delegate_to_subagent` tool | avoids per-session allowlist globals and conversation persistence; keeps sub-agent hooks and events | invoking the chat-facing delegation tool internally |
| D13 | Judgment stays sequential; parallelism lands only where it parallelizes LLM calls or unblocks the analyst — evals now, async review as the designed-for next step, reviewer panel / hypothesis workers later behind contextvar + kernel prerequisites (§8) | loop adaptivity is the product; LLM turns are the latency bottleneck, local compute is not | parallel insight loops; premature sub-agent fan-out on racy module-global context |

## 4. Plugin layouts

```
plugins/dataclaw-eda/
  pyproject.toml                  # entry point dataclaw-eda = "dataclaw_eda:EdaPlugin"
  dataclaw_eda/
    __init__.py                   # depends_on=["dataclaw-plans","dataclaw-notebooks","dataclaw-artifacts"]
    tools.py                      # 8 tools + emit helpers
    store.py                      # hypotheses.jsonl + findings.jsonl + rebuildable indexes + enum constants
    evidence.py                   # anchor resolution (stash → live notebook → stale)
    readiness.py                  # PURPOSE_REQUIRED_CHECKS + MODE_CHECK_OVERLAY + rollup
    sections.py                   # findings/hypotheses → artifact typed sections + living-report events
    router.py                     # GET /api/eda/... (read-only)
    hooks.py                      # eda_context_hook (pre), eda_evidence_hook (post)
  tests/

plugins/dataclaw-analysis-review/
  dataclaw_analysis_review/
    __init__.py                   # depends_on=["dataclaw-plans","dataclaw-eda","dataclaw-artifacts","dataclaw-projects"]
    tools.py  store.py  context.py  checklist.py  reviewer.py  gates.py  router.py  hooks.py
  tests/

plugins/dataclaw-plans/dataclaw_plans/gates.py        # new: set_step_gate, GATE_RESOLVERS, accept_gate_risk, audit
plugins/dataclaw-notebooks/dataclaw_notebooks/        # patch: cell_id in execute/insert/read results + cell_summary

skill-library/{structured_eda,insight_validation,analysis_review,dataclaw}.md   (+ OpenClaw mirrors)

ui/src/hooks/{useFindings,useReviews}.ts
ui/src/components/{FindingsPanel,ReviewPanel}.tsx
ui/src/components/tool-renderers/{EdaFindingCard,ReviewCard}.tsx   (+ ToolResultRenderer dispatch)

evals/{runner,harness,scripted}.py  evals/scoring/{schema,deterministic,hypotheses,judge,report}.py
evals/rubrics/structured_eda_judge.md
evals/cases/structured_eda_customer_events/{case,hypotheses,expected}.yaml
tests/test_evals_smoke.py  tests/test_live_eval.py
```

## 5. Tool contracts

```python
# ── dataclaw-eda ────────────────────────────────────────────────────────────
propose_eda_hypotheses(hypotheses, dataset_id=None, version_id=None, **ctx)
  # hypotheses = [{statement, rationale, source, priority="medium", covers_checks=[],
  #                selection={screened_n, selection_rule, correction}?}]
  # caps: len ≤ 7, high-priority ≤ 3; data_signal requires substantive rationale
  # -> {hypothesis_ids, count}

update_eda_hypothesis(hypothesis_id, status, disposition_reason="",
                      linked_finding_ids=None, priority=None, loop_index=None, **ctx)
  # -> {hypothesis_id, status, history_len}

list_eda_hypotheses(dataset_id=None, plan_step_id=None, status=None,
                    source=None, priority=None, **ctx)

record_eda_finding(title, finding_type, summary, evidence, dataset_id,
                   version_id=None, severity="info", caveat="", next_action="",
                   confidence="medium",
                   hypothesis_id="", hypothesis_status=None,     # atomic link + transition
                   disposition="unresolved", validation=None, covers_checks=None,
                   loop_index=None, selection=None, **ctx)
  # floors: high confidence ⇒ internal validated + evidence_refs;
  #         external unverified ⇒ mandatory caveat + confidence ≤ medium;
  #         screened validated/high-confidence findings require correction or holdout;
  #         hypothesis_status rejected ⇒ finding_type auto = rejected_hypothesis
  # -> {finding_id, status, anchors, hypothesis_id}

supersede_eda_finding(finding_id, reason, replacement_id=None, **ctx)
  # side effect: linked confirmed/rejected hypotheses gain needs_reevaluation

list_eda_findings(dataset_id=None, plan_step_id=None, status=None, severity=None,
                  finding_type=None, hypothesis_id=None, **ctx)
read_eda_finding(finding_id, **ctx)

summarize_eda_readiness(dataset_id, version_id=None, purpose="dashboard",
                        required_checks=None, mode="", **ctx)
  # -> {status, blockers: [{kind: missing_check|blocker_finding|open_hypothesis, ...}],
  #     caveats, hypotheses: {counts…, cited…, deferred…}, evidence_links,
  #     missing_checks, purpose, mode}

# ── dataclaw-plans (delta) ──────────────────────────────────────────────────
update_plan(...)          # rejects ready_for_validation=true on required fail/unknown gates
accept_gate_risk(proposal_id, plan_step_id, gate_name, rationale, **ctx)   # audited escape hatch

# ── dataclaw-analysis-review ────────────────────────────────────────────────
request_analysis_review(scope, target_id=None, plan_step_id=None,
                        severity_floor="warning", require_subagent=False, **ctx)
list_review_findings(scope=None, target_id=None, status=None, severity=None, **ctx)
resolve_review_finding(finding_id, status, rationale="", evidence_link=None, **ctx)
get_review_gate(scope, target_id, **ctx)
```

All context params (`session_id`, `proposal_id`, `plan_step_id`) are hook-injected into `tool_input`; canonical names are unprefixed; the OpenClaw manifest auto-generates and the alias fixture asserts schema identity.

## 6. Storage layouts

```
workspaces_dir()/eda/findings/<safe_session_id>/
  hypotheses.jsonl        # hypothesis + hypothesis_update records (fold = effective state)
  findings.jsonl          # finding + supersede records
  indexes/by_dataset.json  by_plan_step.json  by_hypothesis.json   # rebuildable, self-healing

workspaces_dir()/analysis-review/reviews/<rev-id>/
  run.json  findings.jsonl  context_manifest.json

plugin_data_dir("plans")/gate_events.jsonl              # append-only gate audit
```

Write order per NFR-2: finding → hypothesis link → living-report event; readers tolerate dangling refs; index rebuild heals them. Store mechanics (atomic write, per-key locks, fsync append, log fold) copied from `dataclaw_artifacts/store.py`.

## 7. Hooks & events

- `eda_context_hook` (pre): injects session/proposal/`plan_step_id` (from `state["active_plan_step_id"]`) into the 8 EDA tools' input. Same pattern for review tools.
- `eda_evidence_hook` (post): stashes last successful `execute_cell` `{cell_id, source_sha256}` per session for anchor resolution.
- Review hook (post): on `update_plan` marking a step completed → auto-run checklist, persist run, write gate. Sub-agent review never auto-triggers.
- AG-UI custom events (emitter pattern from artifacts): `eda_hypothesis_proposed`, `eda_hypothesis_updated`, `eda_finding_recorded`, `eda_finding_superseded`, `eda_summary_ready`, `analysis_review_started|updated|gate_changed`.
- Living report: findings/readiness on **analyses**; hypothesis batches on **decisions**; review runs on **log**.

## 8. Concurrency model

Verified baseline: the LangGraph loop executes a turn's tool calls **sequentially** (`for tc in pending`, `dataclaw/loop/nodes.py`); `DefaultSubAgentProvider` awaits one sub-agent to completion (no fan-out primitive); the JSONL stores use per-key locks and are already safe for concurrent writers; several hooks stash per-request context in module globals — safe under today's one-agent-per-session model, **not** safe under within-session parallel agents.

**Sequential by design (not a limitation to fix):**
- **The insight loop.** Each loop's Update step re-prioritizes the remaining hypotheses using what was just learned — a Simpson's-paradox discovery reframes its sibling hypotheses. Parallel loops would forfeit exactly the adaptivity that makes loops worth budgeting. Judgment ordering beats wall-clock here.
- **Hooks and plan mutations.** Hooks are graph nodes threading one state; plan updates funnel through the main agent (two concurrent writers to a proposal create logical conflicts, not just lock contention).

**Parallel now (in this PRD, no infra risk):**
- **Evals (P8):** cases, per-hypothesis Tier-2 scoring, and judge calls are independent — the runner uses `asyncio.gather`. The cheapest real win.
- **Routine mode checks:** batched into one computation (a single cell computing missingness/duplicates/distributions together) rather than serial one-check loops — parallelism by batching, no new machinery.

**Designed-for extension (enabled by D5, not built in this pass):**
- **Async review.** Because gates block `ready_for_validation` rather than execution, `request_analysis_review` can later run as a background task whose gate lands on completion — review latency (≤6 LLM turns) stops blocking the analyst flow. No schema change; needs only a background-task runner and a completion event.

**Deferred until wall-clock pain is real (prerequisites named):**
- **Multi-lens reviewer panel** (N parallel sub-agents with distinct rubric lenses, findings merged) and **parallel hypothesis workers** (one sub-agent per open independent hypothesis). These are the only places parallelism buys real latency, because they parallelize LLM calls. Prerequisites: migrate per-request module-global context to contextvars (the accepted racy pattern becomes an actual bug under within-session concurrency), and a kernel strategy (one kernel per notebook today; parallel compute means extra kernels and duplicated dataset memory).

## 9. Safety model

| Threat | Mitigation |
|---|---|
| Prompt injection via reviewed content | reviewer receives structured extraction (section-meta JSON, ledger records), never raw artifact HTML; no data-query tools |
| Data-poisoning text inside finding fields | capped, control-char-redacted text; reviewer treats field content as data; checklist checks are structural, not textual |
| Agent hides bad news | append-only ledgers; rejected hypotheses durable; checklist required-checks; eval hypothesis coverage |
| Self-reported validation | evidence-ref floor at tool boundary; CHK-unvalidated-confirmed; reviewer coherence audit; eval outcomes (NFR-6 chain) |
| False confidence in degraded review | reviewer_type on every run/gate/card; checklist-only never passes sub-agent-required gates; acceptance is audited |
| Cost blowups | deterministic checklist auto; sub-agent bounded + explicit; judge single-call; live evals opt-in + budgeted |

## 10. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Hypothesis ledger becomes boilerplate theater | batch caps, rationale requirements, eval precision penalty, judge specificity criterion (D2) |
| Loop budget vs open hypotheses deadlock | D3 reconciliation: caps, free routine checks, deferred ≠ unresolved |
| Findings become a second transcript | compact cards, NFR-5, checklist doesn't flag info-severity noise |
| Cross-store dangling links after crash | fixed write order + tolerant readers + healing rebuilds (NFR-2) |
| Reviewer misses numerical errors | scoped expectations (D7); future capped query tool is an explicit open question |
| Golden-case overfitting | second case in a different mode before skill tuning (Open Questions) |
| Live eval flakiness erodes trust | disposition sets + thresholds + advisory judge (D11); smoke test keeps harness honest in CI |
| Gate friction annoys iteration | gates only on `ready_for_validation`, policy-scoped required-ness, audited escape hatch (D5) |

## 11. Open questions (decide before or during build)

1. **Tool surface in non-data sessions** — 12 new tool definitions load into every session. Should the tool-availability provider scope EDA/review tools to sessions with datasets attached? (Recommended: yes, follow-up patch; not blocking P1.)
2. **Reviewer data access** — revisit a capped read-only query/preview tool for the reviewer after P6 ships and golden results show what coherence-only review misses. (Deliberately out of scope now, D7.)
3. **Dataset-scoped findings aggregation** — "what do we know about dataset X across sessions" needs a project-level index or query layer. Deferred (D10); trigger = first real multi-session project use.
4. **Second eval case** — which mode next: time-series (gaps/seasonality/leakage-by-time) or dashboard/KPI (grain/denominator)? Needed before heavy skill tuning against the churn case.
5. **MVP cut if capacity forces it** — recommended order preserved: P0–P4 plus the P5 review-lifecycle core ship the governed methodology; P5 checklist expansion, P6 sub-agent review, P7 UI, and P8 eval scoring follow. The phases are cut-compatible by design.
6. **`record_eda_finding` parameter count** — ~15 params; if malformed-call rates show up in practice, collapse `hypothesis_id`/`hypothesis_status` into a nested object and/or split a `validate_eda_finding` tool. Measure first.
7. **When to build async review** — the background-task runner for non-blocking review (§8) is a small, contained addition; trigger = review latency measurably interrupting analyst flow once P6 is in real use. Reviewer panel and hypothesis workers stay behind the contextvar + kernel prerequisites regardless.
8. **Gate required-ness detection** — FR-21's keyword-based step-kind policy (modeling/export/external-share from step text) is brittle in the same way the UI's regex workstream bucketing is. A cleaner path is an explicit step `kind` field in the plan schema, set at proposal time. Decide before P0 hardens the policy list.

## 12. Verification

1. Per-phase: `uv run pytest plugins/dataclaw-eda plugins/dataclaw-analysis-review plugins/dataclaw-plans tests/`; `npm run build` in `ui/`.
2. Golden acceptance (header of this doc) via the scripted-agent loop test — no live model required.
3. `pytest tests/test_evals_smoke.py` in default CI (scripted agent + fake judge; scorer-sensitivity asserted).
4. Live: `DATACLAW_LIVE_EVAL=1 uv run pytest tests/test_live_eval.py` or `python -m evals.runner --case structured_eda_customer_events` — Tiers 1–2 at thresholds, judge report generated.
5. Manual: run the fixture prompt; watch hypothesis/finding cards stream; Findings tab groups by hypothesis with readiness pinned; step blocked by gate until review resolved or risk accepted; `/app` publish unaffected.
