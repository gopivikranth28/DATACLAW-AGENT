# Chat Console Redesign - Build Spec

Companion to [chat-redesign-prd.md](chat-redesign-prd.md). Reference implementation of
every visual and interaction decision: [mockups/chat-redesign.html](mockups/chat-redesign.html)
(self-contained; open in a browser, toggle "Design notes").

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

- Below 1400px viewport width the panel overlays the thread (absolute, shadowed)
  instead of pushing it — the console never drops below ~900px usable.
- Left nav absorbs the project tab bar: Projects tree + Chat / Data / Subagents /
  Tools / Skills / Experiments / Config. `ProjectPage` tab strip is deleted.
- Topbar: back · session title · branch chip · (spacer) · plan pill · scope chip ·
  Auto · kebab. Nothing else. Standalone-chat Alert is deleted.
- Panel width 400px (resizable 360–560 later; not in v1). Rail is permanent.

## 2. Design tokens (P0 — do this first)

Introduce `ui/src/tokens.css` as CSS custom properties; components consume tokens,
never literals. From the mock:

```
--ink #1a222e   --muted #667085   --faint #98a2b3
--line #e7ebf0  --line-soft #f0f3f7
--bg #ffffff    --bg-soft #f7f8fa
--rail #10151e  --rail-ink #e8ecf2  --rail-muted #8b95a3
--accent #1677ff  --accent-soft #eef4ff
--bad #d92d20   --bad-soft #fef3f2   --good #16a34a   --warn #d97706
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
- Error headers: "· {k} errors fixed" only when a later run of the same cell
  succeeded. A run that ends on an unresolved failure renders
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
| fetch_skill | `Loaded skill {name}` |
| propose_plan | `Submitted plan {name} for review` |
| update_plan | `Updated plan — {summary of step changes}` |
| delegate_to_subagent | `Delegated to {name} · {k} turns` (expand → conversation, current renderer) |
| display_* / report_add_section | not a step line — evidence (see §4) |
| mlflow log | `Logged run {name} to MLflow — {headline metric}` |
| *(unknown)* | `Ran a tool` (degradation rule) |

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
  - `report_add_section` → one-line summary + Reports rail badge increment
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

## 8. Scope tab

- Groups: Datasets / Tools / Skills / Subagents / Guardrails. Header: name · count ·
  state (`all on` green, `{k} off` amber, `none defined` faint). Body: toggle rows
  (identifier + context tag; guardrails add phase + auto/approval tags). >6 rows →
  "Show n more…".
- Persistence: existing per-session PATCH endpoints (`datasetIds`, `toolIds`,
  `skillIds`, `subagentIds`, guardrail config). The five filter modals are deleted.
- Chip: `Scope · All` neutral; restricted → amber `Scope · {k} off`. Deep-links to
  the tab. Settings-vs-review nuance: editing here is allowed; content approvals are
  not (read-right/act-left applies to agent work).

## 9. Removals checklist

`ProjectPage` tab strip · standalone Alert · `PendingPlanBanner` · plan popover +
auto-focus effect (`ChatPage` ~L314-323) · per-call `ToolCallCard` chrome · five
filter modals · `react-ipynb-renderer` from thread path · `AUTO_EXPAND_TOOLS` (replaced
by evidence allowlist) · `Plan 1/Plan 2` buttons in `PlanPanel`.

## 10. Phases & exit criteria

| Phase | Scope | Exit criteria |
|---|---|---|
| P0 | tokens.css; swap literals in touched files | no visual change; snapshot parity |
| P1 | turn grouping + step lines + verb map + unknown fix; evidence allowlist; md/Out cells; capped blocks | fixture renders per PRD gate; height metric met |
| P2 | edge rail + panel (Plans list/doc, Files, Reports); pill; syslines; remove banner/popover | plan review in 1 click; no plan UI in thread except syslines |
| P3 | queue incl. pause/resume + session API; provenance footers + ↓ output links | queued fixture dispatches FIFO on natural end only; Stop holds the queue; every evidence cell footers its cell |
| P4 | Scope tab; delete modals; chip states | scope edits persist; amber chip on restriction |
| P5 | chrome merge (nav, alert), removals checklist, delete `chat_v2` flag | old paths deleted; both fixture types pass |

## 11. Accessibility & interaction

- All disclosure affordances are buttons with `aria-expanded`; step rows reachable by
  keyboard (Enter/Space toggle). Focus visible throughout.
- Live turn header is `role="status"`; queued bubbles announce position.
- `prefers-reduced-motion`: no pulse/spin animation, instant expand.
- Color is never the only signal: errored steps carry the error text; guardrail modes
  carry tags; plan status has text tags beside dots.

## 12. Open questions (tracked, not blocking)

1. Auto toggle: stays in topbar (flip frequency) vs. Scope group with its settings —
   currently topbar.
2. Revision diffs inside a plan doc (rev chips exist; diff view unspecified).
3. Whether `Working` turn groups should auto-collapse on completion or stay open
   until the user collapses them — mock keeps them open.
4. Multiple pending plans at once: pill reads `Plans · {k} need review` → list
   filtered to pending (plain list acceptable v1).
