# DataClaw Data Intake & Profiling - PRD & Solution Architecture

| | |
|---|---|
| **Status** | Draft, build-ready |
| **Owner** | Nandini Mathan |
| **Last updated** | 2026-07-07 |
| **Ships as** | `plugins/dataclaw-intake/` |
| **Composes with** | `plugins/dataclaw-data`, `plugins/dataclaw-projects`, `plugins/dataclaw-artifacts`, `skill-library/data_profiling.md`, `skill-library/structured_eda.md` |

---

## Release-note-first framing

DataClaw can now take a raw local file and turn it into a usable analytical dataset: the agent registers the file, fingerprints it, infers schema, profiles quality risks, creates a versioned dataset record, and publishes a compact profile artifact before analysis begins. The human no longer validates raw data from scattered notebook cells; they review one dataset intake card with shape, schema, missingness, duplicates, type warnings, sample rows, and next recommended EDA path.

## Validation gate & degradation rule

- **Golden acceptance check:** upload/register `examples/structured_eda/customer_events_sample.csv`, produce a dataset version id, profile pack, quality flags, and profile artifact; rerun intake after editing the CSV and verify a new version id plus diff; run with a malformed CSV and verify a structured error with no partial registration.
- **Degradation rule:** if profile generation fails, registration can still ship as "registered, unprofiled" with schema/sample only and a required follow-up task. If artifact publishing is unavailable, the profile is returned as a tool result and markdown file, but the dataset version id and profile JSON still persist; the profile does not satisfy artifact evidence or review gates until publishing succeeds.

## Convergence checklist

| Surface | How this PRD uses it |
|---|---|
| Plugin | `plugins/dataclaw-intake/` auto-discovered at startup |
| Tools | `register_dataset_file`, `profile_dataset_version`, `diff_dataset_profiles`, `list_dataset_versions` |
| Hooks | pre-tool session/project context; post-registration plan output attachment |
| Skills | `data_profiling` and `structured_eda` decide profile depth and next path |
| UI | `dataset_registered`, `profile_ready`, `profile_failed` AG-UI events and read-only intake/profile panel |
| Sub-agents | Not applicable |
| OpenClaw | Bridge manifest/allowlist exposes intake tools as canonical names or `dataclaw_...` aliases with identical schemas |
| Validation | golden CSV registration/profile/diff, malformed-file fixture, and OpenClaw alias/manifest check |

---

# Part 1 - Product Requirements

## 1. Problem

DataClaw already has a data plugin that can list, preview, profile, query, and describe registered datasets. The missing product step is the front door: a raw file becomes analyzable only through ad hoc workspace inspection or plugin-specific paths such as Kaggle auto-registration. There is no durable dataset version, no intake profile pack, no profile diff, and no validation card that tells the analyst whether the data is ready for EDA, SQL, modeling, or dashboarding.

## 2. Goals

- **G1** - Register local files as versioned DataClaw datasets through a tool, using project/session scope.
- **G2** - Produce a compact profile pack: schema, shape, sample, missingness, duplicates, type warnings, cardinality, and basic distribution summaries.
- **G3** - Preserve data provenance: source path, content digest, registered dataset id, version id, inferred schema, and registration timestamp.
- **G4** - Emit profile-ready events and profile artifacts so the user can validate data before analysis.
- **G5** - Feed downstream skills/plugins: `structured_eda`, `sql_analyst`, Query Lab, Modeling, and Artifacts all consume the same dataset version id.
- **G6** - Degrade gracefully for messy files: partial parsing is explicit, never silently coerced into "good" data.

## 3. Non-goals

- No remote database connectors. Those remain in `dataclaw-data` or future connector plugins.
- No write-back to source files.
- No full semantic catalog or business glossary.
- No model-readiness verdict beyond profile-level warnings; deeper readiness is `structured_eda` and Modeling.
- No multi-tenant dataset service.

## 4. Users & Use Cases

| # | Use case | What must be true |
|---|---|---|
| U1 | "Use this CSV for the analysis" | Agent registers the file, returns a dataset version id, and shows a profile card |
| U2 | "Did the file change since yesterday?" | The digest and version history show whether content changed |
| U3 | "Can I query it?" | The dataset appears in `data_list_datasets` and works with DuckDB read-only queries |
| U4 | "Is it safe to model on?" | Profile flags identifiers, missingness, constant columns, mixed types, duplicates, and suspicious target columns |
| U5 | "This upload is messy" | Bad rows, encoding failures, delimiter ambiguity, and type conflicts are surfaced with sample evidence |
| U6 | "Profile all files in this folder" | Agent registers/profile batches with per-file status and no all-or-nothing failure |
| U7 | "Compare this revised extract to the old one" | Profile diff highlights row/column/schema/missingness/cardinality changes |
| U8 | "Start an EDA plan" | The plan can reference the dataset version id and profile artifact |
| U9 | Poisoned filename or path traversal | Root checks prevent reading outside allowed project/workspace roots |

