---
name: artifacts
description: Publish, revise, inspect, export, and troubleshoot DataClaw artifacts. Use when a report, dashboard, chart, profile, model card, or living-report note should become a secure, versioned, shareable artifact through dataclaw-artifacts.
tags: [artifacts, reporting, dashboards, visualization, publishing]
---

## When to use
Use this skill whenever the final visual or written deliverable should be a
DataClaw artifact: reports, dashboards, chart pages, data profile reports,
model cards, stakeholder exports, and living-report notes.

This skill owns artifact lifecycle behavior. For content and layout, also fetch:
- `report_design` for final report authorship, evidence review, and quality gates
- `visualization` only when analysis-time charting or evidence preparation is needed
- `structured_eda`, `sql_analyst`, or `modeling` when the artifact is evidence from those workflows

## Core rule
The notebook computes, `report_design` authors, and artifacts publish. Do not leave the
final deliverable as a loose workspace HTML file, App-panel state, long chat
answer, or raw chart collection.

The durable UI surface is the inline published-artifact card plus the right
panel Artifact Library/living report. Treat `/app/:sessionId` as a legacy
compatibility scratch view for loose visual outputs, not as a final handoff.

The handcrafted report author may create a report-specific visual system. Do
not retrofit its output to a fixed component library. Preserve the required host
contrast tokens, evidence metadata, CSP, safety constraints, and receipt.

Use `publish_artifact` for a standalone report, dashboard, chart page, profile,
or model card. Use `report_note` for interpretation, decisions, rationale, and
course changes in the living report. Pass `plan_step_id` when available; names
are display labels. A major published artifact should also be linked or
summarized in the living report.

For EDA findings, `record_eda_finding` is the living-report entry. Do not add a
separate `report_note` for the same finding just to satisfy the living-report
habit; use `report_note` only for non-EDA interpretation, decisions, rationale,
and course changes that are not already captured by the EDA ledger.

## Tool names and fallback
Use the canonical tool names in this skill: `publish_artifact`,
`read_artifact`, `list_artifacts`, `export_artifact`, `delete_artifact`, and
`report_note`. If the runtime exposes only plugin-prefixed aliases such as
`dataclaw_publish_artifact`, use the visible alias with the same arguments.

If artifact tools are unavailable, still build the canonical workspace HTML
source and report that artifact publication is unavailable. Do not claim an
`artifact_id`, version, URL, export, or living-report note that did not happen.

## Publish workflow
1. **Prepare the source.** Prefer a workspace `source_path` over inline `html`.
   The source should be self-contained authored or typed report HTML that has
   passed the appropriate report flow.
2. **Validate before publish.** For a report-builder HTML source, first call
   `report_publish(report_path=..., storyboard_path=...)` and inspect its
   receipt, quality, and runtime-smoke result. Then check for remote assets,
   iframe/object/embed/base tags, raw datasets, fetch/XHR/WebSocket calls, inline
   event handlers, and oversized
   published/exported payloads. Fix obvious issues before calling the tool.
3. **Publish.** Call:
   `publish_artifact(title, description?, source_path?, html?, report_receipt_path?, artifact_id?, label?, base_version?)`
   with exactly one of `source_path` or `html`. For report-builder HTML (typed
   section metadata), pass the `receipt_path` returned by `report_publish` or
   keep its default sibling `<report>.publish.json`; publication verifies the
   receipt against the exact HTML bytes and rejects stale or analytically blocked
   reports.
4. **Confirm the result.** Expect `{artifact_id, version, session_id, url}`.
   Mention the artifact title and version briefly; the UI renders the same
   version inline and in the Artifact Library.
5. **Optional visual review.** Capture and approve desktop screenshots only when
   the user or report requirements explicitly request visual review. Routine
   artifact publication does not require mobile, light/dark, or screenshot gates.

## Revision workflow
When the user asks for a change to an existing artifact:

1. Call `read_artifact(artifact_id, version?)`.
2. For a structured or creative report, update its findings, aggregate inputs,
   requirements, or design brief and re-run `report_design_report`; do not edit
   generated HTML as the source of truth. For a generic non-report artifact,
   make the smallest safe source edit.
3. Re-run notebook/query/model computations when the underlying evidence changed.
4. Re-run `report_publish` for report-builder HTML, then call
   `publish_artifact` with the same `artifact_id` and the `base_version`
   you edited from.
5. If the tool returns a conflict, read the latest version and re-apply the
   change intentionally. Never last-writer-wins by guessing.

Do not create a new artifact for normal revisions of the same report/dashboard.

## Export workflow
When the user asks for an export, call
`export_artifact(artifact_id, version?)`. Expect a result with
`download_url`, `filename`, and `bytes`; do not fabricate export links. Artifact
open/source/export/delete operations are session-scoped, so use the current
session context and do not copy an artifact id into another session's handoff.

## Security contract
Artifacts are hostile-content-safe by default. Follow these rules:

- No live data querying from artifact JavaScript. Artifacts must not fetch from
  DataClaw APIs or the network.
- Aggregate in the notebook; embed only summary JSON or typed section payloads.
- No remote `script src`, `link href`, or remote `img src`.
- Relative file assets are allowed only when their resolved path stays inside
  allowed workspace/project roots; never use `../` paths to reach outside the
  report's workspace.
- No `<iframe>`, `<object>`, `<embed>`, or `<base>`.
- No inline event handlers such as `onclick`; use `addEventListener`.
- No JavaScript-driven navigation such as `window.open`, `location = ...`,
  `location.assign(...)`, or `location.replace(...)`.
- Preserve the host-required contrast tokens and metadata, but allow the
  report author to choose a distinctive inline visual system.
- Ordinary external `<a href>` links may exist, but artifact runtime must escape
  them through the parent/open-in-tab affordance; do not attach custom link
  handlers.
- The 25 MiB cap applies to the published/exported single-file artifact, not the
  living-report manifest store.

If validation fails, fix once and retry. If it fails again, surface the
machine-readable error to the user instead of silently looping.

## Tool patterns

### Create a new artifact
```python
publish_artifact(
    title="Customer Retention Dashboard",
    description="KPI and segment-level view of repeat purchase behavior.",
    source_path="reports/customer-retention.html",
    label="initial-dashboard",
)
```

### Revise an artifact
```python
current = read_artifact(artifact_id="art-3f9c21ab")
# edit the canonical source path, then:
publish_artifact(
    title="Customer Retention Dashboard",
    source_path="reports/customer-retention.html",
    artifact_id="art-3f9c21ab",
    base_version=current["version"],
    label="heatmap-revision",
)
```

### Add living-report narrative
Use `report_note(page, markdown, plan_step_id?)` for interpretation, rationale,
direction changes, or decisions that hooks cannot infer.

Good notes are short and evidence-linked:
- one note per non-EDA finding
- one note per changed course
- include the stable plan step id when available; names are display labels
- explain why the user should care, not just what happened

If only a step name is available, include it as human context and do not invent
a step id. Living-report attribution should travel by id, not by name.

## Read-right / act-left behavior
Use the right panel to inspect artifact library state, versions, and living
report status. Use chat/tool calls to publish, revise, delete, export, or add
living-report notes.

## Completion checklist
Before closing an artifact-producing step:
- artifact was published or intentionally degraded to download-only/unpublished
- version and `artifact_id` are known
- source path remains the canonical editable source
- no raw rows or live API calls are embedded
- light/dark and responsive layout were checked for reports/dashboards
- plan outputs or living-report notes include the artifact/evidence link
