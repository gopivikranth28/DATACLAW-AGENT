# DataClaw Chat Console and Report Review - PRD

| | |
|---|---|
| **Status** | Draft, build-ready |
| **Owner** | Nandini Mathan |
| **Last updated** | 2026-07-16 |
| **Ships as** | `ui/src/` chat and report-review surface plus the additive reporting contracts required by that surface |
| **Composes with** | `plugins/dataclaw-plans`, `plugins/dataclaw-workspace`, `plugins/dataclaw-artifacts`, sessions API, AG-UI event stream, and the [report pipeline](../report-authoring-system-v2.md) |
| **Companions** | [chat-redesign.md](chat-redesign.md) (critique + decision log) · [chat-redesign-spec.md](chat-redesign-spec.md) (build spec) · [mockups/chat-redesign.html](mockups/chat-redesign.html) (clickable mock, rev 4) |

---

## Release-note-first framing

The DataClaw chat is now a working console, not a tool-call log. Agent turns collapse
to a single line ("Worked · 14 steps · 4m 32s · 1 error fixed") that expands into
plain-language steps; narrative and evidence render as notebook-style markdown and
output cells on one shared rail; plans, files, experiments, reports, and session scope live behind
an always-visible edge rail on the right; and you can keep typing while the agent works —
messages queue in the thread, pause when you press Stop, and dispatch in order.
Every chart, table, and metric carries its provenance: which cell produced it, when,
and the source one click away.

Reports use the same console as a first-class review surface. The Reports rail shows
the progression from approved analysis package to storyboard, authored HTML, and
published receipt. When visual approval is explicitly requested, desktop captures
render as images beside structured review findings; paths and raw JSON are never the
only evidence. Publication is available for a validated `ReportBuild`, with any
explicit visual-review requirement satisfied, and returns the final shareable link in
one step.

**Session boundary:** a chat is one session in one of two contexts: **independent**
(`project_id = null`) or **project-scoped** (`project_id` set). Both own their
transcript, plans, queue, and notebook state. A project-scoped session uses that
project's workspace and defaults; an independent session does not. The UI must always
name the current context and never mix both session lists in one global sidebar.

## Validation gate & degradation rule

- **Golden acceptance check:** replay the recorded WC2026 fixture session (60+ AG-UI
  events, two plans, one cell error, one Plotly chart, one metric row, one wide table).
  The transcript must render every tool call as a step line inside exactly three turn
  groups, show color only on the errored step, render the chart/metrics/table inline
  with `Out [n]` gutters, keep the composer enabled during the simulated run, dispatch
  two queued messages in order on run end, and show both plans in the Plans list with
  the pill pointing at the running one. No nested scroll regions inside the thread.
- **Report acceptance check:** replay a report fixture containing an approved
  `AnalysisPackage`, a storyboard with one explicit omission, a `ReportBuild`, desktop
  captures, browser findings, and a visual-review decision. The Reports
  surface must render the captures as images, expose the package/story/build hashes,
  show the omission and review findings, and publish through `publish_report` to a
  shareable link. Changing the HTML hash must invalidate the captures and disable
  publication. A provider-auth failure must remain retryable without creating a
  lower-quality fallback report.
- **Degradation rule:** Every step must still name the concrete action and, when
  available, its target. Known tools use the verb map; an unknown integration is
  humanized from its name and target (for example, `Completed search memory — pricing
  notes`), never rendered as "Ran a tool" or `unknown`. Sessions persisted before
  turn-id attribution render as one flat step group per run. If the plans plugin is
  absent, the pill, Plans tab, and syslines do not render; nothing else degrades.

## Convergence checklist

| Surface | How this PRD uses it |
|---|---|
| Plugin | no UI plugin; the surface consumes the canonical workspace/reporting and artifacts contracts |
| Tools | reporting operations are `finalize_analysis_package`, `create_report_storyboard`, `author_visual_report`, `review_visual_report`, and `publish_report`; legacy report tools remain compatibility-only until cutover |
| Hooks | none |
| AG-UI | turn grouping keys off existing run/message ids; unknown-name events get a fallback renderer; report lifecycle results update the Reports surface |
| Sessions API | existing PATCH persistence reused for scope and queue; report records are fetched by session id |
| Plans plugin | existing list/decision endpoints unchanged; UI-side selection logic replaced |
| Artifacts | immutable report builds, captures, review evidence, and `PublishReceipt`; generic artifact publication cannot publish a final report |
| Skills | reporting skills must follow the canonical analysis → storyboard → visual report → publish path |
| OpenClaw | no manifest changes; UI renders the same event stream |
| Validation | fixture-session replay above + visual regression on the four panel tabs |

---

# Part 1 - Product Requirements

## 1. Problem

The chat screen renders operational plumbing (cell inserts, cell runs, file reads,
plan updates) with the same visual weight as the analysis itself. Every tool call is
a bordered card; inserted cell source renders uncapped; each cell result embeds a
notebook document with its own scrollbars; plan state surfaces in four competing
places; the composer locks while the agent runs. On a real session the conversation
is a minority of the pixels. Full critique with code references:
[chat-redesign.md §1](chat-redesign.md).

