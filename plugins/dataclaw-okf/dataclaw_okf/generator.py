"""Generate OKF v0.1-style markdown bundles from Dataclaw datasets."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import duckdb

from dataclaw_data.registry import find_dataset

from dataclaw_okf.registry import (
    bundles_root,
    find_bundle_for_dataset,
    new_bundle_id,
    now_iso,
    slugify,
    upsert_bundle,
)


OKF_GENERATOR_VERSION = 4
OKF_VERSION = "0.1"
MISSING_LIKE_TOKENS = ("", "na", "n/a", "null", "none", "nan")


def dataset_fingerprint(dataset: dict[str, Any]) -> str:
    relevant = {
        "okf_generator_version": OKF_GENERATOR_VERSION,
        "id": dataset.get("id"),
        "name": dataset.get("name"),
        "type": dataset.get("type"),
        "connection": dataset.get("connection"),
        "description": dataset.get("description"),
        "definition": dataset.get("definition"),
        "tables": dataset.get("tables", []),
        "table_definitions": dataset.get("table_definitions", {}),
        "column_definitions": dataset.get("column_definitions", {}),
        "updated_at": dataset.get("updated_at"),
    }
    payload = json.dumps(relevant, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def generate_bundle(dataset_id: str, *, force: bool = False) -> dict[str, Any]:
    dataset = find_dataset(dataset_id)
    source_hash = dataset_fingerprint(dataset)
    existing = find_bundle_for_dataset(dataset_id)

    if existing and existing.get("source_hash") == source_hash and Path(existing.get("path", "")).exists() and not force:
        return {**existing, "status": "unchanged", "stale": False}

    bundle_id = existing.get("id") if existing else new_bundle_id(str(dataset.get("name") or dataset_id))
    bundle_dir = bundles_root() / bundle_id
    catalog_dir = bundle_dir / "catalog"
    if catalog_dir.exists():
        shutil.rmtree(catalog_dir)
    catalog_dir.mkdir(parents=True, exist_ok=True)

    files = _write_catalog(catalog_dir, dataset)
    created_at = existing.get("created_at") if existing else now_iso()
    bundle = {
        "id": bundle_id,
        "dataset_id": dataset_id,
        "dataset_name": dataset.get("name", dataset_id),
        "path": str(catalog_dir),
        "created_at": created_at,
        "updated_at": now_iso(),
        "source_hash": source_hash,
        "file_count": len(files),
        "files": files,
        "format": "okf-v0.1-markdown",
    }
    upsert_bundle(bundle)
    return {**bundle, "status": "generated", "stale": False}


def is_bundle_stale(bundle: dict[str, Any]) -> bool:
    try:
        dataset = find_dataset(str(bundle.get("dataset_id", "")))
    except ValueError:
        return True
    return bundle.get("source_hash") != dataset_fingerprint(dataset)


def _write_catalog(root: Path, dataset: dict[str, Any]) -> list[str]:
    files: list[str] = []
    table_defs = dataset.get("table_definitions") or {}
    column_defs = dataset.get("column_definitions") or {}

    def write(rel: str, text: str) -> None:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text.rstrip() + "\n", encoding="utf-8")
        files.append(rel)

    dataset_slug = slugify(str(dataset.get("name") or dataset.get("id") or "dataset"))
    tables = dataset.get("tables") or []
    write("index.md", _index_markdown(dataset, dataset_slug))
    write("log.md", _log_markdown(dataset))
    write("datasets/index.md", _directory_index("Datasets", [(str(dataset.get("name", dataset.get("id"))), f"{dataset_slug}.md", _dataset_description(dataset))]))
    write(f"datasets/{dataset_slug}.md", _dataset_markdown(dataset))
    write("tables/index.md", _directory_index("Tables", _table_index_entries(tables)))
    write("columns/index.md", _directory_index("Column Documentation", _table_index_entries(tables)))
    write("quality/index.md", _directory_index("Quality Notes", _table_index_entries(tables)))
    write("notes/index.md", _directory_index("Notes", [("Analysis notes", "analysis_notes.md", "Curated findings, assumptions, methodology decisions, and open questions.")]))
    write("notes/analysis_notes.md", _analysis_notes_markdown(dataset))

    for table in tables:
        table_key = _table_key(table)
        table_slug = slugify(table_key)
        write(
            f"tables/{table_slug}.md",
            _table_markdown(dataset, table, table_defs.get(table_key) or table_defs.get(table.get("name", ""))),
        )
        write(
            f"columns/{table_slug}.md",
            _columns_markdown(dataset, table, column_defs.get(table_key) or column_defs.get(table.get("name", "")) or {}),
        )
        write(f"quality/{table_slug}.md", _quality_markdown(dataset, table, _profile_table(dataset, table)))

    return sorted(files)


def _frontmatter(**values: Any) -> str:
    lines = ["---"]
    for key, value in values.items():
        if value is None:
            continue
        if isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {json.dumps(item)}")
        else:
            lines.append(f"{key}: {json.dumps(value)}")
    lines.append("---")
    return "\n".join(lines)


def _index_markdown(dataset: dict[str, Any], dataset_slug: str) -> str:
    tables = dataset.get("tables") or []
    table_links = "\n".join(
        f"* [{_table_key(t)}](tables/{slugify(_table_key(t))}.md) - {t.get('rows', 0)} rows, {t.get('columns', 0)} columns."
        for t in tables
    ) or "* No tables were introspected."
    return f"""{_frontmatter(okf_version=OKF_VERSION)}

