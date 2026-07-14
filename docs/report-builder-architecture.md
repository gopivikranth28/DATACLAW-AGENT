# Dataclaw Report Builder — Findings & Solution Architecture

_Consolidated design and implementation-status note. Branch: `structured-eda`. Scope: why
report visual/analytical quality regressed, what "good" means for a dataclaw report, and the
architecture to guarantee it. The document distinguishes shipped behavior from target design._

_Status refreshed 2026-07-14. The renderer overhaul, storyboard path, versioned rubric gate,
fail-closed publish boundary, raw-HTML normalization, bounded critique, evidence registry,
typed display-fact contract, evidence-bound runtime visual author, constrained story-block
reordering, and hash-bound human/vision approval over full-page/key-section browser review are
shipped. Deterministic rendered-page semantic review, source-bound regeneration recipes, and
declared rigor/component contracts are also shipped. DOCX fidelity/static fallbacks remain target work._

---

## 1. The problem

A recent report (`wc2026_report.html`) looked and read markedly worse than an earlier
handcrafted one (`wc2026_player_archetypes.html`), despite the newer one running on a more
capable rendering shell. The regression is real and reproducible, and it is **mostly a
routing failure, not missing capability** — plus two genuine renderer gaps.

### 1.1 Evidence

| | Before (good) | Now (regressed) |
|---|---|---|
| File | `wc2026_player_archetypes.html` | `wc2026_report.html` |
| Size / lines | 316 KB / 121 lines | 4.6 MB / 482 lines |
| Origin | Hand-authored, bespoke CSS | Storyboard renderer shell (`data-dc-section`) |
| Plotly charts | 2, **fully themed** (`paper_bgcolor`×4, `plot_bgcolor`×4, `colorway`×2, font, `template`×15) | 8, **zero theming** (no template/colorway/bg/font on any) |
| Plotly delivery | CDN (light) | ~4 MB library inlined |
| Section types | archetype cards, similarity explorer, numbered findings, callouts | 6 **consecutive plain `chart`** sections + bullet lists |
| Components used | pills, badges, stat strips, similarity bars, evidence | `metric_row`, `findings`, `chart`, `table`, `callout` |

### 1.2 Root causes

**A. The report skipped the designed pipeline entirely.** The renderer already contains
all the handcrafted machinery — `chart_interpretation`, `chart_table_explorer`,
`selector_panel`, `entity_card_grid`, `insight_grid`, `narrative_band`, `methodology_block`,
plus content-type-driven layout roles, and a quality gate (`analyze_report_quality`) that
_fails_ exactly this shape (`consecutive_plain_charts`, `chart_dump`, `plain_chart_overuse`,
`missing_interactive_explorer`).

None of it ran. The report was emitted as **raw HTML via `build_report`** (a passthrough
with zero gating) — or as repeated `report_add_section(section_type="chart")` at the default
non-blocking `warn` gate. The auto-mapper (`_storyboard_section_from_analysis`) routes a bare
figure → `chart_interpretation`, `records`+`chart` → explorer, `items` → `entity_card_grid`;
the **only** way to get a plain `chart` is to request it explicitly. This single miss
accounts for the loss of layout, insights, chart interpretation, and visual design.

**B. Two genuine renderer gaps, independent of path** _(both closed 2026-07-10 — kept here
as the historical diagnosis; see §1.4 for the shipped mechanism):_
- **Chart theming.** Both chart renderers emitted `Plotly.newPlot(fig.data, fig.layout, …)`
  with the figure untouched — no themed template — so charts fell back to stock Plotly
  colors on a white background and broke in dark mode.
- **Navigation.** The nav was a top sticky _horizontal_ bar (`.r-story-nav`); the desired
  pattern is a persistent **left rail** with scroll-spy.

### 1.3 What is already good (keep it)

The regression is _content routing + chart theming_, not the shell. The new rendering shell is
a genuine step up and must be **preserved**, not reverted: themed metric cards with deltas
(e.g. "+10% vs xG"), the findings list, light/dark theming, and the reading-progress bar. The
fix restores the handcrafted _content_ pipeline on top of this better chrome — it does not throw
the chrome away.

### 1.4 State as of 2026-07-13 (post-overhaul baseline)

Shipped on this branch and covered by the workspace report-builder test suite:

- **Chart theming is render-time, not baked.** All charts route through one themed path
  (`applyChartTheme` + a `renderFigure` registry): token colorway (`--dc-cat-1..8`),
  transparent surfaces, shell typography, axis/legend recolor, and **automatic re-render on
  `data-theme` change**. Baked templates on embedded figures are stripped. This mechanism is
  load-bearing for the rubric: a template injected into `fig.layout` would freeze the theme
  at generation time and defeat the toggle (see A.6 `chart_theme_defeated`).
- **Left rail** ≥1240px — numbered entries, scroll-spy, anchor deep-links from stable
  section ids, collapse to top pills on narrow viewports.