## 2. Goals

- **G1** - Maximize the conversational console: one row of chrome, ~1000px column,
  panel content on demand.
- **G2** - Turn-grouped transcript (Codex×Claude hybrid): one collapsed activity line
  per agent turn; plain-verb step lines that expand in place; success monochrome,
  errors the only color.
- **G3** - Preserve the notebook feeling inside chat: markdown (`md`) cells for
  narrative, `Out [n]` cells for evidence, one shared gutter rail, no embedded
  notebook documents, no nested scrolling.
- **G4** - One home for session context: Plans / Files / Reports / Datasets / Experiments / Scope as a
  persistent right edge rail; read-right/act-left for content review.
- **G5** - Never block input: mid-run messages queue in the transcript, editable and
  reorderable until dispatch.
- **G6** - Provenance on every result: evidence cites its producing cell, with source
  and a step↔output link in both directions.
- **G7** - Multi-plan legibility: list-first Plans tab; the top-bar pill always names
  the plan needing attention.
- **G8** - Keep session context legible: Independent chats are browsed from Chats;
  project-scoped chats are browsed inside their project. The header names which context
  is active, and Scope distinguishes project defaults from session-only overrides.
- **G9** - Make report quality inspectable: show analysis/story coverage, optional
  desktop captures and visual review, validation findings, exact build identity, and
  the publication receipt in the primary product surface.

## 3. Non-goals

- No analytical, storyboard, or visual-authoring logic in the UI. The UI presents
  canonical contracts, evidence, review state, and allowed actions.
- No generic artifact action that can bypass report review or manufacture a
  `PUBLISHED` state.
