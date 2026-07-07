# DataClaw Query Lab - PRD & Solution Architecture

| | |
|---|---|
| **Status** | Draft, build-ready |
| **Owner** | Nandini Mathan |
| **Last updated** | 2026-07-07 |
| **Ships as** | `plugins/dataclaw-query-lab/` |
| **Composes with** | `plugins/dataclaw-data`, `plugins/dataclaw-intake`, `plugins/dataclaw-artifacts`, `skill-library/sql_analyst.md`, `skill-library/structured_eda.md` |

---

## Release-note-first framing

DataClaw can now answer data questions with durable query evidence. The agent does not just run SQL and paste a table; it creates a query card with the user question, dataset version, SQL, result preview, assumptions, checks, and interpretation. Every query can be rerun, revised, cited in a report, or reviewed before the human trusts the answer.

## Validation gate & degradation rule

- **Golden acceptance check:** on the customer events sample dataset, answer "Which channel has the highest repeat purchase rate?", save the query card, rerun it, revise the metric definition, and verify the living report links to the final card and the superseded card.
- **Degradation rule:** if result-card persistence fails, the SQL can still run through `dataclaw-data`, and the canonical SQL/result preview should be saved where possible, but the answer must be labeled "uncaptured query result" and cannot satisfy a `plan_step_id`, artifact evidence, review, or human-validation requirement.

## Convergence checklist

| Surface | How this PRD uses it |
|---|---|
| Plugin | `plugins/dataclaw-query-lab/` auto-discovered at startup |
| Tools | `create_query_card`, `run_query_card`, `revise_query_card`, `validate_query_card`, `read_query_card`, `list_query_cards` |
| Hooks | active plan context injection; postToolCall capture for raw `data_query_data` calls |
| Skills | `sql_analyst` drives SQL behavior; `structured_eda` escalates suspicious results |
| UI | `query_card_created`, `query_card_updated`, `query_card_warning` events and read-only Query Lab panel |
| Sub-agents | Not applicable |
| OpenClaw | Bridge manifest/allowlist exposes Query Lab tools as canonical names or `dataclaw_...` aliases with identical schemas |
| Validation | golden repeat-purchase query card with revision, living-report link, and OpenClaw alias/manifest check |

---

# Part 1 - Product Requirements

## 1. Problem

`dataclaw-data` already supports read-only DuckDB queries, and `sql_analyst` guides SQL behavior. What is missing is the product object around a query: a durable question, SQL text, dataset version, result preview, validation checks, and interpretation. Without that object, analysis answers evaporate into the transcript and cannot be cited by artifacts, reviewed, rerun, or compared after a dataset changes.

## 2. Goals

- **G1** - Turn data questions into durable query cards with provenance and interpretation.
- **G2** - Keep all SQL execution inside existing read-only `dataclaw-data` tools.
- **G3** - Make query results citeable from artifacts and living reports.
- **G4** - Support revision: same question/card, new SQL version, preserved history.
- **G5** - Add lightweight validation checks so the human reviews fewer obvious mistakes.
- **G6** - Keep the right panel read-only: query cards are browsed on the right, created/revised in chat.

## 3. Non-goals

- No write SQL, DDL, or materialized database mutations.
- No universal semantic layer or metrics store in P1.
- No natural-language query engine separate from the agent/tool loop.
- No dashboard layout; Query Lab produces evidence cards consumed by Artifacts/Dashboarding.
- No multi-user query collaboration.

## 4. Users & Use Cases

| # | Use case | What must be true |
|---|---|---|
| U1 | "How many active customers did we have last month?" | Query card stores question, SQL, dataset version, result, and interpretation |
| U2 | "Use purchases, not sessions, as the denominator" | Same card gets a new revision; old SQL/result remains visible |
| U3 | "Can I trust this answer?" | Card shows row counts, null checks, denominator definition, and caveats |
| U4 | "Put this result in the report" | Artifact section deep-links to the query card/result |
| U5 | "Rerun after I updated the file" | Rerun shows dataset version changed and flags non-comparable results |
| U6 | "Show me all queries for the EDA step" | Right panel filters cards by plan step and dataset |
| U7 | "This query is slow" | Query plan/timing is captured and surfaced |
| U8 | "Which SQL produced that chart?" | Chart/artifact provenance links back to the query card |
| U9 | Prompt injection tries to run destructive SQL | Read-only SQL validator rejects non-SELECT/WITH/SHOW before execution |

