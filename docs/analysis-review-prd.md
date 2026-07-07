# DataClaw Analysis Review - PRD & Solution Architecture

| | |
|---|---|
| **Status** | Draft, build-ready |
| **Owner** | Nandini Mathan |
| **Last updated** | 2026-07-07 |
| **Ships as** | `plugins/dataclaw-analysis-review/` |
| **Composes with** | `plugins/dataclaw-plans`, `plugins/dataclaw-artifacts`, `plugins/dataclaw-query-lab`, `plugins/dataclaw-modeling`, sub-agent registry |

---

## Release-note-first framing

DataClaw can now review its own analysis before asking the human to trust it. After an EDA, query, model, or report step, a scoped reviewer sub-agent checks claims against evidence, flags missing caveats, questions fragile denominators, verifies artifact links, and produces a review card with required fixes and optional improvements. The human gets a smaller validation surface: the claims, the evidence, and the unresolved risks.

## Validation gate & degradation rule

- **Golden acceptance check:** run a fixture notebook/report with one unsupported claim, one denominator error, one missing model reproducibility field, and one valid chart. The reviewer must flag the first three, leave the valid chart alone, and block "ready for human validation" until required findings are resolved or explicitly accepted.
- **Degradation rule:** if a sub-agent provider is unavailable, the plugin falls back to deterministic checklist review over available manifests/cards and labels the review "checklist-only"; it may not mark high-risk analysis as fully reviewed, satisfy external-share gates, or clear human-validation gates that require sub-agent review.

## Convergence checklist

| Surface | How this PRD uses it |
|---|---|
| Plugin | `plugins/dataclaw-analysis-review/` auto-discovered at startup |
| Tools | `request_analysis_review`, `list_review_findings`, `resolve_review_finding`, `get_review_gate` |
| Hooks | postToolCall triggers for artifacts/modeling/plan completion; pre-tool context injection |
| Skills | new `skill-library/analysis_review.md` defines reviewer rubric |
| UI | review AG-UI events, inline review card, read-only Review panel |
| Sub-agents | registers/uses reviewer sub-agent through existing sub-agent registry |
| OpenClaw | Bridge manifest/allowlist exposes review tools as canonical names or `dataclaw_...` aliases with identical schemas; reviewer provider remains optional |
| Validation | golden seeded review fixture with required findings, fallback mode, and OpenClaw alias/manifest check |

---

# Part 1 - Product Requirements

## 1. Problem

Execution is increasingly Codex-driven, but human validation bandwidth is the binding constraint. DataClaw can produce plans, notebooks, query results, models, and artifacts, yet the human still has to read everything to find unsupported claims, denominator mistakes, missing caveats, non-comparable model runs, or broken evidence links. The README already calls out the need for a sub-agent that reviews v1 analysis; this PRD turns that into a modular review component.

## 2. Goals

- **G1** - Provide a review sub-agent that audits analysis outputs against evidence.
- **G2** - Create durable review cards with findings, severity, evidence links, and resolution state.
- **G3** - Integrate with plan steps: review can be required before a step is marked `ready_for_validation`.
- **G4** - Support deterministic checklist fallback when no sub-agent is available.
- **G5** - Keep review scoped and cheap: inspect artifacts, living-report manifest, query cards, model cards, and notebook summaries, not the entire workspace by default.
- **G6** - Make unresolved risk visible in artifacts and final chat summaries.

## 3. Non-goals

- No claim that review proves correctness.
- No automatic modification of analysis outputs without an explicit agent/tool action.
- No replacement for human approval.
- No broad framework for arbitrary eval agents.
- No hidden second agent loop outside the existing sub-agent registry.

## 4. Users & Use Cases

| # | Use case | What must be true |
|---|---|---|
| U1 | "Review this analysis before I send it" | Reviewer returns required fixes, optional suggestions, and evidence links |
| U2 | "Is every claim supported?" | Claims without query/artifact/notebook evidence are flagged |
| U3 | "Can I trust the model comparison?" | Missing baseline, mismatched eval digest, or absent repro fields are flagged |
| U4 | "Did the chart exaggerate the result?" | Visualization checklist catches misleading axes or missing caveats |
| U5 | "Mark this risk accepted" | Human/agent can accept a finding with rationale; it remains visible |
| U6 | "What changed after fixes?" | Review rerun shows resolved/new/still-open findings |
| U7 | "Auto mode is running" | Required review gates prevent silent completion of high-risk plan steps |
| U8 | "No sub-agent configured" | Checklist-only fallback runs and labels its limits |
| U9 | Reviewer prompt injection from artifact text | Reviewer receives extracted evidence and manifests, not executable artifact content |