- No plan content-model changes — boilerplate sections stay (deferred by decision #8).
- No dedicated notebook page; the notebook stays a chat-area experience.
- No theming/dark-mode expansion beyond the token layer itself.
- No backend plan/tool schema changes; UI-only interpretation of existing events.
- No global sidebar that interleaves independent and project-scoped chat sessions, and
  no hidden project context or invisible inherited configuration.
- No session forking — considered and cut (2026-07-07): the workspace/notebook-state
  semantics of a fork (copy vs. share vs. snapshot) are unresolved; revisit post-v1.

## 4. Users & Use Cases

| # | Use case | What must be true |
|---|---|---|
| U1 | "Watch a long auto-mode run" | Turns collapse to summary lines; thread stays scannable at any run length |
| U2 | "What did it actually do?" | Expanding a turn shows timestamped verb steps; any step expands to source/output/traceback |
| U3 | "Did anything go wrong?" | Errors are the only colored steps; turn header counts them |
| U4 | "Read the finding" | Narrative is markdown-formatted cells; evidence charts/tables/metrics inline with `Out [n]` links |
| U5 | "Review the pending plan" | Pill names it, deep-links to its doc; approval/feedback happens in the composer |
| U6 | "Which of my plans is which?" | Plans tab lists all plans with status/progress; revisions stay inside each plan |
| U7 | "Ask the next question mid-run" | Composer never disabled; queued messages visible in-thread, ordered, editable |
| U8 | "Where did this number come from?" | Every evidence cell footers its producing cell, run time, and duration; source expands inline; metrics cite their cell |
| U9 | "Limit what it can touch" | Datasets tab controls session data; Scope controls tools/skills/subagents/guardrails, with restriction badges on the rail |
| U10 | "Start a chat without choosing a project" | Chats creates an independent session immediately, with no project defaults |
| U11 | "Return to a chat inside a project" | The project lists only its own sessions; the chat header, Files, and Scope name the project context |
| U12 | "Why is this report missing the strongest finding?" | Reports shows the approved findings, storyboard coverage, and explicit omissions before the visual report |
| U13 | "Did anyone actually inspect this report?" | When visual review was requested, desktop captures and hash-bound browser and review findings render directly in the Reports surface |
| U14 | "Publish the validated report" | One action publishes the exact validated HTML bytes and returns a receipt-backed shareable link |

## 5. Functional Requirements

### 5.1 Transcript
- **FR-1** Group all tool activity between two user/assistant narrative boundaries
  into one activity block keyed by run/turn id, with summary line
  `{verb} · {n} steps · {duration} [· {k} errors fixed]`.
- **FR-2** Step lines use the verb map (spec §3.2), monospace only for identifiers;
  raw args/JSON one expansion deeper.
- **FR-3** Only failed steps are colored; expanded error detail is capped and scrolls
  the page, not itself.
- **FR-4** Running turns stream steps live under a spinner header; the newest step
  pulses.
- **FR-5** Unknown-name events use the degradation rule; never render `unknown` or
  "Ran a tool".

### 5.2 Notebook-in-chat
- **FR-6** Assistant narrative renders as `md` cells (headings, lists, bold, inline
  code) on the shared 58px gutter rail.
- **FR-7** Evidence allowlist renders inline as `Out [n]` cells: metric tiles, Plotly
  figures, capped tables, images, report-section summaries. Everything else is a step
  line.
- **FR-8** Inline code/output blocks are height-capped with explicit expand; no
  `react-ipynb-renderer` in the thread; collapsed detail unmounts.

### 5.3 Plans
- **FR-9** Plans tab opens list-first: card per plan (name, status, progress, rev,
  updated), active/pending first; card → doc with back link.
- **FR-10** Pill shows the attention plan (pending > running > latest) plus `+n`;
  click deep-links to that plan's doc. Approvals/feedback stay in the composer.
- **FR-11** Plan lifecycle events render as centered syslines, not cards.
- **FR-12** PendingPlanBanner, plan popover, and sidebar auto-focus choreography are
  removed.

### 5.4 Queue
- **FR-13** Composer enabled during runs; Enter queues. Queued messages render
  in-thread as ordered ghost bubbles with edit / remove / send-next; dispatch FIFO on
  natural run end; persisted on the session. Queue state is visible only in-thread —
  no counters elsewhere.
- **FR-13a** **Stop pauses the queue.** Cancelling a run never auto-dispatches; a
  "Queue paused — {n} messages held" strip appears above the composer with explicit
  Resume. Messages that dispatched from the queue carry a "sent from queue · {time}"
  tag in the transcript.
- **FR-14** Provenance: every inline evidence cell renders a footer
  `cell [n] · ran at +t · {duration}` with expandable source; the producing step line
  links "↓ output" (scroll + highlight); metric tiles cite their source cell
  (optional `source_cell` param on `display_metric` — additive, backward-compatible).

### 5.5 Panel, rail & chrome
- **FR-15** Right edge rail (Plans / Files / Reports / Datasets / Experiments / Scope) is always visible with
  status badges; panel content opens on demand; rail tab toggles its panel.
- **FR-16** Datasets is its own editable session tab; Scope holds tools, skills,
  subagents, and guardrails (existing PATCH persistence). Restriction badges live on
  the relevant rail tabs. For project sessions the panels label project defaults and
  session-only overrides; independent sessions have no inherited defaults. The old
  filter modals are removed.
- **FR-17** The global left nav exposes a Chats destination for independent sessions
  and a Projects destination, but does not list every session. Project pages list only
  their project-scoped sessions. The chat header carries an Independent or Project
  context chip; message column max-width ~1000px; one top-bar row.

### 5.6 Reports

- **FR-18** The Reports tab lists report work by canonical state:
  `ANALYZING`, `ANALYSIS_READY`, `STORY_READY`, `REPORT_READY`, or `PUBLISHED`.
  UI labels may be friendlier, but must not invent a `designed` tier or derive state
  from tool names, filenames, or chat text.
- **FR-19** Report detail shows the bound `AnalysisPackage`, `Storyboard`,
  `ReportBuild`, and optional `PublishReceipt` identifiers and hashes. It displays
  primary finding coverage, explicit omissions, evidence gaps, and storyboard beats
  without requiring the user to open raw JSON.
- **FR-20** `report_capture_visuals` and `report_review_visuals` results have a
  dedicated renderer. Desktop full-page and key-section captures load as first-class
  images with viewport and SHA-256 metadata, full-size inspection, loading/error
  states, and keyboard-accessible navigation. A path or hash string alone does not
  count as rendered review evidence.
- **FR-21** Browser validation and visual-review findings render beside the captures,
  with pass/reject status and ownership. Analytical gaps link back to analysis,
  editorial defects to storyboard, and presentation defects to visual authoring.
- **FR-22** Publish is enabled for a validated, non-stale `ReportBuild`; a named
  approval is additionally required only when visual review was explicitly requested.
  `publish_report` stores the exact HTML and returns `PublishReceipt` plus a shareable
  link. The UI never chains `publish_artifact` after report publication.
- **FR-23** New analysis invalidates storyboard/build/review state; a storyboard
  change invalidates the build; and an HTML-byte change invalidates captures and
  review. The surface must show the stale dependency and the required repair stage.
- **FR-24** Provider, authentication, browser, or review outages are operational
  blockers. The UI offers retry and preserves the last valid stage; it never offers a
  deterministic or lower-tier fallback as an equivalent final report.

## 6. Success metrics

- Fixture-session rendered thread height reduced ≥ 70% vs current UI (collapsed state).
- Zero nested scroll containers inside the thread (audit via script).
- Composer available 100% of wall-clock time during runs.
- Plan review reachable in exactly one click from any state.
- No `unknown` strings anywhere in the transcript for the fixture session.
- 100% of required report captures render as inspectable images before approval or
  publication can be presented as complete.
- Zero published report links without a `PublishReceipt` whose HTML hash matches the
  reviewed build.
- Every primary analysis finding is either mapped to a storyboard beat or displayed
  as an explicit omission.

## 7. Rollout

Phased behind a `chat_v2` UI flag and a temporary `report_pipeline_v2` compatibility
flag; phase order and exit criteria are in
[chat-redesign-spec.md §10](chat-redesign-spec.md). The old transcript renderer is
removed after P5. Legacy report tiers, generic report publication, and path-only
review rendering are removed after the report fixture passes end to end.
