# Chat Screen Redesign — critique, decisions, and mock

Initiative: `ui_upgrade` · Drafted 2026-07-07 · Status: direction approved, mock v1 done, implementation not started.

The goal: **maximize the conversational console**. Thinking, intermediate steps, and cell
operations dominate the screen today; the transcript format, nested scrolling, and plan
access all need rework. Notebook *feeling* is preserved — this is built for analysts —
but not everything becomes a notebook.

Clickable mock: [`mockups/chat-redesign.html`](mockups/chat-redesign.html) (open in a
browser; toggle "Design notes" bottom-right for annotated rationale).

---

## 1. Critique of the current chat screen

The root problem: **the UI doesn't distinguish evidence from plumbing.** The skill
library draws that line (`skill-library/visualization.md`: chat = short narration +
deliberate visual evidence), but `AUTO_EXPAND_TOOLS` in
`ui/src/components/tool-renderers/ToolResultRenderer.tsx` auto-expands operational
plumbing (`insert_cell`, `execute_cell`, `ws_read_file`, …) with the same weight as
actual deliverables (`display_metric`, `display_image`, Plotly). Everything below is
downstream of that.

### Vertical space
- Every tool call is a full bordered card (`ToolCallCard.tsx`) — ~40px collapsed; real
  runs emit dozens. Reference UIs (Claude Code, Codex) use ~22px borderless text lines.
- Inserted/edited cells render **full source with no height cap**
  (`CellChangeRenderer` → `CellSourceView`); a 100-line cell is 100 lines of transcript.
  Raw JSON, ironically, *is* capped (200–300px).
- No batching: `update_plan → fetch_skill → insert_cell → execute_cell` = four cards,
  four green checkmarks. Success is rendered as loudly as failure.
- `unknown`-titled cards appear (timeline events with no tool name in `useAGUI`) — bug,
  fix regardless of redesign.
- Windowing (80 items) + `containIntrinsicSize: 'auto 80px'` misestimates expanded-cell
  heights → scroll jumps when paging history.

### Nested scrolling / "weird HTML framing"
- Each cell result embeds a **one-cell fake notebook** via `react-ipynb-renderer`
  (`CellOutputRenderer.tsx`) with its own stylesheet + `vscDarkPlus` dark code theme —
  a document-within-a-document, dark islands in a light UI.
- Wide pandas HTML tables scroll internally (h + v) inside an 800px column —
  scroll-inside-scroll; up to five independent scroll regions per screen.

### Horizontal real estate / chrome
- Message column capped at `maxWidth: 800` while side chrome eats the rest.
- Project tab bar duplicates the left nav (Data/Tools/Skills/Subagents in both).
- Five scope chips (datasets/tools/skills/guardrails) permanently occupy the toolbar for
  set-once session config.
- Right sidebar always exists at 420px default even when empty; collapse affordance is
  an undiscoverable custom `◀`.

### Plans
- Plan state surfaces in **four places** (inline tool notice, `PendingPlanBanner`
  popover, sidebar tab, auto-focus choreography in `ChatPage.tsx` that opens all of
  them at once). Reading a plan = 420px column or a near-fullscreen "Expand" overlay.
- `PlanPanel.tsx` generates boilerplate sections for every plan, and
  `groupStepsForMarkdown` buckets steps with domain-specific regexes (`/xg|finishing/`).
  **Decision: boilerplate stays for now** (see §2), but the entry-point problem is fixed.

### Mechanics
- Composer `disabled={isRunning}` — can't type during long runs.
- Expanded cards stay mounted forever (`display:none`) — Plotly memory accumulates.
- Subagent card renders a chat-within-a-chat with inverted bubble alignment.
- Raw tool names leak into UI; accent `#1677ff` means everything, therefore nothing.
- All styling is inline per-component; no token layer (`index.css` is 15 lines).

## 2. Decisions (2026-07-07)

| # | Decision |
|---|----------|
| 1 | **Transcript idiom: Codex × Claude hybrid.** One collapsed activity group per agent turn ("Worked · 14 steps · 4m 32s · 1 error fixed"); inside it, Claude-style one-line steps that expand in place. Success is monochrome; only errors get color. |
| 2 | **Notebook lives in the chat area.** Narrative text renders as markdown (`md`) cells and evidence (metric tiles, charts, tables) as `Out [n]` cells on one shared gutter rail, with full markdown formatting (headings, lists, inline code). No embedded notebook documents, no dark code islands, heights capped; full outputs open from Files. |
| 3 | **Right panel = Plans / Files / Reports only.** Read-only (act left, read right). The three tabs stay **visible at all times** as a slim edge rail on the right; panel content opens on demand. The App tab's future is the artifacts layer (parallel development — not part of this initiative). |
| 4 | **One plan entry point:** a status pill in the top bar (`● Plan WC2026 5/5 completed`) opens the panel. Banner, popover, and auto-focus choreography are removed. Approvals/feedback stay in the composer. |
| 5 | **Queue in the thread.** Composer is never disabled; messages sent mid-run join the **transcript** as ordered ghost bubbles (`Queued · next`, `Queued · 2nd`, …) that can be edited, removed, or bumped until they dispatch in order on run end. Stop sits beside Queue. |
| 6 | **Fork a chat** from any message (hover action) → branches the session; header shows a branch chip (`⑂ main`). |
| 7 | **Chrome subtraction:** project tab bar merges into the left nav; scope chips fold into one `Scope · All` control (counts shown only when restricted); standalone-chat alert removed; column widens to ~1000px. |
| 8 | **Plan boilerplate sections stay** (Validation/Deliverables/Risks) — content-model slimming deferred. |
| 9 | Verbs, not tool names, in step lines ("Added code cell [4] · 38 lines", not `insert_cell`). Raw args/JSON stay one expand deeper. |

## 3. Implementation notes (for when we build)

- Step zero: introduce a small design-token layer (CSS custom properties) — today ~40
  files of inline styles make any visual change a hunt.
- Turn grouping needs `useAGUI` to attribute tool calls to their parent assistant turn
  (it already interleaves a timeline; grouping key = run/turn id). Fix the `unknown`
  tool-name events while there.
- Evidence classification: keep an allowlist (`display_metric`, `display_image`,
  plotly-bearing `execute/display_cell_output`, `report_add_section` summary) rendered
  inline; everything else becomes a step line.
- Replace `react-ipynb-renderer` in-chat with a lightweight capped code/output block
  (light syntax theme); keep the full renderer for a dedicated notebook/file preview.
- Queue: buffer sends while `isRunning`, render the buffer in the transcript as ghost
  user bubbles, flush in order on `onRunFinished` (plumbing exists — auto-mode already
  re-sends there).
- Icons stay AntD outline style everywhere (nav, panel rail, file tree) — no emoji.
- Fork: new session created from a message index; copy history up to that point;
  parent/branch metadata on the session record for the header chip.
- Unmount collapsed tool detail instead of `display:none` (or virtualize) to stop
  Plotly memory growth.

## 4. Artifacts

- Clickable mock (this repo): `docs/ui-upgrade/mockups/chat-redesign.html`
- Hosted copies for review:
  - Current-state screenshot tour: https://claude.ai/code/artifact/8d3484a8-d469-4a53-b477-c8b00e4dea13
  - Redesign mock: https://claude.ai/code/artifact/d24aba12-4aac-460f-9858-1536d63ce716