# {dataset.get("name", dataset.get("id"))}

This Open Knowledge Format bundle captures portable, agent-readable context for a Dataclaw dataset.

## Dataset

* [Dataset card](datasets/{dataset_slug}.md) - {_dataset_description(dataset)}
* [Dataset directory](datasets/) - Dataset-level concepts.

## Tables

{table_links}

## Bundle Directories

* [Tables](tables/) - Table-level concepts and schema context.
* [Column documentation](columns/) - Column definitions grouped by table.
* [Quality notes](quality/) - Lightweight profiling and quality signals.
* [Notes](notes/) - Open questions and analysis notes.

## Notes

* [Analysis notes](notes/analysis_notes.md) - Curated findings, assumptions, methodology decisions, and open questions.
* [Update log](log.md) - Bundle generation history.
"""


def _directory_index(title: str, entries: list[tuple[str, str, str]]) -> str:
    body = "\n".join(
        f"* [{entry_title}]({href}) - {description}"
        for entry_title, href, description in entries
    )
    if not body:
        body = "* No concepts have been generated in this directory yet."
    return f"""# {title}

{body}
"""


def _log_markdown(dataset: dict[str, Any]) -> str:
    today = now_iso().split("T", 1)[0]
    dataset_slug = slugify(str(dataset.get("name") or dataset.get("id") or "dataset"))
    return f"""# Bundle Update Log

## {today}

* **Generation**: Created OKF {OKF_VERSION} bundle for [dataset {dataset.get("name", dataset.get("id"))}](/datasets/{dataset_slug}.md).
* **Profiling**: Generated lightweight table-level quality notes where the source could be queried with DuckDB.
"""


def _table_index_entries(tables: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    return [
        (
            _table_key(table),
            f"{slugify(_table_key(table))}.md",
            f"{table.get('rows', 0)} rows, {table.get('columns', 0)} columns.",
        )
        for table in tables
    ]


def _dataset_description(dataset: dict[str, Any]) -> str:
    return _one_line(str(dataset.get("description") or "No description has been provided."))


def _one_line(value: str) -> str:
    text = " ".join(str(value).split())
    return text[:240] + "..." if len(text) > 240 else text


def _dataset_markdown(dataset: dict[str, Any]) -> str:
    description = _dataset_description(dataset)
    definition = dataset.get("definition") or "No extended dataset definition has been provided."
    dataset_slug = slugify(str(dataset.get("name") or dataset.get("id") or "dataset"))
    return f"""{_frontmatter(type="Dataclaw Dataset", title=str(dataset.get("name", dataset.get("id"))), description=description, resource=_dataset_resource(dataset), tags=["dataclaw", "dataset", str(dataset.get("type", "unknown"))], timestamp=dataset.get("updated_at") or dataset.get("created_at") or now_iso(), dataset_id=dataset.get("id"), source_type=dataset.get("type"), status=dataset.get("status"))}

