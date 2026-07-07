# DataClaw Plans Contract Note - `plan_step_id` & Validation Gates

| | |
|---|---|
| **Status** | Build prerequisite for Artifacts P3, Query Lab, Modeling, and Analysis Review |
| **Owner** | Nandini Mathan |
| **Last updated** | 2026-07-07 |
| **Ships as** | Patch to `plugins/dataclaw-plans/` and the OpenClaw bridge manifest |

---

## Release-note-first framing

DataClaw plans now provide stable step identity and validation gates. Evidence
objects can attribute themselves to a plan step even when the user renames the
step, and high-risk work can be blocked from "ready for validation" until review
gates pass.

## Validation gate & degradation rule

- **Golden acceptance check:** propose a plan, update a step by `plan_step_id`,
  rename that step, update it again, and verify all evidence still lands on the
  same step. Then attach a failing review gate and verify `ready_for_validation`
  is rejected until the gate passes or is explicitly degraded.
- **Degradation rule:** if stable `plan_step_id` is unavailable, dependent
  plugins may still persist evidence with plan/session context, but it must be
  labeled `unattributed_step` and cannot satisfy artifact, living-report, review,
  modeling, or human-validation gates.

## Convergence checklist

| Surface | How this note uses it |
|---|---|
| Plugin | Patch existing `plugins/dataclaw-plans/` |
| Tools | `propose_plan`, `update_plan`, `get_plan`, `list_plans` |
| Hooks | Active plan context hook injects `proposal_id` and `plan_step_id` |
| Skills | `dataclaw` and artifact-producing skills rely on id-first updates |
| UI | Plan cards keep names editable without changing identity |
| Sub-agents | Not applicable |
| OpenClaw | Bridge manifest/allowlist exposes plan tools as canonical names or `dataclaw_...` aliases with identical schemas |
| Validation | golden rename/update/gate fixture and OpenClaw alias/manifest check |

---

# Requirements

## Functional requirements

- **FR-1** Every plan step gets a stable `plan_step_id` at proposal time.
- **FR-2** `update_plan` accepts step patches by `plan_step_id`; name matching is
  display-only fallback for legacy calls and must not create or fork step
  identity.
- **FR-3** Active plan context injection includes `proposal_id` and
  `plan_step_id` when a step is in progress.
- **FR-4** Step rename changes the display name only. It never changes
  `plan_step_id`.
- **FR-5** Plans support `ready_for_validation` gate metadata keyed by
  `plan_step_id`.
- **FR-6** `ready_for_validation` is rejected when a required gate returns
  `fail` or required-review `unknown`.
- **FR-7** Tool results and plan outputs can attach evidence ids, artifact ids,
  query card ids, modeling ids, and review ids to a `plan_step_id`.

## Non-functional requirements

- **NFR-1 Durability** - step ids are persisted with the plan and survive
  process restart.
- **NFR-2 Compatibility** - legacy name-based updates continue to work only when
  there is an unambiguous single match; ambiguous matches return a structured
  error.
- **NFR-3 Auditability** - gate transitions are append-only events with actor,
  timestamp, previous state, and reason.

## Phasing & exit criteria

| Phase | Scope | Exit test |
|---|---|---|
| P1 - Stable step ids | step id generation, id-first `update_plan`, legacy fallback errors | Renaming a step does not fork attribution |
| P2 - Active context | hook injection of `proposal_id` and `plan_step_id` | Query/EDA/model evidence receives `plan_step_id` automatically |
| P3 - Validation gates | `ready_for_validation` gate metadata and transition checks | Analysis Review can block and then clear a high-risk step |

## Tool contract delta

```python
update_plan(
    proposal_id=None,
    step_patches=[
        {
            "plan_step_id": "s2",
            "name": "Display name only",
            "status": "completed",
            "summary": "...",
            "outputs": [],
        }
    ],
    status=None,
    summary="",
)
```

Legacy `{name: ...}` patches are accepted only when one existing step matches
exactly. Otherwise the tool returns a structured ambiguity error and asks for
`plan_step_id`.

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| Step rename forks living-report attribution | id-first updates and tests that rename mid-run |
| Legacy agents send name-only patches | unambiguous fallback plus structured ambiguity errors |
| Review gate blocks ordinary iteration | gates block `ready_for_validation`, not execution |
| Plugins invent local step ids | active context hook is the only source of `plan_step_id` |