## 5. Functional Requirements

### 5.1 Review requests

- **FR-1** `request_analysis_review(scope, target_id?, plan_step_id?, severity_floor="warning")` creates a review run.
- **FR-2** Valid scopes: `plan_step`, `artifact`, `living_report`, `query_card`, `modeling_spec`, `session`.
- **FR-3** Review context is assembled from structured sources: plan step, artifact metadata, living-report manifest, query cards, model comparisons, notebook summaries, and capped source excerpts.
- **FR-4** Review runs are stored with reviewer type: `subagent`, `checklist`, or `mixed`.

### 5.2 Findings

- **FR-5** Findings include `{finding_id, severity, category, claim, evidence, recommendation, status}`.
- **FR-6** Categories: unsupported claim, data quality caveat, denominator/grain issue, query risk, modeling comparability, reproducibility gap, misleading visualization, broken link, security/export risk.
- **FR-7** Status values: open, resolved, accepted_with_rationale, dismissed_as_not_applicable.
- **FR-8** `resolve_review_finding(finding_id, status, rationale?, evidence_link?)` updates status append-only.
- **FR-9** Review reruns preserve old findings and supersede them when resolved or changed.

### 5.3 Gates

- **FR-10** `get_review_gate(scope, target_id)` returns pass/fail/unknown plus blocking findings.
- **FR-11** Plan steps may be marked `ready_for_validation` only when no open required findings remain.
- **FR-12** High-risk scopes (modeling, external-share artifact, executive dashboard) require sub-agent review unless explicitly degraded to checklist-only by the user; checklist-only degradation must keep the review gate `unknown` or `fail`, never `pass`, for scopes that require a sub-agent.
- **FR-13** Final artifact export shows unresolved required findings unless the user explicitly accepts them.

### 5.4 Surfaces

- **FR-14** Emit `analysis_review_started`, `analysis_review_updated`, and `analysis_review_gate_changed` AG-UI events.
- **FR-15** Inline review card renders findings grouped by severity/category.
- **FR-16** Right panel Review tab lists review runs and finding status read-only.
- **FR-17** `list_review_findings(scope?, status?, severity?)` supports follow-up work.
- **FR-18** Living report Log captures review runs and finding resolutions.

## 6. Non-functional Requirements

- **NFR-1 Safety** - reviewer context is structured/capped; artifact HTML is not executed.
- **NFR-2 Cost control** - review context is scoped; session-wide review requires explicit call.
- **NFR-3 Durability** - review runs and finding state are append-only.
- **NFR-4 Explainability** - every finding needs evidence or a statement that evidence is missing.
- **NFR-5 Degradation** - checklist-only mode is visible and cannot masquerade as full review.

## 7. Phasing & Exit Criteria

| Phase | Scope | Exit test |
|---|---|---|
| P1 - Checklist review | store, tools, deterministic checks over artifacts/query/model cards | Golden fixture flags seeded issues checklist-only; generated OpenClaw manifest/allowlist exposes review tools with identical canonical/alias schemas |
| P2 - Sub-agent reviewer | register reviewer sub-agent definition, scoped context builder, review events | Sub-agent finds unsupported claim and denominator issue |
| P3 - Plan/artifact gates | ready_for_validation gate, artifact unresolved-risk banner, living report log | High-risk step blocked until finding resolved/accepted |
| P4 - Review ergonomics | right panel filters, rerun diff, review templates by artifact type | Rerun shows resolved vs new findings |

## 8. Success Metrics

- Every external-share artifact has a review run or explicit checklist-only degradation.
- Required findings reduce unsupported final claims in golden notebooks to zero.
- Human validation time falls because review card surfaces blocking issues first.
- Auto mode cannot silently complete a high-risk plan step with open required findings.

---

# Part 2 - Solution Architecture

## 1. System Context

Analysis Review is the only PRD in this set that primarily uses the sub-agent registry. It still lands as a plugin with tools/hooks/events; the sub-agent is an implementation detail behind a review tool.

| Piece | Role |
|---|---|
| `dataclaw.providers.sub_agent.registry` | reviewer sub-agent definition |
| `plugins/dataclaw-plans` | plan step status and gates |
| `plugins/dataclaw-artifacts` | artifact metadata, living report, export risk |
| `plugins/dataclaw-query-lab` | query cards and warnings |
| `plugins/dataclaw-modeling` | comparison cards and model repro state |
| `skill-library/analysis_review.md` | reviewer rubric and checklist |