## 5. Functional Requirements

### 5.1 Query cards

- **FR-1** `create_query_card(question, dataset_id, version_id?, sql, title?, assumptions?)` creates a durable card without executing.
- **FR-2** `run_query_card(card_id, base_revision?, limit=1000)` executes through `dataclaw-data` and stores result metadata.
- **FR-3** `revise_query_card(card_id, sql?, question?, assumptions?, base_revision?)` creates a new revision using compare-and-set semantics.
- **FR-4** Each card revision stores SQL, dataset id/version id, execution timestamp, row count, column schema, timing, capped result preview, result digest, and `plan_step_id` when available.
- **FR-5** Identical SQL + dataset version + options short-circuits to the existing revision.

### 5.2 Validation

- **FR-6** SQL validator accepts only read-only DuckDB queries: SELECT, WITH, SHOW, DESCRIBE/EXPLAIN where supported.
- **FR-7** Validation flags missing LIMIT during exploration, ambiguous `count(*)` denominators, joins without key cardinality checks, date filters without timezone/grain notes, and percent metrics without numerator/denominator labels.
- **FR-8** Agent can call `validate_query_card(card_id)` to get machine-readable warnings before presenting the answer.
- **FR-9** Query cards can mark warnings as accepted with a rationale, but warnings are never hidden.

### 5.3 Surfaces

- **FR-10** On execution, emit `query_card_updated` AG-UI event.
- **FR-11** Tool result renders an inline query result card with SQL collapsed by default, capped result preview, checks, and interpretation.
- **FR-12** Right panel Query Lab tab lists cards by session, dataset, `plan_step_id`, status, and latest/superseded.
- **FR-13** Query cards expose stable anchors for artifacts/living report links.
- **FR-14** `list_query_cards(dataset_id?, plan_step_id?, status?)` and `read_query_card(card_id, revision?)` support review/reuse.

### 5.4 Integration

- **FR-15** Active plan context hook injects `session_id`, `proposal_id`, and `plan_step_id` when available.
- **FR-16** `postToolCallHook` captures successful `data_query_data` calls and can offer to promote them into query cards.
- **FR-17** If `dataclaw-artifacts` is installed, query cards can become typed table/metric sections.
- **FR-18** If dataset version is unknown, the card is allowed but marked "unversioned data" and cannot satisfy the golden validation gate.

## 6. Non-functional Requirements

- **NFR-1 Security** - query execution stays in `dataclaw-data`; Query Lab never opens a broader database connection.
- **NFR-2 Durability** - append-only revisions; atomic writes; corruption is surfaced.
- **NFR-3 Performance** - previews are capped; full result export is a separate explicit action.
- **NFR-4 Reproducibility** - every executed result stores enough metadata to rerun or explain why rerun is not comparable.
- **NFR-5 Privacy** - result previews obey the shared 20-row/50-KB cap and are not blindly embedded into artifacts.

## 7. Phasing & Exit Criteria

| Phase | Scope | Exit test |
|---|---|---|
| P1 - Query cards | store, create/run/read/list tools, read-only validation, inline renderer | Golden question creates and reruns a card; generated OpenClaw manifest/allowlist exposes Query Lab tools with identical canonical/alias schemas |
| P2 - Revision and checks | CAS revisions, validation warnings, plan step attribution | Denominator change preserves old and new cards |
| P3 - Artifact/living report integration | stable anchors, typed sections, `postToolCallHook` capture | Report links to the final query card |
| P4 - Query review ergonomics | right panel filters, explain/timing display, card search | Analyst can find all queries for a plan step |

## 8. Success Metrics

- 100% of final SQL-backed claims in artifacts link to a query card.
- Query revisions preserve history and do not overwrite prior result evidence.
- Human review catches fewer denominator/join/grain mistakes because the card surfaces them early.
- No destructive SQL executes through Query Lab.

---

# Part 2 - Solution Architecture

## 1. System Context

Query Lab is a provenance layer over `dataclaw-data`, not a second SQL engine.

