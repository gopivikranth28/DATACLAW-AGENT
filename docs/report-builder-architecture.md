# Dataclaw Report Builder — Findings & Solution Architecture

_Consolidated design note. Branch: `structured-eda`. Scope: why report visual/analytical
quality regressed, what "good" means for a dataclaw report, and the architecture to
guarantee it. No code changes proposed here — this is the design of record._

_Refreshed 2026-07-10 against the renderer overhaul on this branch: the two L5 gaps named
in §1.2.B (chart theming, left-rail nav) have since shipped, along with seven runtime bug
fixes and the component affordances in §1.4. The rubric in Appendix A describes the
post-overhaul baseline._

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

### 1.4 State as of 2026-07-10 (post-overhaul baseline)

Shipped on this branch, verified by 53 plugin tests plus headless light/dark/mobile
screenshots, simulated filter interaction, and a runtime theme-flip:

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
machine-readable rubric the gates load. One definition, two enforcement points, no drift.

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
mode. Also hosts the self-critique loop (§5.3).

**L6 · Dual-axis quality gate.** Two axes, **remediation-first then fail-closed** (§5).

**L7 · Published artifact.** The report **plus its storyboard JSON and recipe** — self-contained,
portable, regenerable. Reproducibility is part of the deliverable.

---

## 5. Locked decisions

### 5.1 Persona lives in both the skill and a rubric config
The charter splits into two synchronized forms with one canonical source:
- **`report_rubric` config** (versioned, e.g. `report_rubric.yaml`) — canonical machine-readable
  definition of both axes; `analyze_report_quality` loads it instead of hard-coding checks;
  every gate result cites the **rubric version** (a report is reproducible against the exact
  standard it was judged by).
- **Skill guidance** — same persona + criteria in prose to shape generation; references the
  rubric so the two cannot drift.

### 5.2 `build_report` auto-upgrades (does not reject)
`build_report` becomes a **normalizing entry**, not a raw writer:

```
submit → extract asset graph → design_report_storyboard → render typed sections
       → self-critique → gate → publish   (+ an "upgrade report" of what changed)
```

It pulls figures, tables, headings, and any author-written interpretation out of the
submission, hands them to the designer, and reconstructs proper `chart_interpretation` /
explorer / `insight_grid` sections — preserving author titles, order, and interpretation text.
A chart-dump gets **repaired**, not rejected. (`build_report` today also emits a best-effort
`.docx` alongside the HTML; that export must flow from the _upgraded_ report, not the raw input.)

> **Consequence to respect:** auto-upgrading _arbitrary raw HTML_ is lossy (figures and
> section metadata recover cleanly; freeform prose layout does not). Design accordingly:
> make **structured assets the canonical submission**, treat raw HTML as best-effort
> extraction, and when extraction confidence is low, **preserve the author's HTML and
> gate-warn** rather than mangle it. This nudges every caller toward the good path.

The preserve-and-warn principle is already live on the structured path: the designer
raises with a machine-readable message on unrenderable or unknown analyses rather than
silently dropping them (2026-07-10). Extraction must adopt the same rule.

**Both leak paths get closed, not one.** The regression came through `build_report` _and_
through `report_add_section` at its default non-blocking `warn` gate. `report_add_section`
keeps `warn` as the draft path, but the **publish path re-gates at `fail`**: publishing or
exporting a report that has only ever passed the draft gate re-runs the full rubric first.
A report cannot reach a reader having been judged only by the draft standard.

### 5.3 Self-critique loop (in scope)
A bounded loop on the **structured section model** (not the HTML), after render and before the gate:
- Scores each section on both axes; regenerates just the sub-bar sections (add a stated
  conclusion to a chart, add a missing dek, pair a lonely table, tighten hierarchy, upgrade
  plain text to the right component).
- **Bounded** (≤2 passes) with a convergence check.
- **Hard rigor guardrail:** may _flag or request_ missing evidence but must **never fabricate**
  a number, citation, or evidence id. A claim without a trace is downgraded to a caveat or
  marked unsourced — never invented.
- **Scoped to what the model can see.** The loop scores only model-checkable criteria
  (deks, conclusions, bare bullets, component choice, evidence presence). Render-dependent
  criteria — contrast, density, hierarchy-as-seen, and all runtime behavior — are owned by
  the smoke check and screenshot self-check (A.6), not the loop. The loop must not claim
  scores it cannot measure from the section model.

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

