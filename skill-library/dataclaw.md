---
name: dataclaw_data_science
description: Use Dataclaw tools for governed data science and analytics work. Includes tools for interacting with data, running jupyter notebooks, proposing, updating and reviewing analytical plans, experiment tracking, training machine learning models, and generating reports.
---

# Dataclaw Data Science Workflow

Use this skill when the user asks for data analysis, exploratory data analysis, notebook work, modeling, profiling, segmentation, visualization, or a data science report.

Follow this process:

1. Clarify the analytical goal, available data, expected artifact, and success criteria if they are ambiguous.
2. Open or create a notebook with `dataclaw_open_notebook`. Relative paths are resolved inside the project directory automatically. Prefer notebooks over creating scripts or directly executing code unless it is for diagnostics, a specific request, or quick checks. Notebooks are the standard artifact for data science work and are required for plan execution. They also provide a durable record of the analysis, decisions, and findings that can be reviewed, shared, and built upon over time.
3. Discover available data with `dataclaw_data_list_datasets`. This returns only datasets enabled for the current chat session, including dataset ids, table names, query aliases, descriptions, and column metadata without exposing connection strings. This should be called before reporting back that you can't find data.
4. Perform initial EDA before proposing major work. Use `dataclaw_data_preview_data`, `dataclaw_data_profile_dataset`, `dataclaw_data_describe_column`, and `dataclaw_data_query_data` for quick inspection. For any non-trivial EDA, model-readiness review, dashboard/KPI prep, survey/research analysis, time-series/event/text/geospatial/causal exploration, or data-quality audit, fetch the `structured_eda` skill before proposing the plan or executing the notebook. During pre-plan EDA, record the initial hypothesis batch with `dataclaw_propose_eda_hypotheses` and cite it in `plan_markdown`. Use `data_profiling` only for a compact quick profile. Use `dataclaw_insert_cell`, `dataclaw_execute_cell`, and notebook-reading tools when work needs to be captured in a notebook.
5. In notebook code, load datasets through the runtime helper package instead of asking for or constructing connection strings:

```python
import dataclaw_data

orders = dataclaw_data.get_dataframe(dataset_id="DATASET_ID", table_name="main.orders")
summary = dataclaw_data.get_dataframe(
    dataset_id="DATASET_ID",
    sql="SELECT status, count(*) AS orders FROM main.orders GROUP BY 1",
)
```

