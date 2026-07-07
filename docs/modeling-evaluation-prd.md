# DataClaw Modeling & Evaluation - PRD & Solution Architecture

| | |
|---|---|
| **Status** | Draft, build-ready |
| **Owner** | Nandini Mathan |
| **Last updated** | 2026-07-07 |
| **Ships as** | `plugins/dataclaw-modeling/` |
| **Composes with** | `plugins/dataclaw-plans`, `plugins/dataclaw-notebooks`, `plugins/dataclaw-intake`, `plugins/dataclaw-artifacts`, MLflow |

---

## Release-note-first framing

DataClaw can now run modeling work like a cautious data scientist: define a modeling spec, build a baseline, train candidate models in the notebook, log every run to MLflow, compare only compatible runs, and publish a model card with metrics, parameters, data digest, seed, environment, caveats, and the decision rationale. The human validates a comparison matrix and reproducibility block instead of digging through scattered notebook cells.

## Validation gate & degradation rule

- **Golden acceptance check:** train a baseline logistic regression and one tree model on a fixture dataset, log both runs, compare them on the same evaluation digest, publish a model card artifact, then rerun one model on a different split and verify it is badged "not directly comparable".
- **Degradation rule:** if automatic training helpers fail, the agent may still train in the notebook and log MLflow manually; the component only ships a comparison/model-card surface when required run tags and reproducibility fields are present. If artifact publishing is unavailable, the model card source is still compiled and stored as canonical evidence, but no `artifact_id`, version, export, review, or human-validation gate is satisfied until `publish_artifact` succeeds.

## Convergence checklist

| Surface | How this PRD uses it |
|---|---|
| Plugin | `plugins/dataclaw-modeling/` auto-discovered at startup |
| Tools | `create_modeling_spec`, `log_model_run_summary`, `validate_model_run`, `compare_model_runs`, `record_model_decision`, `publish_model_card` |
| Hooks | MLflow run completion and active plan context capture |
| Skills | new `skill-library/modeling.md` drives modeling spec, baseline, and comparison rules |
| UI | `modeling_spec_created`, `model_run_validated`, `model_comparison_ready`, `model_decision_recorded` events and read-only Modeling panel |
| Sub-agents | Not applicable in P1-P3; review handled by Analysis Review PRD |
| OpenClaw | Bridge manifest/allowlist exposes modeling tools as canonical names or `dataclaw_...` aliases with identical schemas; MLflow remains existing backend |
| Validation | golden baseline/candidate comparison, mismatched split fixture, model-card publish through artifacts, and OpenClaw alias/manifest check |

---

# Part 1 - Product Requirements

## 1. Problem

DataClaw already has notebooks and MLflow experiment tracking through `dataclaw-plans`, but model work lacks a product contract. Runs can be logged, yet there is no modeling spec, no baseline requirement, no compatibility check, no reproducibility block, and no durable model card that a human can validate. This makes "which model won?" answerable only by reading notebook cells and trusting the agent's summary.

## 2. Goals

- **G1** - Define a modeling spec before training: target, prediction unit, split, primary metric, baseline, and leakage risks.
- **G2** - Require at least one baseline before comparing advanced models.
- **G3** - Capture MLflow runs with dataset version/digest, split digest, seed, code hash, environment freeze, metrics, params, and `plan_step_id`.
- **G4** - Compare runs only when evaluation data is compatible; badge mismatches loudly.
- **G5** - Publish a model card artifact and living-report entry with chosen/rejected models and rationale.
- **G6** - Keep modeling helpers optional; notebooks remain the compute layer.

## 3. Non-goals

- No AutoML framework in P1.
- No model serving endpoint.
- No feature store.
- No distributed training.
- No claim that metrics prove causal or business impact.

## 4. Users & Use Cases

