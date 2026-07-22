# Chat Console and Report Review - Build Spec

Companion to [chat-redesign-prd.md](chat-redesign-prd.md). Reference implementation of
every visual and interaction decision: [mockups/chat-redesign.html](mockups/chat-redesign.html)
(self-contained; open in a browser. Append `?review=1` to show the annotated review controls).

Numbers in this spec (widths, caps, timings) are the mock's values — treat them as
defaults to tune, not constants to re-litigate.

## 1. Layout & regions

```
┌ left nav ┬───────────────────────────────┬ panel ┬ rail ┐
│ 200px    │ topbar (50px, single row)     │ 400px │ 46px │
│ dark     ├───────────────────────────────┤ on-   │ fixed│
│          │ thread (flex, scroll-y)       │ demand│      │
│          │   └ thread-in max-w 1000px    │       │      │
│          ├───────────────────────────────┤       │      │
│          │ composer (queue + input row)  │       │      │
└──────────┴───────────────────────────────┴───────┴──────┘
```

- **≥1161px:** below 1400px viewport width the 400px panel overlays the thread
  (absolute, shadowed) instead of pushing it. This keeps a ≥900px console at the
  smallest desktop width where that promise is physically possible.
- **761–1160px:** the left nav collapses to icons and the panel becomes a full console
  sheet, so opening it never leaves a cramped chat column beside it.
- **≤760px:** the left nav hides, Scope and Auto fold away from the top bar, and the
  panel is a sheet covering the console while the 46px rail remains available.
- Left nav keeps the two contexts distinct without listing sessions: **Chats** opens
  independent sessions; **Projects** opens the project catalog. A project page lists
  only the sessions scoped to that project. Data / Subagents / Tools / Skills / Config
  remain resource navigation, not chat tabs; session Datasets and Experiments live in the right rail.
- Topbar: back · session title · context chip (Independent | Project name) · (spacer)
  · plan pill · Auto · session actions. Datasets, Experiments, and Scope open from the right rail.
- Panel width 400px (resizable 360–560 later; not in v1). Rail is permanent.
- Report list and status summary use the 400px panel. Selecting a report opens a
  `ReportReviewView` over the console at `min(1120px, calc(100vw - rail - 32px))`;
  on ≤1160px it becomes a full console sheet. Full-page captures must never be
  squeezed into the ordinary side panel.

### 1.1 Session ↔ project boundary

- A session with `project_id = null` is independent and is created/browsed from Chats.
  A session with `project_id` is created/browsed from that project's Sessions surface;
  its project id is passed deliberately, never inferred from unrelated navigation.
- Plans, queue, transcript, and notebook state always belong to the session. A
  project-scoped session uses the project workspace and project configuration as its
  starting defaults; session Scope records any overrides.
- The Files tab labels its source: **Session workspace** for independent sessions and
  **Project workspace · {project name}** for project sessions. The context chip uses
  the same distinction.

## 2. Design tokens (P0 — do this first)

Introduce `ui/src/tokens.css` as CSS custom properties; components consume tokens,
never literals. From the mock:

```
--ink #1a222e   --muted #667085   --faint #667085
--line #e7ebf0  --line-soft #f0f3f7
--bg #ffffff    --bg-soft #f7f8fa
--rail #10151e  --rail-ink #e8ecf2  --rail-muted #8b95a3
--accent #0b63ce  --accent-soft #eef4ff
--bad #b42318   --bad-soft #fef3f2   --good #137333   --warn #8a5a00
--mono ui-monospace,"SF Mono",Menlo,Consolas,monospace
```

Rule: `--accent` = interaction/identity only; `--good/--warn/--bad` = status only;
success states in the transcript wear no color at all.

## 3. Transcript

### 3.1 Turn grouping
- Group timeline entries by AG-UI run id; within a run, tool calls between narrative
  text blocks form one `TurnActivity`. Assistant narrative stays outside the group.
- Header: `{Planned|Worked|Working} · {n} steps · {mm:ss} [· {k} errors fixed]`.
  Verb: `Planned` if the group contains propose_plan and no execution tools;
  `Working` while streaming; else `Worked`.
