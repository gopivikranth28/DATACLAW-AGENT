# DataClaw Analyst Workflow PRD Portfolio

| | |
|---|---|
| **Status** | Working portfolio, build-ready PRDs in progress |
| **Owner** | Nandini Mathan |
| **Last updated** | 2026-07-07 |
| **Purpose** | Turn DataClaw into the local open-source data scientist: raw file to defensible, shareable insight |

---

## Release-note-first framing

DataClaw is being split into a portfolio of small, buildable product components that compose into one analyst workflow: bring in raw data, profile it, explore it, answer questions with defensible queries, model when useful, visualize the evidence, publish the result, and review the work before the human spends scarce validation time. Every component lands through DataClaw's existing extension grammar: plugin, tools, hooks, skills, AG-UI events, and sub-agents where appropriate.

## Portfolio principle

Each PRD defines one modular component. If a component cannot be built through existing extension surfaces, redesign it until it can. Only write a missing-extension-point PRD after at least two concrete PRDs need that primitive.

## Convergence Checklist

Every component PRD must answer "yes" or explicitly justify "not applicable" for each item:

| Check | Requirement |
|---|---|
| Plugin | Ships under `plugins/dataclaw-*` and auto-discovers with the existing plugin loader |
| Tools | Registers canonical unprefixed PythonTool names in the shared registry; OpenClaw may expose `dataclaw_...` aliases, but aliases must keep identical schemas and route to the same implementation |
| Hooks | Uses existing hook stages (`preToolCallHook`, `postToolCallHook`, etc.) for automatic capture or context injection |
| Skills | Adds or updates Markdown skills in `skill-library/`; skills decide and plugins do |
| UI | Uses AG-UI events, tool result renderers, and the read-right/act-left rule |
| Sub-agents | Uses the sub-agent registry only when delegation is the product primitive |
| OpenClaw | Names a bridge acceptance check: generated manifests/allowlists expose intended canonical tools or `dataclaw_...` aliases with identical schemas |
| Validation | Names a golden acceptance check and a degradation rule that persists canonical evidence, labels degraded capability, and does not satisfy plan/artifact gates |

## PRD Set

| Workflow stage | PRD | Ships as | Primary extension surfaces | Status |
|---|---|---|---|---|
| Publish/report | [DataClaw Artifacts PRD](artifacts-prd.md) | `plugins/dataclaw-artifacts/` | tools, router, hooks, AG-UI events, skill triad | Approved for build |
| Plan spine contracts | [Plans Contract Note](plans-contract-prd.md) | `plugins/dataclaw-plans/` patch | plan ids, `plan_step_id`, review gates, active context hook | Build prerequisite |
| Raw file -> dataset/profile | [Data Intake & Profiling PRD](data-intake-prd.md) | `plugins/dataclaw-intake/` | tools, router, hooks, `data_profiling`/`structured_eda` skills | Drafted |
| Explore/findings | [EDA Findings PRD](eda-findings-prd.md) | `plugins/dataclaw-eda/` | tools, hooks, finding cards, `structured_eda` skill | Drafted |
| Query/answer | [Query Lab PRD](query-lab-prd.md) | `plugins/dataclaw-query-lab/` | tools, hooks, query cards, `sql_analyst` skill | Drafted |
| Model/evaluate | [Modeling & Evaluation PRD](modeling-evaluation-prd.md) | `plugins/dataclaw-modeling/` | tools, MLflow hooks, modeling skill, artifact cards | Drafted |
| Validation/review | [Analysis Review PRD](analysis-review-prd.md) | `plugins/dataclaw-analysis-review/` | sub-agent registry, hooks, tools, review events | Drafted |

## Workflow Composition

```
RAW FILE / REGISTERED DATASET
  -> Data Intake & Profiling
       registers dataset version, profile pack, quality flags
  -> EDA Findings
       records durable observations, rejected hypotheses, readiness flags
  -> Query Lab
       produces saved question/query/result cards with provenance
  -> Modeling & Evaluation
       creates baseline, trained runs, comparison matrix, reproducibility block
  -> Artifacts
       publishes report/dashboard/living report with safe embed/export
  -> Analysis Review
       reviews claims, evidence links, caveats, and missing validation
  -> HUMAN VALIDATION
       approves, requests changes, or shares/export final artifact
```