| # | Use case | What must be true |
|---|---|---|
| U1 | "Build a churn model" | Agent first creates a modeling spec with target, unit, metric, split, and baseline |
| U2 | "Which model won?" | Comparison matrix shows primary metric, baseline, deltas, and caveats |
| U3 | "Can I trust the comparison?" | Runs with different eval digests are badged not directly comparable |
| U4 | "Did you try a simple model?" | Baseline run is required and visible |
| U5 | "What data did this use?" | Dataset version/digest and split digest are in every run |
| U6 | "Can we reproduce it?" | Model card includes seed, code hash, env freeze, params, and notebook path |
| U7 | "Why reject the higher AUC model?" | Decision rationale links to metrics and caveats |
| U8 | "Put the model summary in the report" | Artifact/living report consumes the model card section |
| U9 | Target leakage sneaks in | Modeling spec and validation warnings flag likely leakage before training closes |

## 5. Functional Requirements

### 5.1 Modeling spec

- **FR-1** `create_modeling_spec(dataset_id, version_id, target, prediction_unit, primary_metric, split_strategy, baseline, problem_type?, notes?)` creates a durable spec.
- **FR-2** Spec validates required fields before any model comparison can be marked complete.
- **FR-3** Spec records leakage checklist: target availability, time leakage, duplicate entities, post-outcome features, and train/test grouping.
- **FR-4** Spec is tied to session, plan id, and `plan_step_id`.

### 5.2 Run capture

- **FR-5** `log_model_run_summary(spec_id, run_id, role, notes?)` attaches an MLflow run to the spec.
- **FR-6** Required run fields: model name, params, metrics, primary metric value, dataset version id, train digest, eval digest, seed, code hash, env freeze, notebook path, and `plan_step_id`.
- **FR-7** `validate_model_run(run_id)` returns missing fields and leakage/comparability warnings.
- **FR-8** Runs can be tagged as `baseline`, `candidate`, `chosen`, `rejected`, or `diagnostic`.

### 5.3 Comparison

- **FR-9** `compare_model_runs(spec_id, run_ids?, primary_metric?)` returns a comparison matrix.
- **FR-10** Comparison matrix includes baseline row, deltas vs baseline, primary metric, secondary metrics, params summary, eval digest, and warning badges.
- **FR-11** Runs with mismatched eval digest are grouped separately and cannot be auto-ranked together.
- **FR-12** Missing baseline blocks "complete" status but still shows candidate diagnostics.
- **FR-13** Human/agent decision rationale is stored with the chosen model.

### 5.4 Surfaces

- **FR-14** On spec creation and comparison update, emit `modeling_spec_updated` and `model_comparison_ready` AG-UI events.
- **FR-15** Inline model comparison card renders in chat.
- **FR-16** Right panel lists modeling specs and run groups read-only.
- **FR-17** `publish_model_card(spec_id, comparison_id?, artifact_id?, base_version?)` compiles the model-card source, then calls `publish_artifact` with the same `artifact_id`/`base_version` semantics as any artifact revision. It returns the artifact result `{artifact_id, version, url}` only after artifact publish succeeds; if artifact tools are unavailable, it returns a degraded source path and cannot satisfy model-card artifact gates.
- **FR-18** Living report Models page consumes comparison cards and decision rationale automatically.

## 6. Non-functional Requirements

- **NFR-1 Reproducibility** - no model run is "valid" without data digest, seed, code hash, and env freeze.
- **NFR-2 Compatibility** - builds on MLflow; does not replace it.
- **NFR-3 Durability** - specs/comparisons are append-only JSONL plus current index.
- **NFR-4 Performance** - comparison queries must handle hundreds of MLflow runs for a session.
- **NFR-5 Safety** - model cards must state that offline metrics are validation evidence, not production readiness.

## 7. Phasing & Exit Criteria

| Phase | Scope | Exit test |
|---|---|---|
| P1 - Spec and run validation | tools, store, required fields, MLflow tag bridge | Golden baseline/candidate runs validate; generated OpenClaw manifest/allowlist exposes modeling tools with identical canonical/alias schemas |
| P2 - Comparison card | matrix, baseline deltas, eval digest badging, inline renderer | Mismatched split is not directly comparable |
| P3 - Model card artifact | publish_model_card, living report Models integration | Model card artifact appears with repro block |
| P4 - Review helpers | leakage checklist improvements, feature importance section, reviewer hooks | Reviewer catches seeded leakage fixture |

## 8. Success Metrics

- Every completed modeling plan has a spec, baseline, comparison, and model card.
- 100% of model comparisons show eval digest compatibility.
- Human reviewers can reproduce the winning run metadata without opening MLflow directly.
- No chosen model lacks a rationale tied to metrics and caveats.