- Default collapsed for completed turns; running turn open with spinner header and
  pulsing last line. Completed-turn expansion state is per-turn, not persisted.
- Error headers: "· {k} errors fixed" only when a later successful call retries the
  same tool against the same cell, file, or dataset. A run that ends on an unresolved failure renders
  `Worked · {n} steps · {k} errors` with the count in `--bad` and the failing step
  auto-expanded.
- Step timestamps are run-relative and prefixed `+m:ss`; syslines use wall-clock —
  the prefix is the cue distinguishing the two.
- Fix in the same PR: `useAGUI` emitting nameless tool events (`unknown` cards today).

### 3.2 Step-line verb map
| Tool | Step line |
|---|---|
| insert_cell | `Added {code|markdown} cell [i] · {n} lines[ — {summary}]` (expand → capped source) |
| edit_cell / edit_cell_source | `Edited cell [i] — {summary}` (expand → diff) |
| execute_cell / execute_code | `Ran cell [i] · {dur}` ; error → red + `· {ErrType}: {msg}` (expand → traceback) |
| open_notebook / close_notebook | `Opened|Closed notebook {name}` |
| ws_read_file / ws_write_file | `Read|Wrote {path}[ · {size|rows}]` |
| ws_list_files / ws_update_file / ws_exec | `Listed files [in {path}]` / `Updated {path}` / `Ran workspace command — {command}` |
| data_* | `Listed available datasets`, `Previewed|Profiled {table} in {dataset}`, `Queried {dataset} — {SQL}` |
| fetch_skill | `Loaded skill {name}` |
| propose_plan | `Submitted plan {name} for review` |
| update_plan | `Updated plan — {summary of step changes}` |
| delegate_to_subagent | `Delegated to {name} · {k} turns` (expand → conversation, current renderer) |
| display_* | not a step line — reader-facing evidence (see §4) |
| finalize_analysis_package | `Finalized analysis package — {n} findings · review {status}` |
| create_report_storyboard | `Built report story — {n} beats · {k} explicit omissions` |
| author_visual_report | `Authored visual report — {desktop capture status, when requested}` |
| review_visual_report | `Reviewed visual report — {approved|rejected|blocked}` |
| publish_report | `Published report {title} · v{version}` only when a valid `PublishReceipt` is returned; otherwise show the concrete blocker |
| report_add_section | Conversational report mutation inside `Worked`: `Set the report opening: {title} — {subtitle}`, `Added the headline metrics — {labels}`, or `Added an interpreted chart: {title} — {caption}`. Adjacent identical mutations collapse to one line with a consolidation note. |
| mlflow log | `Logged run {name} to MLflow — {headline metric}` |
| *(unknown)* | Humanize the tool name and attach its best available target: `Read|Created|Updated|… {object} — {file|dataset|query|URL}`; final fallback is `Completed {human-readable tool name}`, never `Ran a tool` |

Identifiers (`[4]`, paths, skill names, metrics) render in `--mono` at 11.5px;
timestamps in a fixed 34px gutter; step rows ~24px.

### 3.3 Detail expansion
- Source/traceback blocks: cap 200px, fade-out + "Show all {n} lines"; light syntax
  theme (no vscDarkPlus); horizontal scroll allowed inside `pre` only.
- Collapsed details unmount (no `display:none` retention). Plotly figures in evidence
  cells are exempt (state preserved) — they live outside turn groups.

## 4. Notebook-in-chat cells

Shared rail: 58px gutter + 12px gap; all assistant content aligns to it.

- **md cells** (assistant narrative): gutter label `md`; body = markdown via existing
  `MarkdownContent` with h4/ul/li/inline-code styles; 3px left rail `--line-soft`;
  no box. max-width 76ch.
- **Out [n] cells** (evidence): gutter link `Out [n]` → opens the cell (file preview
  today; notebook anchor later); body boxed with 3px left border.
