# DataClaw EDA Findings - PRD & Solution Architecture

| | |
|---|---|
| **Status** | Draft, build-ready |
| **Owner** | Nandini Mathan |
| **Last updated** | 2026-07-07 |
| **Ships as** | `plugins/dataclaw-eda/` |
| **Composes with** | `plugins/dataclaw-intake`, `plugins/dataclaw-notebooks`, `plugins/dataclaw-query-lab`, `plugins/dataclaw-artifacts`, `skill-library/structured_eda.md` |

---

## Release-note-first framing

DataClaw can now explore data with a durable finding trail. Instead of leaving EDA as a pile of notebook outputs, the agent records each meaningful observation as a finding card with evidence, severity, caveat, affected columns/segments, and recommended next action. The human can validate the exploration by reviewing findings, not replaying every cell.

## Validation gate & degradation rule

- **Golden acceptance check:** run structured EDA on the customer events sample and record at least one distribution finding, one missingness/quality finding, one segment comparison, and one "not a finding" rejected hypothesis; verify all are tied to dataset version, `plan_step_id`, notebook cell id/source hash, and artifact/living-report anchors.
- **Degradation rule:** if finding-card persistence fails, EDA may continue in the notebook and persist notebook/source summaries where possible, but the plan step cannot be marked "EDA summarized" and artifacts/review must label the EDA section as notebook-only/unstructured until finding cards are recorded.

## Convergence checklist

| Surface | How this PRD uses it |
|---|---|
| Plugin | `plugins/dataclaw-eda/` auto-discovered at startup |
| Tools | `record_eda_finding`, `list_eda_findings`, `read_eda_finding`, `supersede_eda_finding`, `summarize_eda_readiness` |
| Hooks | postToolCallHook captures notebook outputs and plan-step context |
| Skills | `structured_eda` decides loops, modes, and finding thresholds |
| UI | `eda_finding_recorded`, `eda_finding_superseded`, `eda_summary_ready` AG-UI events and read-only Findings panel |
| Sub-agents | Not applicable |
| OpenClaw | Bridge manifest/allowlist exposes EDA tools as canonical names or `dataclaw_...` aliases with identical schemas |
| Validation | golden structured EDA fixture with distribution, quality, segment, rejected-hypothesis cards, and OpenClaw alias/manifest check |

---

# Part 1 - Product Requirements

## 1. Problem

Structured EDA exists as a skill, and notebooks can compute rich exploration. But EDA findings are not first-class product objects. Important observations, caveats, rejected hypotheses, and next-step implications live in notebook markdown or chat text. That makes it hard to answer "what did we learn?", "which findings were validated?", "what changed after re-running?", and "which evidence supports this dashboard/modeling decision?"

## 2. Goals

- **G1** - Capture EDA observations as durable finding cards with evidence and caveats.
- **G2** - Tie every finding to dataset version, `plan_step_id`, notebook cell id/source hash, and optional query/artifact anchors.
- **G3** - Preserve rejected hypotheses and superseded findings instead of overwriting them.
- **G4** - Feed artifacts/living reports with structured findings grouped by `plan_step_id`, data domain, and severity.
- **G5** - Keep compute in notebooks; EDA plugin records and indexes evidence.
- **G6** - Make readiness decisions explicit: ready for query, dashboard, modeling, or needs data repair.

## 3. Non-goals

- No automated exhaustive EDA engine.
- No statistical claim engine that proves causality.
- No replacement for `structured_eda` skill judgment.
- No chart rendering surface; Artifacts owns final visuals.
- No raw dataset storage beyond evidence metadata and capped summaries.

## 4. Users & Use Cases