Use either `table_name` or `sql`, not both. The helper resolves data server-side, enforces the current chat session's dataset allowlist, and returns a pandas DataFrame.
If the dataset is not available via the helper, you can check the content of the workspace directory and see if there might be static files you can load into your notebook; You should not explore outside of the workspace directory or create files outside of it unless explicitly approved by the user.
6. Never ask the user for raw connection strings, never call a connection-string utility, and never print or save connection strings in notebook cells. If a user asks how data is accessed, explain that Dataclaw resolves dataset ids server-side and redacts sensitive connection values from notebook output.
7. Propose a plan with `dataclaw_propose_plan` before beginning execution (minor EDA is an exception). Keep the approval card compact: include a concise `name`, a clear `description`, and grouped ordered `steps` that combine obvious follow-on work where possible. Each step should have `name`, `description`, and `status`; use `not_started` for steps not yet begun. Leave `summary` empty unless the step already has completed EDA findings, and include `outputs` only for files that already exist. Also include `plan_markdown` as the detailed lead-review document for `plan.md`: objective, what is already known from previous inspection, assumptions and data limitations, grouped workstreams, validation and QA checks, expected deliverables, risks or open questions, and execution order. The Markdown should be richer than the card and should reflect any prior tool, notebook, or data findings.
8. The Dataclaw UI will send the user's approval, denial, or requested edits back as a normal chat message.
9. If the user denies the plan or requests edits in chat, simply call `dataclaw_propose_plan` again with the revised plan. Dataclaw will automatically update the existing unapproved proposal.
10. After an approval message, execute the flow in the notebook. Keep outputs reproducible, prefer `dataclaw_data.get_dataframe(...)` and polars or pandas transformations, and write durable intermediate artifacts where useful. Keep cells focused and concise, and avoid doing too much in a single cell. If a step has multiple distinct actions or findings, consider breaking it into multiple cells for clarity and better progress reporting. This may also avoid timeouts.
11. Any trained model should be logged to mlflow with a new run and meaningful names, tags, metrics, datasets, artifacts, and parameters.
12. Report progress with `dataclaw_update_plan` after every step status change and after every completed step (must have called `dataclaw_propose_plan` first as you can't update a non-proposed plan). When a step completes, populate that step's `summary` with the actions taken, key findings, validation checks, caveats, and next implication. Record material EDA observations with `dataclaw_record_eda_finding`, supersede changed findings with `dataclaw_supersede_eda_finding`, and call `dataclaw_summarize_eda_readiness` before proposing modeling/dashboard work that depends on EDA. Populate `outputs` with every durable file produced by the step.
13. Use notebook visuals when they help the analysis. Fetch `visualization` for non-trivial analytical charting or visual-integrity review; it is optional when validated aggregate outputs already exist. Share useful notebook output in chat with `dataclaw_display_cell_output` and use `dataclaw_display_metric` only for a genuinely useful headline. For a polished report, fetch `report_design` and hand it completed findings, bounded aggregates, grain, units, denominators, definitions, caveats, uncertainty, methodology, and stable evidence references. Register non-external references in `requirements.evidence_registry.targets`. Do not pre-compose the page with chart types, KPI counts, component names, or a sequence of `dataclaw_report_add_section` calls. Handcrafted composition is the default: the creative author owns all unspecified prose, story, layout, visual form, and safe interactions, while the evidence pass rejects unsupported causal or quantitative claims. Explicit story arcs, controls, brand, or visual direction are optional hard constraints only. Call `report_publish` with the designed HTML and storyboard paths (and `export_docx=False` unless Word output was requested) before `publish_artifact`, then fetch the `artifacts` skill for publication or revision. The final visual deliverable should be a published artifact or living report, not loose App/report state or a long prose-only chat answer. Keep showing useful notebook outputs during long work, but do not mistake those working visuals for the final report design.
14. Summarize the output with findings, caveats, methods used, files/notebooks produced, and recommended next actions.

Be explicit about assumptions, data limitations, and validation checks. Do not skip approval for work that changes files, runs long computations, exports results, or materially commits to an analytical direction.

## Plan Workflow Rules
- **CRITICAL**: You must successfully propose a plan with `dataclaw_propose_plan` and receive an ID before you can use `dataclaw_update_plan`. Do not attempt to update a plan that hasn't been proposed yet.
- Report progress by calling `dataclaw_update_plan` as you complete each step.
- Before setting `ready_for_validation: true`, request or inspect analysis review with `dataclaw_request_analysis_review` / `dataclaw_get_review_gate`. Completed high-risk or EDA-like steps may already have an automatic checklist review; if a required gate blocks the transition, resolve the review finding or ask the user before calling `dataclaw_accept_gate_risk`; never self-accept risk silently.
- Always include an `explain.md` and a summary of findings in each notebook's final cell.
- Deliver the final report through `report_design` and fetch `artifacts` before publish/revision. Call `report_design_report` with completed insights, bounded semantic aggregate assets, methodology, limitations, and the evidence ledger; let the creative author choose all unspecified story and visual decisions. Then call `report_publish` with the generated HTML and storyboard paths. Include `explain.md` as the written companion—never a text-only report or a final report made from appended chart sections.

## MLflow Integration & Experiment Tracking
Dataclaw manages the organization of your experiments but **does not automatically track metrics, parameters, or models**. You must explicitly add MLflow tracking code to your notebook cells.

- **Experiments**: Dataclaw automatically creates an MLflow Experiment for each chat session.

### Usage in Notebooks
The execution environment is pre-configured with `MLFLOW_EXPERIMENT_ID` and `MLFLOW_TRACKING_URI`. Use the `mlflow` library to log results.

**IMPORTANT**: You do not need to manage Run IDs manually. Just start a new run using `mlflow.start_run()` and Dataclaw will automatically associate it with your current plan after execution.

**Logging Guidelines:**
- **Params**: Only log model hyperparameters (e.g., `learning_rate`, `epochs`).
- **Tags**: Use tags for descriptive metadata (e.g., `model_type`, `dataset_name`).
- **Metrics**: Log performance results (e.g., `accuracy`, `loss`).
- **Artifacts**: Log generated files using `mlflow.log_artifact()`.
- **Datasets**: Log source data used for analysis/training.


```python
import dataclaw_data
import mlflow

with mlflow.start_run(run_name="Initial Model Training"):
    mlflow.set_tag("model_type", "LinearRegression")
    mlflow.log_param("alpha", 0.01)
    mlflow.log_metric("rmse", 0.045)
```

### Retrieving History
Use the `dataclaw_query_mlflow_runs` tool to fetch metadata from past runs in the current session.
You can also fetch past plans with `dataclaw_list_plans` and their details with `dataclaw_get_plan` to review the history of proposed plans, their steps, and outcomes.