## 5. Functional Requirements

### 5.1 Registration

- **FR-1** `register_dataset_file(path, name?, description?, project_id?, session_id?, options?)` registers one local file from allowed roots and returns `{dataset_id, version_id, profile_id, status}`.
- **FR-2** Supported P1 formats: CSV, TSV, JSONL, Parquet, Excel first sheet. Unsupported formats fail with a typed reason.
- **FR-3** Every registration computes `sha256`, byte size, row estimate, column count, parser options, and source path.
- **FR-4** Same dataset name + same digest short-circuits to the existing version.
- **FR-5** Same dataset name + new digest creates a new version, never mutates the old profile.
- **FR-6** Batch registration returns per-file successes and failures; one bad file does not block the rest.

### 5.2 Profiling

- **FR-7** `profile_dataset_version(dataset_id, version_id?, depth="quick"|"standard")` produces a profile pack.
- **FR-8** Profile pack includes shape, schema, nullable counts, missingness percentages, duplicate row count, numeric summaries, categorical top values, datetime ranges, high-cardinality warnings, constant columns, mixed-type warnings, and capped sample rows.
- **FR-9** Profile pack labels candidate identifiers, candidate measures, candidate timestamps, and candidate target columns as hints, not facts.
- **FR-10** Large files profile via DuckDB sampling plus exact cheap stats; the profile clearly marks sampled vs exact values.
- **FR-11** `diff_dataset_profiles(dataset_id, from_version, to_version)` returns row/column/schema/profile changes.

### 5.3 Surfaces & events

- **FR-12** On success, emit `dataset_registered` and `profile_ready` AG-UI events.
- **FR-13** Tool result renders an intake card: dataset id, version id, shape, warnings, capped sample, and "suggested next skill".
- **FR-14** If `dataclaw-artifacts` is installed, publish a profile artifact with the same dataset/version ids.
- **FR-15** If a plan is active, attach the dataset version id and profile artifact to the current `plan_step_id` outputs.
- **FR-16** `list_dataset_versions(dataset_id)` returns version metadata and latest profile status.

### 5.4 Safety & validation

- **FR-17** All paths use `Path.resolve()` and `Path.is_relative_to()` against project/workspace roots.
- **FR-18** Parser errors include row/column samples where safe, capped and redacted for binary/control characters.
- **FR-19** The tool never prints source data beyond the shared preview cap: default 20 rows and 50 KB per rendered card/section.
- **FR-20** Profile output is deterministic for the same file/options.

## 6. Non-functional Requirements

- **NFR-1 Security** - no path traversal, no remote fetch, no execution of file content, no formula execution from Excel.
- **NFR-2 Durability** - version/profile writes are tmp -> fsync -> atomic rename; profile corruption is surfaced.
- **NFR-3 Performance** - quick profile target <10s for files up to 100 MB on a laptop; standard profile can run longer but streams progress.
- **NFR-4 Privacy** - samples are capped by the shared preview policy; profile artifacts avoid raw row dumps.
- **NFR-5 Compatibility** - registered datasets must appear through existing `dataclaw-data` list/preview/query tools.

## 7. Phasing & Exit Criteria

| Phase | Scope | Exit test |
|---|---|---|
| P1 - Register and quick profile | Plugin skeleton, tools, store, CSV/TSV/Parquet, path safety, quick profile, AG-UI card | Golden CSV registers, profiles, queries through `dataclaw-data`; generated OpenClaw manifest/allowlist exposes intake tools with identical canonical/alias schemas |
| P2 - Versions and diffs | Version history, digest dedup, profile diff, batch registration | Edited file produces v2 and profile diff |
| P3 - Profile artifact | Artifact publish integration, plan output attachment, suggested next skill | Profile artifact appears inline and in library |
| P4 - Format hardening | Excel/JSONL, parser option inference, large-file sampled profiling, progress events | Messy fixtures fail or degrade with typed reasons |

## 8. Success Metrics

- 95% of local CSV/Parquet test fixtures register without manual code.
- Every registered dataset has a version id and profile id before downstream plan execution.
- Profile warning precision improves human validation speed: analyst can decide "ready for EDA/query/model" from the card/artifact.
- No downstream PRD uses raw file paths as the durable data identity once intake is available.

---

# Part 2 - Solution Architecture

## 1. System Context

`dataclaw-intake` extends, not replaces, `dataclaw-data`. Intake owns file registration, versioning, and profile packs. `dataclaw-data` remains the query/preview surface over registered datasets.