# Dataset Card: {dataset.get("name", dataset.get("id"))}

{description}

# Definition

{definition}

# Source

- Type: `{dataset.get("type", "")}`
- Connection: `{dataset.get("connection", "")}`
- Status: `{dataset.get("status", "")}`
- Created: `{dataset.get("created_at", "")}`
- Updated: `{dataset.get("updated_at", "")}`

# Tables

{_table_summary(dataset.get("tables") or [])}

# Bundle Relationships

- This dataset concept is listed from the [root bundle index](/index.md).
- Table concepts are listed in the [tables directory](/tables/).
- Column documentation is listed in the [columns directory](/columns/).
- Quality notes are listed in the [quality directory](/quality/).

# Citations

[1] [Dataclaw dataset registry entry](/datasets/{dataset_slug}.md)
"""


def _table_markdown(dataset: dict[str, Any], table: dict[str, Any], definition: str | None) -> str:
    table_key = _table_key(table)
    table_slug = slugify(table_key)
    dataset_slug = slugify(str(dataset.get("name") or dataset.get("id") or "dataset"))
    body = definition or "No table definition has been provided."
    description = _one_line(body)
    return f"""{_frontmatter(type="Dataclaw Table", title=table_key, description=description, resource=_table_resource(dataset, table), tags=["dataclaw", "table", str(dataset.get("type", "unknown"))], timestamp=dataset.get("updated_at") or now_iso(), dataset_id=dataset.get("id"), table=table_key)}

# Table: {table_key}

Part of the [dataset](/datasets/{dataset_slug}.md). Column documentation lives in [columns/{table_slug}.md](/columns/{table_slug}.md), and quality notes live in [quality/{table_slug}.md](/quality/{table_slug}.md).

# Meaning

{body}

# Shape

- Rows: `{table.get("rows", 0)}`
- Columns: `{table.get("columns", 0)}`
- File type: `{table.get("file_type", "")}`
- Path: `{table.get("path", "")}`

# Schema

{_column_summary(table.get("column_details") or [])}

# Citations

[1] {_source_citation(dataset, table)}
"""


def _columns_markdown(dataset: dict[str, Any], table: dict[str, Any], definitions: dict[str, str]) -> str:
    table_key = _table_key(table)
    table_slug = slugify(table_key)
    rows = []
    for col in table.get("column_details") or []:
        name = str(col.get("name", ""))
        ctype = str(col.get("type", "unknown"))
        meaning = definitions.get(name) or "No column definition has been provided."
        rows.append(f"| `{_md_cell(name)}` | `{_md_cell(ctype)}` | {_md_cell(meaning)} |")
    table_md = "\n".join(rows) if rows else "| _none_ | _none_ | No column details were introspected. |"
    description = f"Column definitions and inferred data types for {table_key}."
    return f"""{_frontmatter(type="Dataclaw Column Schema", title=f"Columns for {table_key}", description=description, resource=f"dataclaw://datasets/{dataset.get('id')}/tables/{table_slug}/columns", tags=["dataclaw", "columns", "schema"], timestamp=dataset.get("updated_at") or now_iso(), dataset_id=dataset.get("id"), table=table_key)}

# Columns: {table_key}

This schema concept describes columns for [the table](/tables/{table_slug}.md).

# Schema

| Column | Type | Definition |
| --- | --- | --- |
{table_md}