- **Chart grammar**: default-sorted bars, `agg`, `hbar`, `heatmap` (auto-diverging centered
  at 0), `reference_lines`, `annotations`.
- **Storyboard designer**: hero emphasis on the first chart-bearing analysis, phase kickers,
  insight↔evidence anchors + backlinks keyed on shared `finding_id`/`hypothesis_id`/`cell_id`,
  de-templatized readout. **Unrenderable or unknown analyses now raise with the supported-type
  list — nothing is silently dropped.**
- **Component affordances**: evidence chips (typed refs, never dict reprs), status-colored
  insight cards, entity cards with accent borders/count badges/metric bars, metric-tile
  sparklines, numeric table alignment + formatting.
- **Seven runtime bugs fixed**, every one invisible to the metadata gate and caught only by
  rendering: explorer filter wipe, selector cards all hidden (Python/JS key mismatch),
  charts blanking on filter/theme re-render (`innerHTML` vs `Plotly.react` state), evidence
  dict reprs, silent section drops, unthemed dark-mode charts, raw snake_case labels. This
  is the direct motivation for A.6 `runtime_smoke_failed`.

**Current implementation boundary.** `report_design_report` creates a typed storyboard,
applies bounded critique, renders it in one pass, and applies the live rubric gate (default:
`fail`). `report_add_section` remains a draft-oriented incremental path (default: `warn`).
`build_report` preserves its source as a sibling `.source.html`, rebuilds ordinary heading,
prose, and table content into a typed storyboard, and records low extraction confidence instead
of discarding unsupported visual/source content. Evidence targets are embedded with the report;
publish also attempts a browser smoke check and records an explicit `passed`, `failed`, or
`skipped` result.

---

## 2. What "good" means — quality dimensions

The bar is a report a **data scientist would put their name on** and an **analyst would be
proud to have written**. Concretely:

**Visual design & layout**
- Content-type-driven layout (KPI row, 2-col chart+interpretation, card grids, hero chart).
- Deliberate grid, spacing, and visual hierarchy (kicker → headline → dek → body).
- Bespoke components, not generic blocks. Purposeful color. Right information density.

**Insights, description & story flow**
- A stated answer up front; findings as first-class content (claim + evidence + status + caveat).
- A narrative arc across sections (question → answer → evidence → nuance → method); section deks.

**Navigation**
- Left vertical rail with scroll-spy active state; responsive collapse; reading-progress; deep links.

**Chart interpretation**
- Every chart carries a stated conclusion, adjacent to the figure, tied to its evidence,
  with "what to look at" cueing and interactive inspection where it helps.

**Theming**
- On-brand chart palette; charts inherit the surface (transparent bg); dark-mode-correct;
  consistent chart typography; token-driven single source of truth.

**Cross-cutting (implied but essential)**
- Accessibility (WCAG-AA both themes), responsiveness, payload/performance, evidence &
  provenance rigor, export fidelity (`.docx`/print), reproducibility from a stored recipe.

---

## 3. Operating principle

The report builder is not a rendering utility — it is a **dataclaw analyst with a standard**.
It knows its identity and audience, and it ships nothing two internal reviewers wouldn't sign:

- **The Scientist** — would I stake my name on every number and claim? (evidence, uncertainty,
  method, reproducibility)
- **The Storyteller** — would a peer enjoy reading this and leave understanding it? (arc,
  interpretation, hierarchy, design)

**A report is "done" only when it passes both axes.** Enforced at generation (guidance shapes
what is produced) and at output (gates verify it).

Audience implications become concrete rules:
- _Open-source_ → transparency, reproducibility, self-contained portable artifacts, nothing
  asserted without a visible trace.
- _Data-scientist reader_ → show the model, CV score, denominator, uncertainty; never hand-wave.
- _Analyst reader_ → arc, hierarchy, and interpretation are requirements, not polish.

---

## 4. Architecture — seven layers

```
Report-builder charter        (identity, audience, the two-axis rubric)
        ▼
Analysis intake contract      (evidence registry · tables · caveats)
        ▼
Storyboard designer           (narrative arc · section choice · layout)
        ▼
Section renderer              (interpretation · explorers · cards · pills)
        ▼
Design-system shell           (tokens · left rail · themed charts)
        ▼
Dual-axis quality gate        (rigor + narrative · fail closed)
        ▼
Published artifact            (report · storyboard · recipe)

  — The Scientist (rigor) and The Storyteller (craft) sign off on every layer —
```

**L1 · Report-builder charter (new — the "awareness").** One canonical source of the identity
+ two-axis rubric, consumed as (a) skill guidance that shapes generation and (b) a
machine-readable rubric the gates load. **Current:** `report_rubric.yaml` is loaded by the
quality gate; the skill and designer use the same routing standard, while rubric-driven
generation and critique remain target work.