| # | Use case | What must be true |
|---|---|---|
| U1 | "Explore this dataset" | Agent records findings as cards while notebook cells run |
| U2 | "What did we learn?" | Findings panel lists active findings by severity/topic |
| U3 | "Did you check missingness?" | Missingness finding or rejected hypothesis is searchable |
| U4 | "This finding changed after filtering" | Old finding is superseded with reason; history remains |
| U5 | "Can we build a model yet?" | Readiness summary lists blockers and evidence |
| U6 | "Put the EDA summary in the report" | Artifact/living report consumes finding cards |
| U7 | "Which cell produced that chart?" | Finding links to notebook cell id and source hash |
| U8 | "Do not overstate this pattern" | Finding carries caveat and confidence level |
| U9 | Poisoned data asks the agent to hide a quality issue | Findings are append-only; review can flag missing required checks |

## 5. Functional Requirements

### 5.1 Finding cards

- **FR-1** `record_eda_finding(title, finding_type, summary, evidence, dataset_id, version_id?, severity="info", caveat="", next_action="", confidence="medium")` creates a finding card.
- **FR-2** Finding types: distribution, missingness, outlier, segment_difference, correlation_candidate, leakage_risk, readiness, rejected_hypothesis, data_quality, caveat.
- **FR-3** Evidence can reference notebook cell id/source hash, query card id, artifact section id, profile id, or capped inline summary JSON.
- **FR-4** Every finding stores session id, plan id, `plan_step_id`, dataset id/version id, timestamp, and author agent.
- **FR-5** `supersede_eda_finding(finding_id, reason, replacement_id?)` appends a supersede edge and never deletes the old card.

### 5.2 Readiness summaries

- **FR-6** `summarize_eda_readiness(dataset_id, version_id?, purpose)` returns readiness for query/dashboard/modeling with blockers and evidence links.
- **FR-7** Readiness statuses: ready, ready_with_caveats, blocked, unknown.
- **FR-8** Required checks are purpose-specific and configured by the `structured_eda` skill mode.
- **FR-9** Rejected hypotheses are included in summaries when they answer likely user questions.

### 5.3 Surfaces

- **FR-10** Emit `eda_finding_recorded`, `eda_finding_superseded`, and `eda_summary_ready` AG-UI events.
- **FR-11** Inline finding card renders when recorded, compact by default.
- **FR-12** Right panel Findings tab groups findings by `plan_step_id`, dataset, type, status, and severity.
- **FR-13** Artifacts/living report can pull findings as typed sections.
- **FR-14** `list_eda_findings(dataset_id?, plan_step_id?, status?, severity?, finding_type?)` and `read_eda_finding(finding_id)` support review and report assembly.

### 5.4 Capture hooks

- **FR-15** `postToolCallHook` watches notebook cell execution/display output and suggests/auto-records findings only when the agent calls the explicit tool or the skill contract requires it.
- **FR-16** Cell references use nbformat cell id plus source hash, not cell index alone.
- **FR-17** Re-executed cells with changed source can supersede prior findings when the agent records a replacement.

## 6. Non-functional Requirements

- **NFR-1 Durability** - append-only finding log with atomic writes.
- **NFR-2 Reproducibility** - every finding has evidence references or is marked "interpretive note".
- **NFR-3 Performance** - listing/filtering handles hundreds of findings per session.
- **NFR-4 Privacy** - capped summaries only; no raw row dumps; any inline row/table evidence follows the shared 20-row/50-KB preview cap.
- **NFR-5 Usability** - findings should reduce review time, not become a second transcript.

## 7. Phasing & Exit Criteria

| Phase | Scope | Exit test |
|---|---|---|
| P1 - Finding cards | store, record/list/read/supersede tools, inline renderer | Golden EDA records required finding types; generated OpenClaw manifest/allowlist exposes EDA tools with identical canonical/alias schemas |
| P2 - Notebook evidence | cell id/source hash capture, plan step context, findings panel | Finding links to producing notebook cell |
| P3 - Readiness summaries | purpose-specific readiness tool, artifact/living report sections | Dashboard/modeling readiness summary appears in report |
| P4 - Review integration | required-check policies, Analysis Review hooks | Missing required EDA check is flagged by reviewer |

## 8. Success Metrics

- Every completed EDA plan step has at least one finding card or an explicit "no material findings" note.
- Final artifacts cite EDA findings instead of copying notebook prose.
- Re-running exploration preserves superseded findings and reasons.
- Human can review EDA from findings panel plus notebook links without reading the whole transcript.