| Piece | Role |
|---|---|
| `plugins/dataclaw-data` | execute read-only SQL and list/preview datasets |
| `plugins/dataclaw-intake` | provide dataset version ids and profile context |
| `plugins/dataclaw-plans` | provide active plan ids and `plan_step_id` |
| `plugins/dataclaw-artifacts` | consume query cards as evidence sections |
| `skill-library/sql_analyst.md` | query behavior and validation prompts |

## 2. Flow

```
AUTHOR    agent drafts SQL from user question + dataset profile
CARD      create_query_card(question, dataset_version, sql)
VALIDATE  read-only SQL + metric/join/grain checks
RUN       execute via dataclaw-data query tool
STORE     append revision with result schema/preview/digest
SURFACE   query_card_updated event -> inline card + Query Lab panel
REPORT    artifacts/living report deep-link to card anchors
```

## 3. Key Decisions

| ID | Decision | Why | Rejected alternative |
|---|---|---|---|
| D1 | Query card is the durable object | A result needs question, SQL, data version, checks, and interpretation together | Loose SQL/result in transcript |
| D2 | Execute only through `dataclaw-data` | Keeps one read-only SQL enforcement surface | A second DuckDB connector |
| D3 | Revisions are append-only | Query changes are analytical decisions | Updating a card in place |
| D4 | Validation warnings are visible | Humans need caveat bandwidth focused, not hidden | Auto-fixing or suppressing warnings |
| D5 | Cards feed artifacts as typed sections | Query evidence should be citeable | Copy/paste tables into reports |

## 4. Plugin Layout

```
plugins/dataclaw-query-lab/
  dataclaw_query_lab/
    __init__.py       # tools, router, hooks
    tools.py          # create/run/revise/read/list/validate
    store.py          # append-only cards and revisions
    validator.py      # SQL policy and analytical warning checks
    data_bridge.py    # execute via dataclaw-data
    sections.py       # convert cards to artifact sections
    router.py         # card endpoints
    hooks.py          # active plan context + data_query_data capture
  tests/
ui/src/components/
  QueryLabPanel.tsx
  tool-renderers/QueryCardRenderer.tsx
```

## 5. Tool Contract

```python
create_query_card(question, dataset_id, sql, version_id=None,
                  title="", assumptions=None)
# -> {card_id, revision, status, warnings}

run_query_card(card_id, base_revision=None, limit=1000)
# -> {card_id, revision, result_preview, row_count, result_digest, warnings}

revise_query_card(card_id, sql=None, question=None, assumptions=None,
                  base_revision=None)
# -> {card_id, revision, conflict?}

validate_query_card(card_id, revision=None)
# -> {status, warnings: [{code, severity, message, evidence}]}

read_query_card(card_id, revision=None)
list_query_cards(dataset_id=None, plan_step_id=None, status=None)
```

## 6. Storage Layout

```
workspaces_dir()/query-lab/
  cards/
    qry-repeat-purchase-rate/
      meta.json
      revisions.jsonl
      results/
        rev-003-preview.json
```

`revisions.jsonl` is append-only. Full result materialization is not P1; previews are capped.

## 7. Safety Model

| Threat | Scenario | Mitigation |
|---|---|---|
| Destructive SQL | Prompt-injected data asks the agent to run DROP/DELETE/ATTACH | Query Lab validator plus `dataclaw-data` read-only enforcement |
| Data overexposure | Result preview embeds sensitive rows into artifacts | preview caps; artifact sections must aggregate or explicitly opt into table preview |
| False denominator | Agent reports a rate with hidden numerator/denominator mismatch | validation warning for percent metrics without labels/checks |
| Join explosion | Many-to-many join inflates metric | join cardinality warning and row-count checks |
| Stale result | Dataset changes but result is reused | dataset version id and rerun comparability warning |

## 8. Events & UI

- `query_card_created`
- `query_card_updated`
- `query_card_warning`

Inline card shows latest result for that revision. Right panel lists cards, revisions, warnings, and plan-step filters. All edits happen through chat/tool calls.

## 9. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Agent treats query result as truth despite warning | warnings visible in card and living report |
| Duplicate SQL execution path | data_bridge tests assert execution uses `dataclaw-data` |
| Result previews leak too much data | row/byte caps and artifact section aggregation rules |
| Dataset changed under a card | dataset version id + rerun comparability warning |
| SQL validator misses edge cases | defense in depth: `dataclaw-data` remains read-only enforcement |