**L2 · Analysis intake contract.** Consumes _completed_ analysis assets only — insights with
evidence ids, aggregate/ranked tables, chart specs, hypothesis dispositions, methodology,
caveats, data-quality notes. Hosts the **evidence registry** (see §6).

**L3 · Storyboard designer.** Produces a _plan_ before any HTML: narrative arc, section-type
selection by asset shape, layout roles, interaction design. Where the Storyteller composes.

**L4 · Section renderer.** The library of typed, bespoke sections with slots for interpretation,
evidence rail, caveat, and content-type layout. The handcrafted quality lives here.

**L5 · Design-system shell.** Presentation system: CSS tokens as single source of truth,
**left-rail nav**, responsiveness, accessibility, and a **themed Plotly template that reads
the same tokens** so charts inherit the surface, use the brand colorway, and recolor in dark
mode. The self-critique loop (§5.3) is not yet implemented.

**L6 · Dual-axis quality gate.** Two axes, **remediation-first then fail-closed** (§5).

**L7 · Published artifact.** The report **plus its storyboard JSON and recipe** — self-contained,
portable, regenerable. Reproducibility is part of the deliverable.

---

## 5. Locked decisions

### 5.1 Persona lives in both the skill and a rubric config
The charter splits into two synchronized forms with one canonical source:
- **`report_rubric` config** (versioned: `plugins/dataclaw-workspace/dataclaw_workspace/report_rubric.yaml`)
  — canonical machine-readable definition of the currently enforceable checks;
  `analyze_report_quality` loads it instead of hard-coding thresholds/severities, and every gate
  result cites the **rubric version** (a report is reproducible against the exact standard it
  was judged by).
- **Skill guidance** — same persona + criteria in prose to shape generation; references the
  rubric so the two cannot drift.

### 5.2 Raw-HTML normalization (live)
`build_report` is a **normalizing entry**, not a raw writer:

```
submit → extract asset graph → design_report_storyboard → render typed sections
       → self-critique → gate → publish   (+ an "upgrade report" of what changed)
```

The current extractor handles existing typed sections plus ordinary title/headings, prose/list
items, and HTML tables; it creates a storyboard, runs critique, and stores the original source
as a sibling `.source.html`. It records a confidence score and uses `preserved_low_confidence`
when unsupported source elements (for example scripts/canvas/SVG) or insufficient prose make a
faithful structural extraction unsafe. This is deliberately conservative: unsupported figures
remain preserved in source rather than being silently dropped or turned into fabricated claims.
An already typed report is copied without re-rendering, so its chart payloads cannot be degraded
while the generated storyboard still supplies the publish record.

> **Consequence to respect:** auto-upgrading _arbitrary raw HTML_ is lossy (figures and
> section metadata recover cleanly; freeform prose layout does not). Design accordingly:
> make **structured assets the canonical submission**, treat raw HTML as best-effort
> extraction, and when extraction confidence is low, **preserve the author's HTML and
> gate-warn** rather than mangle it. This nudges every caller toward the good path.
> Extraction confidence is recorded in the generated storyboard along with a source SHA-256,
> extracted-block/table counts, and unsupported element kinds. Note the A.7 precedence
> guardrail protects structured sections only; it does not cover raw-HTML extraction.

The preserve-and-warn principle is already live on the structured path: the designer
raises with a machine-readable message on unrenderable or unknown analyses rather than
silently dropping them (2026-07-10). Extraction must adopt the same rule.

**Both leak paths get closed, not one.** The regression came through `build_report` _and_
through `report_add_section` at its default non-blocking `warn` gate. `report_add_section`
keeps `warn` as the draft path, but the **publish path re-gates at `fail`**: publishing or
exporting a report that has only ever passed the draft gate re-runs the full rubric first.
A report cannot reach a reader having been judged only by the draft standard.

The re-gate is live at the dedicated `report_publish` boundary. Draft-only reports are re-checked
at `fail` before they can be published; the publish receipt records the rubric result, storyboard,
DOCX export outcome, and runtime-smoke outcome. Rubric v2's live `unstructured_report` fail
criterion prevents non-normalized raw HTML from publishing; `build_report` now creates the
required typed storyboard path.

### 5.3 Self-critique loop (live, bounded)
A bounded loop on the **structured section model** (not the HTML), after render and before the gate:
- Runs on the structured section model (never on rendered HTML), for at most two passes with a
  convergence record in the storyboard.
- Adds missing section context/captions, supplies a safe table caption, and marks an
  evidence-free insight as unverified with a caveat. It normalizes and records the evidence
  registry each pass.
- **Hard rigor guardrail:** may _flag or request_ missing evidence but must **never fabricate**
  a number, citation, or evidence id. A claim without a trace is downgraded to a caveat or
  marked unsourced — never invented.