- Evidence allowlist (everything else becomes a step line):
  - `display_metric` → metric tile row (2–5 tiles, indent 70px)
  - Plotly outputs of `execute_cell`/`display_cell_output` → interactive figure
  - `display_image` → image, max-height 480px
  - DataFrame/table HTML → styled table capped at ~10 rows + `{k} more rows · open
    full table — {path}` footer; wide tables scroll inside the cell body only
  - reporting lifecycle tools → one-line status summary + Reports rail badge/state
    update; capture and review images render in `ReportReviewView`, not as notebook
    output cells
- Every chart/table cell carries a one-line caption slot (stat + caveat, per
  `skill-library/visualization.md`).

### 4.1 Provenance (every evidence cell)
- Footer row on each evidence cell: `cell [n] · ran at +t · {duration}` plus
  `▸ source` expanding the producing code inline (capped block, §3.3 rules).
- Producing step lines gain `↓ output` — scrolls to the evidence cell and flashes
  its border. Bidirectional with the `Out [n]` gutter link.
- Metric rows footer `values from cell [n] · reported at +t`; needs an optional
  `source_cell` param on `display_metric` (additive schema change, the one allowed
  exception to "no tool changes").
- The `md` gutter label was dropped — markdown cells show an empty gutter, matching
  Jupyter.

## 5. Plans

- Data: existing `usePlans`. Selection state (`showPlanList` / `showPlan(id)`) lives
  in the panel, not in chat.
- List: card = name · status tag · 1-line description · progress bar · `{done}/{total}
  steps · rev {r} · updated {t}`. Sort: pending → running/approved → rest by
  updated_at desc. Rail badge = plan count.