# Citations

[1] {_source_citation(dataset, table)}
"""


def _quality_markdown(dataset: dict[str, Any], table: dict[str, Any], profile: dict[str, Any]) -> str:
    table_key = _table_key(table)
    profile_error = profile.get("error")
    if profile_error:
        profile_body = f"""Profiling could not be completed for this table.

- Error: `{profile_error}`

The structural metadata below is still available, but richer quality signals should be generated after the source can be queried successfully."""
    else:
        profile_body = f"""## Profile Summary

- Rows profiled: `{profile.get("row_count", 0)}`
- Columns profiled: `{profile.get("column_count", 0)}`
- Duplicate rows: `{profile.get("duplicate_rows", "not_computed")}`
- Duplicate check: {profile.get("duplicate_note", "exact")}

## Quality Flags

{_quality_flags_markdown(profile.get("flags", []))}

## Column Quality

{_column_quality_markdown(profile.get("columns", []))}

## Numeric Signals

{_numeric_quality_markdown(profile.get("columns", []))}
"""
    table_slug = slugify(table_key)
    return f"""{_frontmatter(type="Dataclaw Data Quality Notes", title=f"Quality notes for {table_key}", description=f"Lightweight profiling and quality signals for {table_key}.", resource=f"dataclaw://datasets/{dataset.get('id')}/tables/{table_slug}/quality", tags=["dataclaw", "quality", "profiling"], timestamp=dataset.get("updated_at") or now_iso(), dataset_id=dataset.get("id"), table=table_key)}

# Quality Notes: {table_key}

This OKF concept is generated from Dataclaw's dataset introspection and lightweight DuckDB profiling for [the table](/tables/{table_slug}.md). Treat these as initial quality signals, then refine them with deeper notebook analysis when the project needs it.

{profile_body}

# Current Structural Signals

- Rows: `{table.get("rows", 0)}`
- Columns: `{table.get("columns", 0)}`
- Introspection source: `{table.get("path") or dataset.get("connection", "")}`

# Citations

[1] {_source_citation(dataset, table)}
"""


def _analysis_notes_markdown(dataset: dict[str, Any]) -> str:
    dataset_slug = slugify(str(dataset.get("name") or dataset.get("id") or "dataset"))
    return f"""{_frontmatter(type="Analysis Notes", title=f"Analysis notes for {dataset.get('name', dataset.get('id'))}", description="Open questions, assumptions, methodology decisions, and modeling caveats for this dataset.", resource=f"dataclaw://datasets/{dataset.get('id')}/analysis-notes", tags=["dataclaw", "analysis", "notes"], timestamp=now_iso(), dataset_id=dataset.get("id"))}

# Analysis Notes

Use this file for curated findings, assumptions, methodology decisions, modeling caveats, and external research notes about [the dataset](/datasets/{dataset_slug}.md).

# Open Questions