- **Scoped to what the model can see.** The loop handles section context and evidence presence;
  it does not invent a chart conclusion, provenance, methodology, or a component upgrade when
  the source does not justify one. Contrast and browser behavior remain outside the loop.

### 5.4 Resulting control flow
Two nested, bounded remediation loops feed one gate:
- **Section loop** (critique → renderer): rewrite weak sections in place.
- **Report loop** (gate fail → designer): re-plan the storyboard on structural failures, one pass.
- The gate **fails closed** only when something is _unfixable without fabrication_ — typically
  missing evidence/method. That is the right place to stop and ask the human.

### 5.5 Draft-from-intake, never always-block
For the `remediable: partial` criteria (`missing_methodology`, `missing_primary_insights`,
`missing_insight_sections`), the critique loop **drafts the missing section from existing intake
material** — reshaping methodology notes, hypothesis dispositions, and insights the analysis
already produced into the required section shape. It **blocks only when the intake genuinely
has nothing** to draft from. "Draft" here means reshaping and relocating material that already
exists — never inventing method or findings, consistent with the §5.3 no-fabrication guardrail.

---

## 6. Evidence linking — a first-class graph

Evidence is now validated, resolvable, and rendered through a report-local registry:

- **Registry (L2).** The analysis phase supplies `requirements.evidence_registry.targets` with
  every citable target and typed id:
  `notebook_cell`, `table`, `artifact`, `chart`, `finding`, `filter`. Claims reference targets
  by id, not free text.
- **Resolvability is a rigor-gate check (L6).** The renderer embeds both registry targets and
  section-level references; the v3 gate warns when a ref is absent, wrong-kind, or marked not
  present (stable external targets are allowed). This compatibility release promotes to fail in
  a later version, after callers have supplied registries.
- **Three coordinated views (L4).** The same graph drives inline **evidence chips** on each
  finding (click → source), an **evidence rail** beside interpretation panels, and a
  consolidated **evidence trace** audit section.
- **Bidirectional.** A finding links to its evidence; a chart/table shows which findings cite it.
  (Groundwork shipped: insight cards carry "See the evidence" anchors and evidence sections
  carry backlink chips, keyed on shared provenance ids — the registry formalizes the convention.)
- **Critique guardrail (L5).** May flag an unresolved ref; may never mint an id to satisfy the check.
- **Sequencing.** v1's presence-only `unsourced_claim` remains a live warning. v3 makes
  `evidence_unresolved` live at warning severity; a later rubric version can promote it to
  fail after the registry contract has had one compatibility release.

---

## 7. Findings presentation & component vocabulary

The observed failure is findings rendered as **bare bullet lists**. Make the rich form the
default and the bare form a gate failure.

- **Insight-card is the canonical finding shape:** numbered marker + title + detail + evidence
  chips + confidence/status pill + caveat + optional metric. A findings section that is just
  `<ul><li>` trips a **narrative-axis** warning.
- **Bullets are demoted** to enumerated sub-points _inside_ a card, not the finding container.
- The designer composes findings into an `insight_grid` ordered by decision-impact.

**Component-by-semantics map** (all renderers already exist; the designer/critique must _select_
them). Two tiers — value-level micro-components and **section-level** shapes; the regression was
mostly a section-level failure (ranking as an unsorted chart, composition as six charts,
chronology as prose), so both tiers are required:

_Value level:_

| Data semantics | Component | Renderer fn |
|---|---|---|
| status / category / tier | **pill** | `_render_pill_row` |
| a count | **badge** | `_chip` / entity count badge |
| similarity / % / share / bounded score | **progress bar** | `_metric_bar_pct` (entity metric bars) |
| KPI with a trend series behind it | **sparkline** in the metric tile | `_spark_svg` |
| a set of entities | **cards** | `_render_entity_card` |
| enumerated short attributes | **bullets** (inside a card) | `_render_bullet_list` |
| a citation | **evidence chip** | `_render_evidence_chips` |

_Section level:_

| Data semantics | Section / chart form |
|---|---|
| ranking, superlatives, "top N" | sorted bar / `hbar` (sorted by default in the grammar) |
| composition, parts of a whole per category | stacked bar (`barmode: stack`) |
| two categorical dims × one measure | `heatmap` (auto-diverging centered at 0) |
| claim with a supporting figure | `chart_interpretation` |
| 2–4 named alternatives on shared metrics | `comparison` |
| entity set with comparable metrics | `entity_card_grid`; `selector_panel` when >6 or the reader should choose |
| chronology of decisions / dispositions | `ledger_timeline` |
| slice-and-verify on one aggregate | `chart_table_explorer` |
| lookup / exact values / audit | `interactive_table` |

**Resolution precedence and conservatism:** explicit `section_type` > payload shape >
semantics. A semantic upgrade never overrides explicit author intent, and every upgrade is
recorded in `section_plan[].rationale` so it is auditable. Without this guardrail the
critique loop becomes a machine that mangles intent.