| Piece | Reused for |
|---|---|
| `dataclaw/plugins/base.py` | plugin registration |
| `plugins/dataclaw-data` | dataset registry/query/preview integration |
| `plugins/dataclaw-projects` | project directory scope |
| `plugins/dataclaw-artifacts` | profile artifact publishing when installed |
| `skill-library/data_profiling.md` | quick profile behavior |
| `skill-library/structured_eda.md` | next-step EDA when profile flags warrant deeper analysis |

## 2. Flow

```
AUTHOR      user points at file/folder
             -> register_dataset_file(path, options)
INTAKE      resolve root, fingerprint, infer parser, parse sample
PROFILE     compute quick/standard profile pack
STORE       datasets/<dataset_id>/versions/<version_id>/{meta.json, profile.json}
INTEGRATE   register with dataclaw-data registry
SURFACE     dataset_registered/profile_ready events -> intake card/profile artifact
DOWNSTREAM  Query Lab, Modeling, Artifacts consume dataset_id + version_id
```

## 3. Key Decisions

| ID | Decision | Why | Rejected alternative |
|---|---|---|---|
| D1 | Dataset identity is versioned by content digest | Analysts need to know whether results are tied to the same extract | Mutable "latest file" path |
| D2 | Intake extends `dataclaw-data` | Query tools and OpenClaw bridge already work there | Forking a second data registry |
| D3 | Profile packs are persisted JSON | Enables diffs, artifacts, and living-report capture | Profile only as chat text |
| D4 | Hints, not semantic truth | Identifier/target detection can be wrong | Automatically declaring business meaning |
| D5 | Sampled stats are labeled | Large files need fast feedback without false certainty | Pretending sample stats are exact |

## 4. Plugin Layout

```
plugins/dataclaw-intake/
  dataclaw_intake/
    __init__.py       # register tools, router, hooks
    tools.py          # register/profile/diff/list versions
    store.py          # atomic version/profile storage
    parsers.py        # csv/tsv/jsonl/parquet/xlsx parsing
    profiler.py       # profile pack computation
    data_bridge.py    # update dataclaw-data registry
    router.py         # dataset version/profile endpoints
    hooks.py          # plan/session context injection
  tests/
```

## 5. Tool Contract

```python
register_dataset_file(path, name=None, description="", project_id=None,
                      session_id="default", options=None)
# -> {dataset_id, version_id, profile_id, status, warnings, profile_summary}

profile_dataset_version(dataset_id, version_id=None, depth="quick")
# -> {profile_id, dataset_id, version_id, exactness, warnings, summary}

diff_dataset_profiles(dataset_id, from_version, to_version)
# -> {row_delta, column_changes, schema_changes, warning_changes}

list_dataset_versions(dataset_id)
# -> [{version_id, sha256, rows, columns, created_at, profile_status}]
```

## 6. Storage Layout

```
workspaces_dir()/intake/
  datasets/
    ds-customer-events/
      meta.json
      versions/
        v-20260707-9c1f/
          source.json       # path, digest, parser options, byte size
          schema.json
          profile.json
          sample.json       # capped sample rows
```

The source file is not copied in P1 unless it already lives outside a stable project root and the user requests import/copy. Metadata always stores the original path and digest.

## 7. Safety Model

| Threat | Scenario | Mitigation |
|---|---|---|
| Path traversal | User/agent passes `../../secrets.csv` or prefix-spoofed root | `Path.resolve()` and `Path.is_relative_to()` against project/workspace roots |
| Spreadsheet execution | Excel file contains formulas or external links | parse values only; never execute formulas/macros or follow external links |
| Sensitive sample leak | Profile artifact includes too many raw rows | capped samples, no raw dumps, configurable sample byte limit |
| Silent parser coercion | Bad rows become nulls without notice | typed parser warnings and malformed-row samples |
| Duplicate dataset identity | Same file registered under multiple ids | digest dedup and name/version policy |

## 8. Events & UI

- `dataset_registered`: opens/refreshes the Data panel entry.
- `profile_ready`: renders an intake card in chat and optionally a profile artifact.
- `profile_failed`: renders a typed failure with suggested parser options.

Right panel reads profile/version history. Chat/tool calls perform register, reprofile, diff, and promote actions.

## 9. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Large files make profiling slow | sampled quick profile, progress events, standard profile opt-in |
| Wrong parser inference | structured parser errors and retry options |
| False semantic hints | label as candidates; require EDA/modeling confirmation |
| Duplicate registries | data_bridge tests prove `dataclaw-data` sees registered versions |
| Sensitive samples in artifacts | capped samples, no raw dumps, redaction of control/binary content |