- What is the primary analytical objective?
- Are there target variables, leakage-prone fields, or time ordering constraints?
- Which quality issues should be reviewed before modeling?
"""


def _table_key(table: dict[str, Any]) -> str:
    schema = table.get("schema")
    name = table.get("name", "")
    return f"{schema}.{name}" if schema else str(name)


def _dataset_resource(dataset: dict[str, Any]) -> str:
    source = str(dataset.get("connection") or "")
    return _source_uri(source) or f"dataclaw://datasets/{dataset.get('id')}"


def _table_resource(dataset: dict[str, Any], table: dict[str, Any]) -> str:
    path = str(table.get("path") or "")
    if path:
        return _source_uri(path) or f"dataclaw://datasets/{dataset.get('id')}/tables/{slugify(_table_key(table))}"
    if dataset.get("type") == "duckdb":
        return f"duckdb://{dataset.get('connection', '')}#{_table_key(table)}"
    return f"dataclaw://datasets/{dataset.get('id')}/tables/{slugify(_table_key(table))}"


def _source_uri(value: str) -> str | None:
    if not value:
        return None
    if "://" in value:
        return value
    path = Path(value)
    if path.is_absolute():
        try:
            return path.as_uri()
        except ValueError:
            return None
    return None


def _source_citation(dataset: dict[str, Any], table: dict[str, Any] | None = None) -> str:
    resource = _table_resource(dataset, table) if table else _dataset_resource(dataset)
    return f"[Source resource]({resource})"


def _md_cell(value: Any) -> str:
    return str(value).replace("\n", " ").replace("|", "\\|")


def _table_summary(tables: list[dict[str, Any]]) -> str:
    if not tables:
        return "No tables were introspected."
    lines = ["| Table | Rows | Columns |", "| --- | ---: | ---: |"]
    for table in tables:
        table_key = _table_key(table)
        lines.append(f"| [`{_md_cell(table_key)}`](/tables/{slugify(table_key)}.md) | {table.get('rows', 0)} | {table.get('columns', 0)} |")
    return "\n".join(lines)


def _column_summary(columns: list[dict[str, Any]]) -> str:
    if not columns:
        return "No columns were introspected."
    lines = ["| Column | Type |", "| --- | --- |"]
    for column in columns:
        lines.append(f"| `{_md_cell(column.get('name', ''))}` | `{_md_cell(column.get('type', 'unknown'))}` |")
    return "\n".join(lines)


def _profile_table(dataset: dict[str, Any], table: dict[str, Any]) -> dict[str, Any]:
    """Build a bounded quality profile for one table.

    The profile is intentionally lightweight enough for bundle generation. It
    computes exact column-level null/unique counts, numeric summary stats, and
    exact duplicate rows only below a row threshold to avoid surprising delays
    on large Kaggle datasets.
    """
    conn = _connect(dataset)
    try:
        relation = _relation_for_table(dataset, table)
        row_count = int(conn.execute(f"SELECT count(*) FROM {relation}").fetchone()[0])
        columns = table.get("column_details") or _describe_columns(conn, relation)
        duplicate_rows: int | str = "not_computed"
        duplicate_note = "skipped for tables above 200000 rows"
        if row_count <= 200_000:
            distinct_rows = int(conn.execute(f"SELECT count(*) FROM (SELECT DISTINCT * FROM {relation})").fetchone()[0])
            duplicate_rows = max(0, row_count - distinct_rows)
            duplicate_note = "exact"

        profiled_columns = []
        flags = []
        for column in columns:
            name = str(column.get("name", ""))
            ctype = str(column.get("type", "unknown"))
            quoted = _quote(name)
            stats = conn.execute(
                f"""
                SELECT
                    count(*) - count({quoted}) AS nulls,
                    count(DISTINCT {quoted}) AS uniques,
                    sum(CASE WHEN lower(trim(coalesce(cast({quoted} AS VARCHAR), ''))) IN ({_missing_token_sql()}) THEN 1 ELSE 0 END) AS missing_like
                FROM {relation}
                """
            ).fetchone()
            null_count = int(stats[0] or 0)
            unique_count = int(stats[1] or 0)
            missing_like_count = int(stats[2] or 0)
            null_rate = (null_count / row_count) if row_count else 0
            missing_like_rate = (missing_like_count / row_count) if row_count else 0
            entry: dict[str, Any] = {
                "name": name,
                "type": ctype,
                "null_count": null_count,
                "null_rate": null_rate,
                "missing_like_count": missing_like_count,
                "missing_like_rate": missing_like_rate,
                "unique_count": unique_count,
                "unique_rate": (unique_count / row_count) if row_count else 0,
            }
            numeric = _numeric_profile(conn, relation, name)
            if numeric:
                entry["numeric"] = numeric
            coercion = _numeric_coercion_profile(conn, relation, name, ctype)
            if coercion:
                entry["numeric_coercion"] = coercion
            profiled_columns.append(entry)
            flags.extend(_flags_for_column(entry, row_count))

        if duplicate_rows not in ("not_computed", 0):
            flags.append(f"{duplicate_rows} duplicate rows detected.")

        return {
            "row_count": row_count,
            "column_count": len(profiled_columns),
            "duplicate_rows": duplicate_rows,
            "duplicate_note": duplicate_note,
            "columns": profiled_columns,
            "flags": flags,
        }
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        conn.close()


def _connect(dataset: dict[str, Any]) -> duckdb.DuckDBPyConnection:
    if dataset.get("type") == "duckdb":
        return duckdb.connect(dataset.get("connection", ":memory:"), read_only=True)
    return duckdb.connect()


def _relation_for_table(dataset: dict[str, Any], table: dict[str, Any]) -> str:
    if dataset.get("type") == "duckdb":
        schema = table.get("schema")
        name = table.get("name")
        rel = _quote(str(name))
        return f"{_quote(str(schema))}.{rel}" if schema else rel

    path = table.get("path") or dataset.get("connection", "")
    file_type = table.get("file_type") or _guess_file_type(path)
    if file_type == "csv":
        return f"read_csv_auto('{_sql_str(path)}')"
    if file_type == "parquet":
        return f"read_parquet('{_sql_str(path)}')"
    raise ValueError(f"Unsupported source for OKF profiling: {table.get('name')}")


def _describe_columns(conn: duckdb.DuckDBPyConnection, relation: str) -> list[dict[str, str]]:
    desc = conn.execute(f"SELECT * FROM {relation} LIMIT 0").description
    return [{"name": str(col[0]), "type": str(col[1]) if len(col) > 1 else "unknown"} for col in desc]


def _numeric_profile(conn: duckdb.DuckDBPyConnection, relation: str, column_name: str) -> dict[str, Any] | None:
    quoted = _quote(column_name)
    try:
        row = conn.execute(
            f"""
            SELECT
                min({quoted})::DOUBLE,
                max({quoted})::DOUBLE,
                avg({quoted})::DOUBLE,
                stddev_samp({quoted})::DOUBLE,
                quantile_cont({quoted}, 0.25)::DOUBLE,
                quantile_cont({quoted}, 0.5)::DOUBLE,
                quantile_cont({quoted}, 0.75)::DOUBLE
            FROM {relation}
            """
        ).fetchone()
    except Exception:
        return None
    if row is None or row[0] is None:
        return None
    q1 = row[4]
    q3 = row[6]
    iqr = (q3 - q1) if q1 is not None and q3 is not None else None
    return {
        "min": _serialize(row[0]),
        "max": _serialize(row[1]),
        "mean": _serialize(row[2]),
        "std": _serialize(row[3]),
        "q1": _serialize(q1),
        "median": _serialize(row[5]),
        "q3": _serialize(q3),
        "iqr": _serialize(iqr),
    }


def _flags_for_column(column: dict[str, Any], row_count: int) -> list[str]:
    name = column["name"]
    flags: list[str] = []
    null_rate = column.get("null_rate", 0)
    missing_like_rate = column.get("missing_like_rate", 0)
    unique_count = column.get("unique_count", 0)
    unique_rate = column.get("unique_rate", 0)
    if null_rate >= 0.5:
        flags.append(f"`{name}` has high missingness ({null_rate:.1%}).")
    elif null_rate >= 0.2:
        flags.append(f"`{name}` has moderate missingness ({null_rate:.1%}).")
    if row_count > 0 and unique_count == 1:
        flags.append(f"`{name}` is constant.")
    if row_count >= 20 and unique_rate >= 0.95:
        flags.append(f"`{name}` is near-unique and may be an identifier.")
    if missing_like_rate >= 0.2:
        flags.append(f"`{name}` contains many missing-like tokens such as blanks/NA/null ({missing_like_rate:.1%}).")
    elif missing_like_rate > 0:
        flags.append(f"`{name}` contains missing-like tokens such as blanks/NA/null ({missing_like_rate:.1%}).")
    coercion = column.get("numeric_coercion")
    if coercion and coercion.get("castable_rate", 0) >= 0.8:
        flags.append(
            f"`{name}` is stored as text but {coercion['castable_rate']:.1%} of non-missing-like values can be cast to numbers."
        )
    return flags


def _quality_flags_markdown(flags: list[str]) -> str:
    if not flags:
        return "- No automatic quality flags were detected."
    return "\n".join(f"- {flag}" for flag in flags)


def _column_quality_markdown(columns: list[dict[str, Any]]) -> str:
    if not columns:
        return "No column quality details were computed."
    lines = [
        "| Column | Type | SQL Nulls | Null Rate | Missing-Like Tokens | Missing-Like Rate | Unique Values | Unique Rate |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for column in columns:
        lines.append(
            f"| `{column['name']}` | `{column['type']}` | {column['null_count']} | {column['null_rate']:.1%} | {column['missing_like_count']} | {column['missing_like_rate']:.1%} | {column['unique_count']} | {column['unique_rate']:.1%} |"
        )
    return "\n".join(lines)


def _numeric_quality_markdown(columns: list[dict[str, Any]]) -> str:
    numeric_columns = [c for c in columns if c.get("numeric")]
    if not numeric_columns:
        return "No numeric summary statistics were computed."
    lines = [
        "| Column | Min | Q1 | Median | Mean | Q3 | Max | Std |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for column in numeric_columns:
        stats = column["numeric"]
        lines.append(
            f"| `{column['name']}` | {_fmt(stats.get('min'))} | {_fmt(stats.get('q1'))} | {_fmt(stats.get('median'))} | {_fmt(stats.get('mean'))} | {_fmt(stats.get('q3'))} | {_fmt(stats.get('max'))} | {_fmt(stats.get('std'))} |"
        )
    return "\n".join(lines)


def _guess_file_type(path: str) -> str | None:
    suffix = Path(path).suffix.lower()
    return {".csv": "csv", ".parquet": "parquet"}.get(suffix)


def _quote(name: str) -> str:
    return f'"{str(name).replace(chr(34), chr(34) + chr(34))}"'


def _sql_str(value: str) -> str:
    return str(value).replace("'", "''")


def _serialize(value: Any) -> Any:
    if value is None or isinstance(value, (int, float, str, bool)):
        return value
    return str(value)


def _fmt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)


def _numeric_coercion_profile(
    conn: duckdb.DuckDBPyConnection,
    relation: str,
    column_name: str,
    column_type: str,
) -> dict[str, Any] | None:
    if "CHAR" not in column_type.upper() and "VARCHAR" not in column_type.upper() and "TEXT" not in column_type.upper():
        return None
    quoted = _quote(column_name)
    try:
        row = conn.execute(
            f"""
            SELECT
                sum(CASE WHEN lower(trim(coalesce(cast({quoted} AS VARCHAR), ''))) NOT IN ({_missing_token_sql()}) THEN 1 ELSE 0 END) AS non_missing_like,
                sum(CASE WHEN lower(trim(coalesce(cast({quoted} AS VARCHAR), ''))) NOT IN ({_missing_token_sql()})
                    AND try_cast({quoted} AS DOUBLE) IS NOT NULL THEN 1 ELSE 0 END) AS numeric_castable
            FROM {relation}
            """
        ).fetchone()
    except Exception:
        return None
    non_missing = int(row[0] or 0)
    castable = int(row[1] or 0)
    if non_missing == 0:
        return None
    castable_rate = castable / non_missing
    if castable_rate < 0.8:
        return None
    return {
        "non_missing_like": non_missing,
        "numeric_castable": castable,
        "castable_rate": castable_rate,
    }


def _missing_token_sql() -> str:
    return ", ".join(f"'{_sql_str(token)}'" for token in MISSING_LIKE_TOKENS)