This map lives in the **rubric** (checkable) and is applied by the **critique loop**: a category
value in plain text → pill; a lonely percentage → bar; an entity list → cards. "Uses plain text
where a component is warranted" is a scored narrative-axis criterion.

---

## 8. How the fixes map to concerns

| Concern | Today (post-overhaul) | Architecture |
|---|---|---|
| Identity / standard | implicit | explicit charter + two-axis rubric (L1) |
| Generation path | `report_design_report` and `build_report` are storyboarded; raw source is retained beside normalized output; add-section drafts at `warn` | publish re-gates at `fail` (L6/5.2) |
| Chart interpretation | designer routes figures to `chart_interpretation`; plain chart w/ interpretation gets side panel | narrative gate enforces the conclusion requirement (L6) |
| Insights / findings | insight cards w/ status borders, evidence chips, anchors (designed path); bare bullets still possible via add-section | bare bullets fail (§7) |
| Evidence linking | embedded typed registry + reference graph, anchors/backlinks, and resolver warning (v3) | promote unresolved refs to fail after compatibility window (§6) |
| Rich components (pills/bars/cards/sparks) | **shipped**; designer selects by shape only | semantic map adds tier-3 selection + critique upgrades plain text (§7) |
| Chart theming | **shipped** — render-time token theming, dark-safe, re-render on toggle | rubric guards the mechanism (A.6 `chart_theme_defeated`) |
| Navigation | **shipped** — left rail with scroll-spy, deep links | — |
| Runtime correctness | structural checks on every gate; publish attempts browser smoke and records pass/fail/skip | promote v3 warnings after browser availability is guaranteed |
| Rigor | uneven | evidence/method/reproducibility as gate criteria (L6) |

---

## 9. Open decisions

1. **Rubric visibility in the published report.** Recommendation for an open-source DS audience:
   a **quiet footer** — "Reviewed against report rubric v3 · N/N criteria · storyboard attached" —
   with detailed per-axis scores living in the storyboard JSON, not on the page. Alternatives:
   fully internal, or a fuller on-page scorecard.

2. **Publish/export boundary.** **Resolved:** `report_publish` is the dedicated `fail` re-gate
   and records the publish receipt. Follow-up: move the legacy best-effort `.docx` emission out
   of `build_report` once callers have migrated, and add static fallbacks before promoting
   `export_fidelity`.

3. **Runtime-smoke environment policy.** **Resolved:** publish always runs structural checks and
   attempts Playwright browser checks. Where Node, Playwright, or Chromium is unavailable, the
   receipt records `skipped` as a **warn-level disclosure** — never as a browser pass. Promotion
   to fail awaits an environment that guarantees browser availability.

_Resolved this pass:_
- **`remediable: partial` behavior** is settled — draft from intake, block only when intake is
  empty (§5.5).
- **A.3 thresholds** are no longer guesses; they mirror the live gate
  (`REPORT_QUALITY_MAX_BYTES = 1.5 MB`, `≥3` consecutive plain charts fail, `≥4` plain charts arm
  the dump checks, `≥6` sections with `≥3` charts require an explorer). They stay tunable, but the
  starting point now describes real behavior rather than an aspiration.

---

## 10. Next milestones

The remaining immediate report-builder milestone is **DOCX fidelity**: static fallbacks for
interactive sections, explicit conversion diagnostics on the legacy path, and promotion of
`export_fidelity`. Longer-term work is a learned/vision semantic evaluator that can supplement
the shipped deterministic rendered-page audit. Promote warning criteria only where the relevant
runtime environment is guaranteed.

---

## Appendix A — `report_rubric` v7 (specification and implementation status)

_The versioned config is live at `plugins/dataclaw-workspace/dataclaw_workspace/report_rubric.yaml`.
The gate consumes all `live` criteria. The designer records the live check ids and rubric
version in its storyboard, and the bounded critique record and evidence registry travel with it._

### A.1 Purpose & consumers

One versioned artifact defines "what a good dataclaw report is." Current and target consumers:

- **Generator (skill / designer)** — uses the report-design skill and records the rubric version
  plus live check ids in the storyboard; direct criterion/component-map consumption is target work.
- **Self-critique loop** — live bounded consumer; adds safe context/caveats and records its actions.
- **Quality gate (`analyze_report_quality`)** — live consumer; emits pass/warn/fail and cites
  `rubric_version`.

The live designer, critique loop, and gate record the same rubric version, so the standard is
traceable across how a report is written, remediated, and judged.

### A.2 Axes

| Axis | Reviewer | Question |
|---|---|---|
| `rigor` | The Scientist | Would I stake my name on every number and claim? |
| `narrative` | The Storyteller | Would a peer enjoy this and leave understanding it? |
| `integrity` | both | Is the artifact well-formed, portable, and reproducible? |

### A.3 Criterion schema