## 2. Flow

```
TRIGGER    plan step complete, artifact publish, or explicit review request
CONTEXT    collect structured evidence for scope
CHECKLIST  run deterministic gates first
SUBAGENT   delegate scoped review when configured/required
STORE      append review run + findings
SURFACE    inline review card + right panel + living report log
GATE       plan/artifact ready state updates from open required findings
```

## 3. Key Decisions

| ID | Decision | Why | Rejected alternative |
|---|---|---|---|
| D1 | Review is a plugin tool, not a hidden background judge | Agent/human can request, inspect, rerun, and resolve it | Invisible evaluator |
| D2 | Deterministic checklist runs before sub-agent | Cheap issues should not consume LLM attention | LLM-only review |
| D3 | Findings are append-only with resolution state | Audit trail matters | Deleting or overwriting resolved findings |
| D4 | Review gates block ready state, not execution | The agent can still fix issues; human sees unresolved risk | Stopping all work on first warning |
| D5 | Context is structured evidence, not raw workspace dump | Safer, cheaper, more reviewable | Give reviewer every file |

## 4. Plugin Layout

```
plugins/dataclaw-analysis-review/
  dataclaw_analysis_review/
    __init__.py       # tools, router, hooks, sub-agent registration
    tools.py          # request/list/resolve/gate tools
    store.py          # review runs/findings append-only
    context.py        # structured evidence collectors
    checklist.py      # deterministic checks
    reviewer.py       # sub-agent delegation
    gates.py          # plan/artifact gate state
    router.py         # review endpoints
    hooks.py          # postToolCall/plan-step/artifact publish triggers
  tests/
skill-library/analysis_review.md
ui/src/components/
  ReviewPanel.tsx
  tool-renderers/ReviewCard.tsx
```

## 5. Tool Contract

```python
request_analysis_review(scope, target_id=None, plan_step_id=None,
                        severity_floor="warning", require_subagent=False)
# -> {review_id, status, reviewer_type, findings_summary, gate}

list_review_findings(scope=None, target_id=None, status=None, severity=None)
# -> [{finding_id, severity, category, status, summary, evidence_links}]

resolve_review_finding(finding_id, status, rationale="", evidence_link=None)
# -> {finding_id, status, updated_at}

get_review_gate(scope, target_id)
# -> {gate: "pass"|"fail"|"unknown", blocking_findings, reviewer_type}
```

## 6. Storage Layout

```
workspaces_dir()/analysis-review/
  reviews/
    rev-plan-s2-001/
      run.json
      findings.jsonl
      context_manifest.json
```

Contexts store references and capped excerpts, not copied raw datasets or executable artifact HTML.

## 7. Safety Model

| Threat | Scenario | Mitigation |
|---|---|---|
| Prompt injection in reviewed content | Artifact/report text asks reviewer to ignore failures | reviewer context is structured extraction, not executable content |
| False confidence | Checklist-only mode is mistaken for full review | reviewer type displayed in gate and final card |
| Review overreach | Reviewer silently changes analysis | review tools only create findings; fixes require explicit agent/tool action |
| Context bloat | Session-wide review burns tokens and misses details | scoped review by default; explicit session review only |
| Finding loss | Rerun deletes prior criticism | append-only findings with supersede/resolution state |

## 8. Hooks & UI

- `postToolCallHook`: if `publish_artifact`, `compare_model_runs`, or plan step completion occurs, offer/trigger review based on policy.
- `preToolCallHook`: inject active plan/session into review requests.
- AG-UI events update inline cards and ReviewPanel.
- Right panel reads review state; fixing findings happens through chat/tool calls.
- `dataclaw-plans` dependency: plans must support a `ready_for_validation` state or gate metadata keyed by `plan_step_id`, and must refuse that transition when `get_review_gate(plan_step, plan_step_id)` returns `fail` or required-review `unknown`.

## 9. Deterministic Checklist Seeds

P1 checklist covers:

- artifact has unresolved validation errors
- final claims without evidence anchors
- query cards with warning severity >= requested floor
- model comparison missing baseline or eval digest
- model card missing repro fields
- charts missing caption/title/axis labels when metadata is available
- export/share requested with open required findings

## 10. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Reviewer becomes noisy | severity floor, required vs optional findings, golden precision tests |
| Reviewer misses subtle issue | checklist plus sub-agent, not a correctness guarantee |
| Review blocks useful iteration | gates block ready/export state, not analysis execution |
| Prompt injection from artifact content | structured extraction; never execute reviewed content |
| Cost blowups | scoped context and explicit session-wide review |