Today "evidence" is a string that may point at nothing. It must become validated, resolvable,
and _rendered_:

- **Registry (L2).** The analysis phase registers every citable target with a typed id:
  `notebook_cell`, `table`, `artifact`, `chart`, `finding`, `filter`. Claims reference targets
  by id, not free text.
- **Resolvability is a rigor-gate check (L6).** Every ref must dereference to a registered
  target actually present in the artifact bundle (or a stable external ref). A dangling id
  **fails closed** — stricter than today's presence-only `missing_evidence_ids`.
- **Three coordinated views (L4).** The same graph drives inline **evidence chips** on each
  finding (click → source), an **evidence rail** beside interpretation panels, and a
  consolidated **evidence trace** audit section.
- **Bidirectional.** A finding links to its evidence; a chart/table shows which findings cite it.
  (Groundwork shipped: insight cards carry "See the evidence" anchors and evidence sections
  carry backlink chips, keyed on shared provenance ids — the registry formalizes the convention.)
- **Critique guardrail (L5).** May flag an unresolved ref; may never mint an id to satisfy the check.
- **Sequencing.** `evidence_unresolved` cannot fail-closed before the registry exists. Two
  steps, each a rubric version: presence-only checks (today's behavior) → full resolvability
  once L2's registry lands. The version history records which standard each report passed.

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
| Generation path | raw HTML slips through; add-section drafts at `warn` | single gated path; `build_report` auto-upgrades; publish re-gates at `fail` (L6/5.2) |
| Chart interpretation | designer routes figures to `chart_interpretation`; plain chart w/ interpretation gets side panel | narrative gate enforces the conclusion requirement (L6) |
| Insights / findings | insight cards w/ status borders, evidence chips, anchors (designed path); bare bullets still possible via add-section | bare bullets fail (§7) |
| Evidence linking | typed refs + anchors/backlinks by convention | validated resolvable graph, 3 views (§6) |
| Rich components (pills/bars/cards/sparks) | **shipped**; designer selects by shape only | semantic map adds tier-3 selection + critique upgrades plain text (§7) |
| Chart theming | **shipped** — render-time token theming, dark-safe, re-render on toggle | rubric guards the mechanism (A.6 `chart_theme_defeated`) |
| Navigation | **shipped** — left rail with scroll-spy, deep links | — |
| Runtime correctness | verified manually via headless screenshots | `runtime_smoke_failed` gate criterion (A.6) |
| Rigor | uneven | evidence/method/reproducibility as gate criteria (L6) |

---

## 9. Open decisions

1. **Rubric visibility in the published report.** Recommendation for an open-source DS audience:
   a **quiet footer** — "Reviewed against report rubric v1 · N/N criteria · storyboard attached" —
   with detailed per-axis scores living in the storyboard JSON, not on the page. Alternatives:
   fully internal, or a fuller on-page scorecard.

_Resolved this pass:_
- **`remediable: partial` behavior** is settled — draft from intake, block only when intake is
  empty (§5.5).
- **A.3 thresholds** are no longer guesses; they mirror the live gate
  (`REPORT_QUALITY_MAX_BYTES = 1.5 MB`, `≥3` consecutive plain charts fail, `≥4` plain charts arm
  the dump checks, `≥6` sections with `≥3` charts require an explorer). They stay tunable, but the
  starting point now describes real behavior rather than an aspiration.

---

## 10. Next step

The **`report_rubric` spec** is the keystone — evidence resolvability, finding presentation,
and the component-semantics map are all just entries in it, read by the generator, the critique
loop, and the gate alike. It is drafted in **Appendix A** below. Turning it into a versioned
config file + wiring `analyze_report_quality` to load it is the first code step whenever we
start building.

---

## Appendix A — `report_rubric` v1 (specification)

_Spec only. Illustrative config shape; not wired to code yet._

### A.1 Purpose & consumers

One versioned artifact defines "what a good dataclaw report is." Three consumers read it:

- **Generator (skill / designer)** — reads criteria as _instructions_ to produce compliant sections.
- **Self-critique loop** — reads criteria as _scores_ and applies the listed remediation to sub-bar sections.
- **Quality gate (`analyze_report_quality`)** — reads criteria as _assertions_; emits pass/warn/fail and cites `rubric_version`.

Because all three read the same file, "rigor" and "craft" cannot drift between how a report is
written, critiqued, and judged.

### A.2 Axes

| Axis | Reviewer | Question |
|---|---|---|
| `rigor` | The Scientist | Would I stake my name on every number and claim? |
| `narrative` | The Storyteller | Would a peer enjoy this and leave understanding it? |
| `integrity` | both | Is the artifact well-formed, portable, and reproducible? |

### A.3 Criterion schema

```yaml
rubric_version: 1
# report-level knobs the criteria reference — values match the live gate today
# (report_renderer.py: analyze_report_quality) so the rubric describes real behavior.
thresholds:
  max_payload_bytes: 1_500_000        # = REPORT_QUALITY_MAX_BYTES; measured after stripping the Plotly runtime
  max_consecutive_plain_charts: 2     # a 3rd consecutive plain chart fails
  plain_chart_dump_min: 4             # ≥4 plain charts arms chart_dump / plain_chart_overuse
  explorer_required_min_sections: 6   # ≥6 sections …
  explorer_required_min_charts: 3     # … with ≥3 chart-like sections must include an explorer
  insight_required_min_sections: 4    # ≥4 sections must include a story/insight layer
  min_headline_metrics: 2
  max_headline_metrics: 5
  critique_max_passes: 2

criteria:
  - id: evidence_unresolved
    axis: rigor
    severity: fail
    scope: section                 # report | section
    applies_to: [findings, insight_grid, chart_interpretation,
                 hypothesis_ledger, evidence_trace, evidence_rail]
    signal: >
      Every evidence ref on an item dereferences to a registered target
      that is present in the artifact bundle (or a stable external ref).
    remediable: false              # cannot be auto-fixed without fabrication
    on_fail: block
    remediation: flag_unsourced    # loop downgrades the claim to a caveat
    rationale: An unsourced claim is exactly what the Scientist won't sign.
```

Every criterion carries: `id`, `axis`, `severity` (`fail`|`warn`), `scope`, `applies_to`,
`signal` (what's evaluated), `remediable` (can the critique loop fix it?), `on_fail`
(`block`|`warn`), `remediation` (the loop's action), `rationale`.

### A.4 Criteria catalog — Rigor axis

| id | sev | remediable | Signal | Critique action |
|---|---|---|---|---|
| `evidence_unresolved` | fail | no | every evidence ref resolves to a present, registered target | flag claim as unsourced / caveat |
| `unsourced_claim` | fail | no | every finding/insight carries ≥1 evidence ref | downgrade to caveat; never mint an id |
| `missing_methodology` | fail | partial | a `methodology_block` states grain, denominator, validation | reshape intake methodology notes into the block; block only if intake has none |
| `missing_data_quality` | warn | yes | data-quality / coverage risk is disclosed | synthesize from intake notes |
| `missing_uncertainty` | warn | partial | quantitative headline claims show CI / confidence / n where applicable | annotate from source stats; never invent |
| `chart_interpretation_missing_evidence` | warn | no | a `chart_interpretation` with a conclusion has ≥1 evidence ref | request evidence; flag if absent |
| `missing_recipe` | warn | yes | storyboard JSON + regeneration recipe is attached | attach the storyboard used to render |

### A.5 Criteria catalog — Narrative axis

| id | sev | remediable | Signal | Critique action |
|---|---|---|---|---|
| `consecutive_plain_charts` | fail | yes | ≤ `max_consecutive_plain_charts` plain charts in a row | convert to `chart_interpretation` / explorer |
| `chart_dump` | fail | yes | not dominated by plain charts w/o interpretation or explorer | re-plan via designer |
| `plain_chart_overuse` | fail | yes | plain charts ≤ interactive + interpreted charts | upgrade supporting charts |
| `missing_interactive_explorer` | fail | yes | ≥3 charts ⇒ ≥1 explorer/selector/filterable/table | add an explorer over an aggregate payload |
| `chart_missing_conclusion` | fail | yes | every chart states what it _shows_, not just axes | generate a one-line conclusion from the data |
| `missing_narrative_answer` | warn | yes | a `narrative_band` answers the primary question up front | synthesize the answer from findings |
| `bare_bullet_findings` | warn | yes | findings render as insight cards, not plain `<ul><li>` | reshape bullets into insight cards |
| `missing_section_dek` | warn | yes | each section opens with a one-line dek | write a dek from section content |
| `plaintext_where_component_warranted` | warn | yes | categorical/%/entity values use the right component (§A.7) | upgrade plain text per the semantics map |
| `missing_table_caption` | warn | yes | tables have a caption explaining grain/filters | write caption from columns/filters |
| `missing_primary_insights` | fail | partial | ≥1 findings/insight-grid carries completed insight items | promote intake insights into an insight-grid; block only if intake has none |
| `missing_insight_sections` | fail | partial | ≥4 sections ⇒ ≥1 story layer (findings/insight-grid/narrative/methodology/evidence/explorer) | build a story layer from intake material; block only if intake has none |
| `unpaired_insights` | warn | partial | insights whose provenance ids match an evidence section carry an `evidence_anchor` | re-run pairing; if no analysis shares the ids, flag the insight as evidence-orphaned |

### A.6 Criteria catalog — Integrity axis

| id | sev | remediable | Signal | Critique action |
|---|---|---|---|---|
| `oversized_report` | fail | partial | payload (excl. Plotly runtime) ≤ `max_payload_bytes` | drop raw/full datasets; sample/aggregate |
| `chart_theme_defeated` | fail | yes | every chart renders through the themed pipeline; no figure carries a baked template or hard-coded paper/plot background, font color, or colorway that defeats token theming and dark-mode re-render | **strip** the baked template / explicit colors from `fig.layout` — render-time theming supplies them. (Theming is applied at render, never injected into the stored figure: a baked template freezes the theme at generation time and breaks the toggle. Replaces the earlier `charts_untemplated` framing, which prescribed the rejected mechanism.) |
| `runtime_smoke_failed` | fail | partial | headless render of the artifact passes behavioral assertions: every `.r-chart-target` mounted a plot; sections declaring `filters`/`controls` materialized them; selector cards visible; anchor `href`s resolve; no unexpected `.r-empty-state` | re-render after upstream fixes; block if assertions still fail. _Motivation: all seven 2026-07-10 bugs were invisible to metadata checks and caught only by rendering (§1.4)._ |
| `export_fidelity` | warn | partial | exports (`.docx`/print) derive from the upgraded report, and every interactive section has a static fallback (sorted table snapshot, chart image, or first-N rows) or the export discloses the omission | generate static fallbacks; disclose what could not be preserved |
| `not_self_contained` | warn | yes | no external asset the CSP/offline artifact can't load | inline or replace the external ref |
| `contrast_below_aa` | warn | partial | text/mark contrast ≥ WCAG-AA in both themes | adjust to token colors that pass |
| `stale_installed_skills` | fail | no | installed library skills match bundled skill-library | block; refresh skills out-of-band |

_Runtime criteria (`runtime_smoke_failed`, `contrast_below_aa`) are evaluated by the smoke
check / screenshot pass, not the section-model critique loop (§5.3) — the loop cannot see
rendered behavior and must not score it._

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

- **Applicable criteria** per axis = those whose `applies_to` matches the sections present.
- **Axis score** = `passed / applicable` (drives the optional footer, §9).
- **Remediation-first:** the critique loop runs up to `critique_max_passes`, re-scoring after each.
- **Gate status after the loop:**
  - `fail` — any `severity: fail` criterion still failing (and, for `remediable: false`, it blocks immediately);
  - `warn` — only warnings remain;
  - `pass` — no failures.
- **Fail-closed only when unfixable without fabrication** — typically `evidence_unresolved` /
  `unsourced_claim`. That is the correct point to stop and ask the human.
- Every gate result embeds `rubric_version`, so a report is reproducible against the exact
  standard it was judged by.

### A.10 Versioning

`rubric_version` bumps on any criteria/threshold change. Published reports record the version
they passed; regenerating an old report re-runs it against its recorded version unless
explicitly upgraded. New criteria ship at `severity: warn` for one version before promotion to
`fail`, so tightening the bar never silently breaks existing reports.