```yaml
rubric_version: 7
# Gate thresholds — every value here matches the live gate today
# (report_renderer.py: analyze_report_quality), so the rubric describes real behavior.
thresholds:
  max_payload_bytes: 1_500_000        # = REPORT_QUALITY_MAX_BYTES; measured after stripping the Plotly runtime
  max_consecutive_plain_charts: 2     # a 3rd consecutive plain chart fails
  plain_chart_dump_min: 4             # ≥4 plain charts arms chart_dump / plain_chart_overuse
  explorer_required_min_sections: 6   # ≥6 sections …
  explorer_required_min_charts: 3     # … with ≥3 chart-like sections must include an explorer
  insight_required_min_sections: 4    # ≥4 sections must include a story/insight layer

# Generation & loop knobs — NOT gate values; no criterion asserts them today.
# Headline bounds exist only as designer guidance ("lead with 2-5 numbers");
# either promote them to a headline_metrics_out_of_range criterion or they stay advisory.
designer:
  min_headline_metrics: 2
  max_headline_metrics: 5
critique:
  max_passes: 2

criteria:
  - id: evidence_unresolved
    axis: rigor
    severity: warn                 # v3 compatibility release; promotes per A.10
    status: live
    since_version: 3
    scope: section                 # report | section
    applies_to: [findings, insight_grid, chart_interpretation,
                 hypothesis_ledger, evidence_trace, evidence_rail]
    signal: >
      Every evidence ref on an item dereferences to a registered target
      that is present in the artifact bundle (or a stable external ref).
    remediable: false              # cannot be auto-fixed without fabrication
    on_fail: warn
    remediation: flag_unsourced    # loop downgrades the claim to a caveat
    rationale: An unsourced claim is exactly what the Scientist won't sign.
```