- Doc: back link `← All plans (n)`, meta chips (`plan.md`, status, rev, Expand),
  markdown doc (boilerplate untouched — decision #8). Expand keeps the current
  overlay behavior.
- Pill: `● Plan {short-name} {done}/{total} {status} [+n]`; dot green=completed,
  blue pulsing=running, amber=pending (`needs review` replaces the fraction). Click →
  deep-link doc. Two+ pending → `Plans · {k} need review`, click → list filtered to
  pending (post-v1 acceptable: plain list).
- Approvals — the **approval strip**: when a plan is pending, a slim amber strip
  renders above the composer (`⚠ Plan {name} awaits your review · View plan → ·
  ✓ Approve · ✗ Deny`), the composer placeholder becomes
  "Approve, deny, or type feedback for this plan…", the pill turns amber
  (`needs review` replaces the fraction), and the rail Plans dot turns amber. This is
  the single approval surface; the old banner/popover/auto-focus stay deleted. Typed
  feedback = changes_requested (current behavior).
- Lifecycle syslines: `✓ Plan {name} approved · rev {r} · {time}`, same for denied /
  changes requested.

## 6. Queue

- State: `queuedMessages: [{id, text, ts}]` + `queuePaused: bool` on the session
  (PATCH-persisted, survives reload).
- Composer Enter while `isRunning` → append + render ghost bubble at thread tail
  (dashed border, `QUEUED · NEXT|2ND|…` tag, hover: Edit / ⬆ Send next / × Remove).
- Dispatch: on **natural** run end and `!queuePaused`, shift head → normal send;
  repeat until empty or a run starts. Dispatched messages render with a
  `sent from queue · {time}` tag above the bubble. Queue preempts the auto-mode
  continuation message (auto turn only fires when the queue is empty).
- **Stop pauses the queue** (`queuePaused=true`): a "⏸ Queue paused — {n} messages
  held, nothing sent" strip appears above the composer with a Resume action; queued
  bubbles grey out. Nothing dispatches after a cancel until explicit Resume (or a new
  manual send, which implicitly resumes).
- Queue visibility is in-thread only — no counters in the composer or topbar
  (decision 2026-07-07).

## 7. Fork — removed

Cut on 2026-07-07 after review: a fork's workspace/notebook-state semantics
(copy-on-fork vs. shared vs. snapshot) are unresolved, and a chat-only fork whose
transcript references cells the workspace no longer contains is broken by
construction. No fork affordances anywhere in v1; revisit post-v1 with a real
workspace-snapshot design.

## 8. Dataset & scope tabs

- **Datasets:** its own rail tab, with readable names, ids as secondary metadata, and
  `Use all` / `Clear` actions. It persists `datasetIds` for exactly the active session.
- **Scope:** groups Tools / Skills / Subagents / Guardrails. Headers show name · count ·
  state (`all on` green, `{k} off` amber, `none defined` faint); rows are editable in
  place. Restriction counts appear on the relevant rail tab. Settings-vs-review nuance:
  editing here is allowed; content approvals are not.

## 9. Reports

The Reports rail is the primary inspection and publication surface for the canonical
[analysis → storyboard → visual report pipeline](../report-authoring-system-v2.md).
The UI does not reconstruct state from a sequence of tool calls. It consumes one
session-scoped report summary endpoint and one detail endpoint.

### 9.1 UI contract

The detail response has four nullable, monotonic records:

```ts
interface ReportDetail {
  reportId: string
  state: 'ANALYZING' | 'ANALYSIS_READY' | 'STORY_READY' | 'REPORT_READY' | 'PUBLISHED'
  analysisPackage?: AnalysisPackageSummary
  storyboard?: StoryboardSummary
  build?: ReportBuildSummary
  receipt?: PublishReceiptSummary
  blocker?: { stage: 'analysis' | 'story' | 'visual' | 'publish'; code: string; message: string }
}
```

Every summary carries its stable id and SHA-256. The API supplies dependency and stale
state explicitly; the client does not compare timestamps or parse filenames to infer
validity.

Until the canonical endpoint ships, a compatibility adapter may list existing living
reports and artifacts, but it must label them `legacy` and cannot synthesize
`REPORT_READY`, review approval, or a receipt.

### 9.2 Report list

- Row: title · canonical state · last valid stage · updated time · blocker badge.
- Sort: blocked/review-needed first, active next, published last by update time.
- Rail badge counts reports needing action, not all historical artifacts.
- `designed`, `authored`, `scratch`, and `living` are compatibility labels, not v2
  lifecycle states.
- Selecting a row opens `ReportReviewView`; Open published report is a secondary
  direct action only when a receipt exists.

### 9.3 Review view

The wide review view has four compact tabs with shared identity header:

1. **Analysis** — goal, primary findings, support status, caveats, and analytical
   review decision.
2. **Story** — thesis, ordered beats, finding coverage, explicit omissions, evidence
   gaps, and editorial review decision.
3. **Visual review** — report preview plus optional desktop full-page/key-section
   captures, deterministic browser findings, visual-review findings, and repair ownership.
4. **Publication** — exact HTML hash, capture hashes, receipt, version, and shareable
   link.

The identity header always shows report state and the short hashes of the analysis
package, storyboard, and build. Clicking a short hash exposes the full copyable value.

### 9.4 Capture renderer

- Recognize `report_capture_visuals` and `report_review_visuals` payloads through a
  typed renderer, never the generic JSON viewer.
- Fetch images through authenticated session-scoped artifact URLs; do not load local
  filesystem paths in the browser.
- Show viewport tabs with dimensions and SHA-256. Fit the image to width initially;
  provide 100% zoom and open-full-size actions.
- A capture is inspectable only after image load succeeds. Error and retry states keep
  approval/publication unavailable.
- Review findings link to a capture and, when present, a region or storyboard beat.
  Selecting a finding focuses that evidence.
- Image `alt` describes report title, viewport, and review role; hashes are metadata,
  not alternative text.

### 9.5 Actions and invalidation

- Presentation defects offer **Repair visual report**; editorial defects offer
  **Revise story**; analytical gaps offer **Return to analysis**. Each action invokes
  the owning stage and does not mutate downstream contracts locally.
- Provider/auth/browser failures show **Retry** and preserve the last valid state.
  There is no “publish draft”, tier downgrade, or deterministic fallback action.
- **Publish report** is enabled only in `REPORT_READY`. It calls `publish_report`
  once and consumes the returned `PublishReceipt`; it never follows with
  `publish_artifact`.
- New analysis clears the visible storyboard/build/receipt bindings, storyboard
  revision clears build/receipt, and HTML-byte revision clears captures/review/receipt
  as directed by the server response.
- After publication, the receipt card is the source of truth for artifact id, version,
  HTML hash, publication time, and shareable URL.

### 9.6 Component boundary

```text
ArtifactPanel
  ReportList
  ReportReviewView
    AnalysisPackageView
    StoryboardView
    ReportCaptureGallery
    ReportReviewFindings
    PublishReceiptView
```

`ArtifactPanel` may continue to host legacy non-report artifacts during migration.
Canonical report state and actions live in the report components and typed API client,
not in `ChatPage.tsx` tool-result scans.

## 10. Removals checklist

`ProjectPage` tab strip · standalone Alert · `PendingPlanBanner` · plan popover +
auto-focus effect (`ChatPage` ~L314-323) · per-call `ToolCallCard` chrome · five
filter modals · `react-ipynb-renderer` from thread path · `AUTO_EXPAND_TOOLS` (replaced
by evidence allowlist) · `Plan 1/Plan 2` buttons in `PlanPanel`.

## 11. Phases & exit criteria

| Phase | Scope | Exit criteria |
|---|---|---|
| P0 | tokens.css; swap literals in touched files | no visual change; snapshot parity |
| P1 | turn grouping + step lines + verb map + unknown fix; evidence allowlist; md/Out cells; capped blocks | fixture renders per PRD gate; height metric met |
| P2 | edge rail + panel (Plans list/doc, Files, Experiments, legacy Reports list); pill; syslines; remove banner/popover | plan review in 1 click; no plan UI in thread except syslines |
| P3 | queue incl. pause/resume + session API; provenance footers + ↓ output links | queued fixture dispatches FIFO on natural end only; Stop holds the queue; every evidence cell footers its cell |
| P4 | Scope tab; delete modals; rail state badge | scope edits persist; amber rail badge on restriction |
| P5 | session-context navigation, chrome cleanup, removals checklist, delete `chat_v2` flag | independent sessions are reachable from Chats; project pages list their own sessions; no global interleaved session list; both fixtures pass |
| P6 | typed report API adapter; wide review view; analysis/story coverage; capture renderer; review findings; receipt-backed publication; legacy report cutover | report fixture passes; images are inspectable in the main UI; stale evidence blocks publish; one `publish_report` call returns the shareable link; no generic report publication remains |

## 12. Accessibility & interaction

- All disclosure affordances are buttons with `aria-expanded`; step rows reachable by
  keyboard (Enter/Space toggle). Scope and Auto use keyboard-operable switches; the
  composer is a labelled textarea, never a pseudo-input. Focus is visible throughout.
- The live turn header is announced as status; queued bubbles announce their position.
- Opening the panel moves focus to its close button, makes the background inert, and
  Escape closes it and returns focus to the invoking control.
- `prefers-reduced-motion`: no pulse/spin animation, instant expand.
- Color is never the only signal: errored steps carry the error text; guardrail modes
  carry tags; plan status has text tags beside dots.
- Capture tabs, findings, and report-stage tabs use roving keyboard focus. Full-size
  capture inspection traps focus and returns it to the invoking thumbnail on close.
  Report status, blockers, and review decisions always include text.

## 13. Open questions (tracked, not blocking)

1. Auto toggle: stays in topbar (flip frequency) vs. Scope group with its settings —
   currently topbar.
2. Revision diffs inside a plan doc (rev chips exist; diff view unspecified).
3. Resolved for v1: `Working` turn groups collapse on completion; expansion state is
   per-turn and is not persisted.
4. Multiple pending plans at once: pill reads `Plans · {k} need review` → list
   filtered to pending (plain list acceptable v1).
5. Cross-version visual diff is not required for v2; the receipt/version selector
   preserves enough identity to add it later without changing the report contracts.