---

# Part 2 - Solution Architecture

## 1. System Context

Modeling is a coordination layer over notebooks and MLflow.

| Piece | Role |
|---|---|
| `plugins/dataclaw-notebooks` | compute/training layer |
| `plugins/dataclaw-plans` | active plan, MLflow experiment, run query tool |
| MLflow | metrics/params/artifacts store |
| `plugins/dataclaw-intake` | dataset version/digest |
| `plugins/dataclaw-artifacts` | model card artifact and living report |
| `skill-library/modeling.md` | modeling workflow rules added by this PRD |

## 2. Flow

```
SPEC       create_modeling_spec(target, metric, split, baseline)
NOTEBOOK   train baseline/candidates and log to MLflow
CAPTURE    log_model_run_summary or MLflow post-run hook validates tags
COMPARE    compare_model_runs groups by eval digest and computes deltas
DECIDE     chosen/rejected rationale stored against comparison
PUBLISH    compile model-card source -> publish_artifact -> living report Models page update
```

## 3. Key Decisions

| ID | Decision | Why | Rejected alternative |
|---|---|---|---|
| D1 | Notebook remains compute layer | It is reproducible, inspectable, and already integrated | Hidden training service |
| D2 | MLflow remains run store | Avoid duplicating metrics/params/artifacts | Custom experiment database |
| D3 | Modeling spec precedes comparison | Prevents metric/target/split drift after seeing results | Free-form "try models" only |
| D4 | Eval digest gates ranking | Ranking incompatible runs is false precision | Sorting all metrics together |
| D5 | Model card is an artifact | Modeling output needs same share/version/security story | Chat-only summary |

## 4. Plugin Layout

```
plugins/dataclaw-modeling/
  dataclaw_modeling/
    __init__.py       # tools, router, hooks, skill registration metadata
    tools.py          # spec/run/compare/publish tools
    store.py          # specs, comparisons, decisions
    mlflow_bridge.py  # query/tag/validate MLflow runs
    validators.py     # required fields, leakage/comparability checks
    card.py           # model card artifact section compiler
    router.py         # specs/comparisons endpoints
    hooks.py          # MLflow run completion + plan context capture
  tests/
skill-library/modeling.md
ui/src/components/
  ModelingPanel.tsx
  tool-renderers/ModelComparisonCard.tsx
```

## 5. Tool Contract

```python
create_modeling_spec(dataset_id, version_id, target, prediction_unit,
                     primary_metric, split_strategy, baseline,
                     problem_type=None, notes="")
# -> {spec_id, status, warnings}

log_model_run_summary(spec_id, run_id, role="candidate", notes="")
# -> {spec_id, run_id, validation_status, missing_fields, warnings}

compare_model_runs(spec_id, run_ids=None, primary_metric=None)
# -> {comparison_id, matrix, comparable_groups, warnings}

record_model_decision(spec_id, comparison_id, chosen_run_id, rationale,
                      rejected_run_ids=None)
# -> {decision_id, status}

publish_model_card(spec_id, comparison_id=None, artifact_id=None, base_version=None)
# -> {artifact_id, version, url} or {degraded: true, source_path, reason}
```

## 6. Storage Layout

```
workspaces_dir()/modeling/
  specs/
    mdl-churn-v1/
      spec.json
      run_links.jsonl
      comparisons.jsonl
      decisions.jsonl
```

MLflow remains authoritative for metrics/params/artifacts. Modeling store keeps product-level spec, comparison, and decision state.

## 7. Events & UI

- `modeling_spec_created`
- `model_run_validated`
- `model_comparison_ready`
- `model_decision_recorded`

Inline cards show spec status, missing requirements, and comparison matrix. Right panel reads specs/comparisons; chat acts.

## 8. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Agent trains without a baseline | baseline requirement blocks complete status |
| Metrics compared across different splits | eval digest grouping and badge |
| MLflow tags missing | validation tool and model card gate |
| Leakage missed | checklist plus Analysis Review seeded fixtures |
| Modeling plugin becomes AutoML | non-goal; helpers coordinate, notebook computes |