The components are deliberately not a pipeline framework. They are independent plugins that share durable ids, `plan_step_id` fields, dataset version ids, artifact ids, and living-report anchors.

## Shared Contracts

- **Tool namespace:** PRDs specify canonical unprefixed PythonTool names. OpenClaw may expose plugin-prefixed aliases such as `dataclaw_publish_artifact`, but the bridge must preserve the same schema and implementation route.
- **Plan-step identity:** Persisted objects, hooks, events, and tool parameters use `plan_step_id`. Step names are display labels only; `step_id` is allowed only as a local UI shorthand and must not be persisted.
- **Degradation:** When an integration is unavailable, persist the canonical evidence/source that can still be produced, label the result degraded, and do not let it satisfy plan completion, artifact evidence, review, export, or human-validation gates that require the missing capability.
- **Preview/sample cap:** Cards, profiles, query previews, and artifact sections may show capped samples only: `DATACLAW_PREVIEW_MAX_ROWS = 20` and `DATACLAW_PREVIEW_MAX_BYTES = 50 KiB` per rendered card/section, with binary/control-character redaction. Final artifacts should use aggregate summaries unless the user explicitly asks for a table preview.

## Build Order & Blocking Dependencies

| Order | Work | Unblocks | Exit signal |
|---|---|---|---|
| 0 | Artifacts P0 security hardening: bind `127.0.0.1`, fix `files.py` root checks/HTML+SVG serving, sandbox FilePreview HTML/SVG | Safe preview path for every later artifact/report PR | Hostile HTML/SVG fixtures cannot call the API or execute at app origin |
| 1 | Plans contract patch: stable `plan_step_id`, id-first `update_plan`, active plan context injection, `ready_for_validation` gate metadata | Artifacts P3, Query Lab, Modeling, Analysis Review | Renaming a step does not fork attribution; required-review gates block ready state |
| 2 | Shared OpenClaw alias fixture and preview-cap constants | Every new plugin PR | Canonical tool and `dataclaw_...` alias schemas compare equal; preview caps are enforced by one constant |
| 3 | Artifacts P1 spine | Profile/model/query cards can publish safe artifacts | Publish v1, revise v2, library shows latest, alias fixture passes |
| 4 | Intake, EDA, Query Lab, Modeling in evidence-object order | Rich report inputs and reviewable claims | Each component persists canonical evidence and links to `plan_step_id` |
| 5 | Artifacts P2/P3 living report and Analysis Review gates | End-to-end investigation narrative and validation loop | Living report accumulates evidence; high-risk exports require review or explicit degraded state |

## Shared Acceptance Fixtures

- `assert_openclaw_tool_aliases(plugin, canonical_tools)`: generated OpenClaw manifest/allowlist exposes either canonical names or `dataclaw_...` aliases, with JSON schemas identical to the PythonTool registry.
- `assert_preview_cap(rendered_payload)`: rendered cards/sections obey `DATACLAW_PREVIEW_MAX_ROWS` and `DATACLAW_PREVIEW_MAX_BYTES`, with binary/control-character redaction.
- `assert_plan_step_identity(object)`: persisted evidence uses `plan_step_id`; step names appear only as display labels.

## House Style for PRDs

Each PRD should include:

- Release-note-first framing.
- Goals and explicit non-goals.
- Use cases in "what must be true" rows.
- Numbered functional requirements.
- Non-functional requirements, including security/durability/performance where relevant.
- Phasing table with exit tests.
- Explicit decisions with rationale and rejected alternatives.
- Solution architecture with flow, plugin layout, tool contracts, storage layout, hooks/events, UI surfaces, and risks.
- Validation gate and degradation rule.
- Success metrics.

## Shared Invariants

- Data movement is local-first and session/project scoped.
- The notebook is the compute/reproducibility layer.
- The plan is the investigation spine.
- Artifacts are the final visual/reporting surface.
- Skills express judgment and workflow policy; plugins execute and persist.
- The right panel reads; the chat/tool loop acts.
- Every shipped result needs an evidence trail: dataset version, query/run/cell provenance, `plan_step_id`, and artifact or living-report anchor.