---

# Part 2 - Solution Architecture

## 1. System Context

EDA Findings is the structured evidence layer for exploration. It does not compute stats itself except lightweight summaries supplied by tools; notebooks and Query Lab produce evidence, EDA plugin records the finding trail.

| Piece | Role |
|---|---|
| `plugins/dataclaw-notebooks` | compute cells, figures, tables |
| `plugins/dataclaw-intake` | dataset version and profile ids |
| `plugins/dataclaw-query-lab` | query evidence cards |
| `plugins/dataclaw-artifacts` | report/living-report sections |
| `skill-library/structured_eda.md` | exploration modes and finding thresholds |

## 2. Flow

```
PROFILE    intake/profile gives dataset version and initial warnings
EXPLORE    notebook cells compute distributions, segments, checks
RECORD     record_eda_finding stores evidence/caveat/action
INDEX      findings grouped by dataset, plan_step_id, type, severity
SUMMARIZE  summarize_eda_readiness produces purpose-specific verdict
REPORT     artifacts/living report render finding sections and anchors
```

## 3. Key Decisions

| ID | Decision | Why | Rejected alternative |
|---|---|---|---|
| D1 | Findings are explicit tool calls | The agent decides what matters; plugin persists it | Auto-record every chart/table |
| D2 | Rejected hypotheses are findings | They answer "did you check X?" | Only store positive discoveries |
| D3 | Cell id + source hash for notebook evidence | Cell indexes move and outputs overwrite | Cell index references |
| D4 | Readiness is purpose-specific | Query/dashboard/modeling need different checks | One global ready/not-ready flag |
| D5 | Artifacts consume findings, not vice versa | Exploration evidence should outlive any one report | Report-only EDA sections |

## 4. Plugin Layout

```
plugins/dataclaw-eda/
  dataclaw_eda/
    __init__.py       # tools, router, hooks
    tools.py          # record/list/read/supersede/summarize
    store.py          # append-only finding log and indexes
    evidence.py       # notebook/query/profile/artifact references
    readiness.py      # purpose-specific readiness policies
    sections.py       # artifact/living-report section adapter
    router.py         # finding endpoints
    hooks.py          # plan/notebook context capture
  tests/
ui/src/components/
  FindingsPanel.tsx
  tool-renderers/EdaFindingCard.tsx
```

## 5. Tool Contract

```python
record_eda_finding(title, finding_type, summary, evidence, dataset_id,
                   version_id=None, severity="info", caveat="",
                   next_action="", confidence="medium")
# -> {finding_id, status, anchors}

supersede_eda_finding(finding_id, reason, replacement_id=None)
# -> {finding_id, status: "superseded"}

list_eda_findings(dataset_id=None, plan_step_id=None, status=None,
                  severity=None, finding_type=None)
# -> [{finding_id, title, type, severity, status, anchors}]

read_eda_finding(finding_id)
# -> {finding_id, title, summary, evidence, caveat, status, anchors}

summarize_eda_readiness(dataset_id, version_id=None, purpose="dashboard")
# -> {status, blockers, caveats, evidence_links}
```

## 6. Storage Layout

```
workspaces_dir()/eda/
  findings/
    session-abc/
      findings.jsonl
      indexes/
        by_dataset.json
        by_plan_step.json
```

Findings are append-only. Indexes are rebuildable from `findings.jsonl`.

## 7. Events & UI

- `eda_finding_recorded`
- `eda_finding_superseded`
- `eda_summary_ready`

Inline cards show the finding and evidence link. Right panel reads findings and filters. Fixes, supersedes, and readiness summaries happen through chat/tool calls.

## 8. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Finding spam | explicit tool call and skill thresholds |
| Findings too subjective | confidence/caveat/evidence fields required |
| Broken notebook references | cell id + source hash; missing cell state rendered as stale evidence |
| Overlap with living report | EDA owns finding objects; living report renders them |
| Agent hides bad news | append-only log plus Analysis Review required-check hooks |