Every criterion carries: `id`, `axis`, `severity` (`fail`|`warn`), `status` (`live`|`deferred`;
`live` = enforced by today's gate at this severity, `deferred` = target standard awaiting
implementation, with `since_version` naming the unlock), `scope`, `applies_to`, `signal`
(what's evaluated), `remediable` (can the critique loop fix it?), `on_fail` (`block`|`warn`),
`remediation` (the loop's action), `rationale`. A criterion that renames a live gate check
also carries `replaces: <live_id>` so the version history stays coherent across the rename.

### A.4 Criteria catalog — Rigor axis

| id | sev | status | remediable | Signal | Critique action |
|---|---|---|---|---|---|
| `evidence_unresolved` | warn (v3) → fail | live | no | every evidence ref resolves to a present, registered target | flag claim as unsourced / caveat |
| `unsourced_claim` | warn (v1) → fail | live | no | every finding/insight carries ≥1 evidence ref | downgrade to caveat; never mint an id |
| `missing_methodology` | fail (v7) | live | partial | a declared rigor contract requires a `methodology_block` with grain, denominator, validation | reshape supplied methodology notes; block only when explicitly required |
| `missing_data_quality` | warn (v7) | live | yes | a declared rigor contract requires visible data-quality / coverage disclosure | render supplied coverage notes as a callout |
| `missing_uncertainty` | warn (v7) | live | partial | declared or predictive rigor requires visible uncertainty | render supplied interval/confidence information; never invent |
| `chart_interpretation_missing_evidence` | warn | live | no | a `chart_interpretation` with a conclusion has ≥1 evidence ref | request evidence; flag if absent |
| `missing_recipe` | warn (v7) | live | yes | a source-bound embedded recipe and `*.recipe.json` sidecar accompany the storyboard | regenerate from the recorded source context, never edited HTML |

`unsourced_claim` is today's `missing_evidence_ids` renamed (`replaces: missing_evidence_ids`).
It enters v1 at its **live severity, `warn`** — encoding it at `fail` in v1 would silently
tighten the gate, exactly what A.10 forbids — and promotes to `fail` in a later version.
These rigor checks are source-declared rather than inferred from prose. Predictive analysis
contracts require uncertainty by default; methodology and data-quality checks require an
explicit `requirements.rigor` flag.

### A.5 Criteria catalog — Narrative axis

| id | sev | status | remediable | Signal | Critique action |
|---|---|---|---|---|---|
| `consecutive_plain_charts` | fail | live | yes | ≤ `max_consecutive_plain_charts` plain charts in a row | convert to `chart_interpretation` / explorer |
| `chart_dump` | fail | live | yes | not dominated by plain charts w/o interpretation or explorer | re-plan via designer |
| `plain_chart_overuse` | fail | live | yes | plain charts ≤ interactive + interpreted charts | upgrade supporting charts |
| `missing_interactive_explorer` | fail | live | yes | ≥3 charts ⇒ ≥1 explorer/selector/filterable/table | add an explorer over an aggregate payload |
| `chart_missing_conclusion` | warn (v3) → fail | live | yes | every chart states what it _shows_, not just axes | request/source a one-line conclusion; never invent one |
| `missing_narrative_answer` | warn | live | yes | a `narrative_band` answers the primary question up front | synthesize the answer from findings |
| `bare_bullet_findings` | warn | live | yes | findings render as insight cards, not plain `<ul><li>` | reshape bullets into insight cards |
| `missing_section_dek` | warn | live | yes | each section opens with a one-line dek | write safe context from the section title |
| `plaintext_where_component_warranted` | warn (v7) | live | yes | a declared semantic role uses its matching component (§A.7) | upgrade the explicit role to its safe component |
| `missing_table_caption` | warn | live | yes | tables have a caption explaining grain/filters | write caption from columns/filters |
| `missing_primary_insights` | fail | live | partial | ≥1 findings/insight-grid carries completed insight items | promote intake insights into an insight-grid; block only if intake has none |
| `missing_insight_sections` | fail | live | partial | ≥4 sections ⇒ ≥1 story layer (findings/insight-grid/narrative/methodology/evidence/explorer) | build a story layer from intake material; block only if intake has none |
| `unpaired_insights` | warn | live (v3) | partial | insights whose provenance ids match an evidence section carry an `evidence_anchor` | re-run pairing; if no analysis shares the ids, flag the insight as evidence-orphaned |

`unpaired_insights` became live in v3: the gate now detects a typed insight that declares
evidence refs but is not anchored to an evidence section.

### A.6 Criteria catalog — Integrity axis

| id | sev | status | remediable | Signal | Critique action |
|---|---|---|---|---|---|
| `unstructured_report` | fail | live (v2) | yes | ≥1 typed `data-dc-section-meta` block is present | migrate/rebuild through the structured storyboard path before publish |
| `oversized_report` | fail | live | partial | payload (excl. Plotly runtime) ≤ `max_payload_bytes` | drop raw/full datasets; sample/aggregate |
| `chart_theme_defeated` | warn (v3) → fail | live | yes | no stored figure carries a baked template/background/font/colorway that defeats token theming and dark-mode re-render | **strip** the baked template / explicit colors from `fig.layout`; render-time theming supplies them |
| `runtime_smoke_failed` | warn (v3) → fail | live | partial | structural smoke always checks shell/anchors/mount points; publish additionally attempts headless render assertions for charts, controls, selector cards, and empty states | re-render after upstream fixes; browser-unavailable is recorded as `skipped`, never passed |
| `visual_semantic_review` | warn (v7) | live | yes | browser audit checks hero/section hierarchy, contextualized evidence, editorial findings, and undeclared nested surfaces | revise the rendered composition and regenerate |
| `visual_author_fallback` | warn (v4) | live | yes | a requested runtime visual author either records a validated plan or declares safe fallback | inspect the runtime provider or use a provided spec |
| `visual_plan_budget` | warn (v4) | live | yes | advisory plan review has no repeated strong surfaces, unclear parent-child nesting, repeated narrative framing, or card grids without peer comparison | revise the plan or accept contextual density explicitly |
| `display_fact_coverage` | warn (v5); explicit contract blocks publish (v6) | live | yes | requested runtime composition has stable source-owned display facts rather than prose inference or legacy display fields; every display-fact evidence ref resolves through the registry | add `display_facts` or explicit `visual_author.facts`, then register its evidence |
| `export_fidelity` | warn | deferred | partial | exports (`.docx`/print) derive from the upgraded report, and every interactive section has a static fallback (sorted table snapshot, chart image, or first-N rows) or the export discloses the omission | generate static fallbacks; disclose what could not be preserved |
| `not_self_contained` | warn | live (v3) | yes | no external script/style/media asset the offline artifact can't load | inline or replace the external ref |
| `contrast_below_aa` | warn | live (v3) | partial | primary ink/muted/surface token pairs meet WCAG-AA in light and dark themes | adjust token colors; v7 stores full-page desktop/mobile and desktop key-section browser artifacts alongside the deterministic token check |
| `stale_installed_skills` | fail | live | no | installed library skills match bundled skill-library | block; refresh skills out-of-band |

v7-status notes: `chart_theme_defeated` evaluates stored figure layout fields; the renderer's
runtime token application remains the source of actual theme styling. `runtime_smoke_failed`
always performs static wiring checks, then attempts Playwright at publish; an unavailable browser
is recorded as `skipped`, never a browser pass. When available, browser smoke records full-page
desktop/mobile and desktop key-section screenshot hashes and checks section, chart, and narrative
clipping. Browser review also performs a deterministic semantic audit of hierarchy, evidence
context, editorial findings, and nested surfaces. `requirements.publication.require_visual_review=true`
requires that audit plus a named approved `report_review_visuals` record bound to the exact HTML and
screenshot hashes. The audit is not a learned vision model. Runtime visual authoring is a constrained fact-selection stage; its model can
select only typed source facts and, when explicitly enabled, reorder only declared contiguous
story blocks inside a named zone. Designed reports embed a source-context/section-plan recipe and
write a hash-bound `*.recipe.json` sidecar. `export_fidelity` remains deferred because the legacy
`.docx` conversion still has no static fallbacks or reliable fidelity accounting.

_Runtime criteria (`runtime_smoke_failed`, `contrast_below_aa`) are evaluated outside the
section-model critique loop (§5.3) — the loop cannot see rendered behavior and must not score it._

### A.7 Component-by-semantics map (declarative)

Read by the designer to _choose_ components and by the critique loop to _upgrade_ plain text.
Resolution precedence is fixed: **explicit `section_type` > payload shape > semantics** — a
semantic upgrade never overrides explicit author intent, and every applied upgrade is logged
in `section_plan[].rationale`.

```yaml
component_map:
  precedence: [explicit_section_type, payload_shape, semantics]
  upgrades:
    never_override_explicit: true
    log_to: section_plan[].rationale

  value_level:
    - when: value_is(status | category | tier)
      use: pill            # _render_pill_row
    - when: value_is(count)
      use: badge           # _chip / entity count badge
    - when: value_is(ratio | percentage | similarity | share | bounded_score)
      use: progress_bar    # _metric_bar_pct (entity metric bars)
    - when: value_is(kpi) and has(trend_series)
      use: sparkline       # _spark_svg, metric tile `spark`
    - when: value_is(entity_set)
      use: cards           # _render_entity_card
    - when: value_is(short_attribute_list) and inside(card)
      use: bullets         # _render_bullet_list
    - when: value_is(citation)
      use: evidence_chip   # _render_evidence_chips

  section_level:
    - when: intent_is(ranking | superlatives | top_n)
      use: sorted_bar      # bar/hbar; grammar sorts by value by default
    - when: intent_is(composition | part_of_whole_by_category)
      use: stacked_bar     # chart barmode: stack
    - when: shape_is(two_categorical_dims x one_measure)
      use: heatmap         # auto-diverging colorscale centered at 0
    - when: has(claim) and has(figure)
      use: chart_interpretation
    - when: shape_is(2..4 named alternatives on shared metrics)
      use: comparison
    - when: shape_is(entity_set with comparable metrics)
      use: entity_card_grid   # selector_panel when >6 or reader should choose
    - when: intent_is(chronology | dispositions_over_time)
      use: ledger_timeline
    - when: intent_is(slice_and_verify one aggregate)
      use: chart_table_explorer
    - when: intent_is(lookup | exact_values | audit)
      use: interactive_table

default_finding_shape: insight_card   # numbered · title · detail · evidence · status pill · caveat · metric
```

### A.8 Evidence resolution rules

```yaml
evidence:
  target_kinds: [notebook_cell, table, artifact, chart, finding, filter]
  ref_shape: { kind: <target_kind>, ref: <registered_id> }
  resolution:
    must_reference_registered_target: true
    must_be_present_in_bundle: true      # or a stable external ref
    render_views: [inline_chip, evidence_rail, evidence_trace]  # same graph, 3 views
    bidirectional: true                  # finding↔evidence backlinks
  guardrail:
    critique_may_flag_missing: true
    critique_may_fabricate_ids: false    # hard rule
```

### A.9 Scoring & gate semantics

- **Applicable criteria** per axis = those whose `applies_to` matches the sections present
  **and** whose `status` is `live` at the rubric version in force — `deferred` criteria are
  never scored, so they cannot fail a report before their mechanism exists.
- **Axis score** = `passed / applicable` (drives the optional footer, §9).
- **Remediation-first:** the critique loop runs up to `critique.max_passes`, re-scoring after each.
- **Gate status after the loop:**
  - `fail` — any `severity: fail` criterion still failing (and, for `remediable: false`, it blocks immediately);
  - `warn` — only warnings remain;
  - `pass` — no failures.
- **Fail-closed only when unfixable without fabrication** — `evidence_unresolved` is a live
  v3 warning while callers adopt the registry; it becomes an appropriate fail-closed condition
  only after promotion. That is the correct point to stop and ask the human.
- Every gate result embeds `rubric_version`, so a report is reproducible against the exact
  standard it was judged by.

### A.10 Versioning

`rubric_version` bumps on any criteria/threshold change. Published reports record the version
they passed; regenerating an old report re-runs it against its recorded version unless
explicitly upgraded. New criteria ship at `severity: warn` for one version before promotion to
`fail`, so tightening the bar never silently breaks existing reports. An exception is a
versioned criterion that closes a material publish-gate bypass: v2's `unstructured_report` is
live at `fail` because a raw document with no typed section metadata cannot be assessed at all;
the migration path and breaking behavior are explicitly documented in §5.2. v3 launches the
registry, chart-theme, runtime-smoke, and contrast evaluators at `warn`; they can only promote
after the documented compatibility window.
