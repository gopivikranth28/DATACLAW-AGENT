"""Data tools — dataset listing, profiling, querying via DuckDB."""

from __future__ import annotations

import re
from typing import Any

import duckdb

from dataclaw_data.registry import read_datasets, find_dataset


MAX_QUERY_ROWS = 500

# Module-level dataset filter — set by preToolCallHook before each agent turn.
# None means "all datasets", a list means "only these IDs".
_allowed_dataset_ids: list[str] | None = None


def set_allowed_dataset_ids(ids: list[str] | None) -> None:
    """Set the allowed dataset filter for the current request."""
    global _allowed_dataset_ids
    _allowed_dataset_ids = ids


def _filtered_datasets() -> list[dict[str, Any]]:
    """Return datasets filtered by the current allowlist."""
    all_ds = read_datasets()
    if _allowed_dataset_ids is None:
        return all_ds
    allowed = set(_allowed_dataset_ids)
    return [ds for ds in all_ds if ds.get("id") in allowed]


def _check_dataset_allowed(dataset_id: str) -> None:
    """Raise if the dataset is not in the current allowlist."""
    if _allowed_dataset_ids is not None and dataset_id not in set(_allowed_dataset_ids):
        raise ValueError(f"Dataset '{dataset_id}' is not enabled for this session")


# ── Tools ───────────────────────────────────────────────────────────────────


async def data_list_datasets(**kwargs: Any) -> dict[str, Any]:
    """List all registered datasets with table and column metadata."""
    datasets = [_dataset_summary(ds) for ds in _filtered_datasets()]

    # Build notebook usage hint with a concrete example if tables exist
    notebook_usage = (
        "To load a dataset as a DataFrame in a notebook cell, use:\n"
        "  import dataclaw_data\n"
        "  df = dataclaw_data.get_dataframe('<dataset_id>', table_name='<query_name>')\n"
        "Or with a SQL query:\n"
        "  df = dataclaw_data.get_dataframe('<dataset_id>', sql='SELECT * FROM <query_name>')\n"
        "IMPORTANT: Use the query_name (not the display name) for table_name and SQL queries."
    )
    for ds in datasets:
        if ds.get("tables"):
            t = ds["tables"][0]
            notebook_usage = (
                f"To load a dataset as a DataFrame in a notebook cell, use:\n"
                f"  import dataclaw_data\n"
                f"  df = dataclaw_data.get_dataframe('{ds['id']}', table_name='{t['query_name']}')\n"
                f"Or with a SQL query:\n"
                f"  df = dataclaw_data.get_dataframe('{ds['id']}', sql='SELECT * FROM {t['query_name']}')\n"
                f"IMPORTANT: Use the query_name (not the display name) for table_name and SQL queries."
            )
            break

    return {"datasets": datasets, "notebook_usage": notebook_usage}


async def data_preview_data(
    *,
    dataset_id: str,
    table_name: str,
    n_rows: int = 50,
    **kwargs: Any,
) -> dict[str, Any]:
    """Preview rows from a dataset table."""
    _check_dataset_allowed(dataset_id)
    dataset = find_dataset(dataset_id)
    table = _find_table(dataset, table_name)
    conn = _connect(dataset)
    try:
        relation = _relation_for_table(conn, dataset, table)
        result = conn.execute(f"SELECT * FROM {relation} LIMIT {int(n_rows)}")
        qname = _safe_alias(table)
        payload = _rows_result(result, table_name=table_name, query_name=qname)
        payload["notebook_hint"] = (
            f"To load this table as a DataFrame in a notebook:\n"
            f"  import dataclaw_data\n"
            f"  df = dataclaw_data.get_dataframe('{dataset_id}', table_name='{qname}')\n"
            f"Or with SQL:\n"
            f"  df = dataclaw_data.get_dataframe('{dataset_id}', sql='SELECT * FROM {qname}')"
        )
        return payload
    finally:
        conn.close()


async def data_profile_dataset(
    *,
    dataset_id: str,
    table_name: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """Profile a dataset table — row count, null rates, unique counts, stats."""
    _check_dataset_allowed(dataset_id)
    dataset = find_dataset(dataset_id)
    table = _find_table(dataset, table_name)
    conn = _connect(dataset)
    try:
        relation = _relation_for_table(conn, dataset, table)
        total_rows = conn.execute(f"SELECT count(*) FROM {relation}").fetchone()[0]
        columns = _column_details(conn, relation, table)

        profile_columns = []
        for col in columns:
            name = col["name"]
            quoted = _quote(name)
            stats = conn.execute(
                f"SELECT count(*) - count({quoted}) AS nulls, count(DISTINCT {quoted}) AS uniques FROM {relation}"
            ).fetchone()
            entry: dict[str, Any] = {
                "name": name,
                "type": col["type"],
                "null_count": stats[0],
                "null_rate": (stats[0] / total_rows) if total_rows else 0,
                "unique_count": stats[1],
            }
            numeric = _numeric_stats(conn, relation, name)
            if numeric:
                entry["descriptive_stats"] = numeric
            profile_columns.append(entry)

        tname = _table_key(table)
        qname = _safe_alias(table)
        return {
            "dataset_id": dataset_id,
            "table_name": tname,
            "query_name": qname,
            "shape": {"rows": total_rows, "columns": len(columns)},
            "columns": profile_columns,
            "notebook_hint": (
                f"To work with this data in a notebook:\n"
                f"  import dataclaw_data\n"
                f"  df = dataclaw_data.get_dataframe('{dataset_id}', table_name='{qname}')\n"
                f"  df.describe()  # {total_rows} rows, {len(columns)} columns"
            ),
        }
    finally:
        conn.close()


async def data_describe_column(
    *,
    dataset_id: str,
    table_name: str,
    column_name: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """Detailed column analysis — top values, stats, histogram."""
    _check_dataset_allowed(dataset_id)
    dataset = find_dataset(dataset_id)
    table = _find_table(dataset, table_name)
    conn = _connect(dataset)
    try:
        relation = _relation_for_table(conn, dataset, table)
        columns = _column_details(conn, relation, table)
        if column_name not in {c["name"] for c in columns}:
            raise ValueError(f"Column not found: {column_name}")

        quoted = _quote(column_name)
        total = conn.execute(f"SELECT count(*) FROM {relation}").fetchone()[0]
        nulls = conn.execute(f"SELECT count(*) - count({quoted}) FROM {relation}").fetchone()[0]
        top = conn.execute(
            f"SELECT {quoted} AS value, count(*) AS cnt FROM {relation} GROUP BY 1 ORDER BY cnt DESC LIMIT 10"
        ).fetchall()

        result: dict[str, Any] = {
            "dataset_id": dataset_id,
            "table_name": _table_key(table),
            "query_name": _safe_alias(table),
            "column_name": column_name,
            "row_count": total,
            "null_count": nulls,
            "top_values": [{"value": _serialize(v), "count": c} for v, c in top],
        }
        numeric = _numeric_stats(conn, relation, column_name)
        if numeric:
            result.update(numeric)
        return result
    finally:
        conn.close()


async def data_query_data(
    *,
    dataset_id: str,
    sql: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """Run read-only DuckDB SQL against a dataset."""
    _check_dataset_allowed(dataset_id)
    if not _is_read_only(sql):
        raise ValueError("Only read-only SELECT/WITH/SHOW/DESCRIBE/SUMMARIZE SQL is allowed")

    dataset = find_dataset(dataset_id)
    conn = _connect(dataset)
    try:
        registered = _register_views(conn, dataset)
        result = conn.execute(sql)
        payload = _rows_result(result)
        payload["dataset_id"] = dataset_id
        payload["registered_tables"] = registered
        return payload
    finally:
        conn.close()


async def data_get_docs(**kwargs: Any) -> dict[str, Any]:
    """Return documentation for the dataclaw_data notebook package."""
    return {
        "package": "dataclaw_data",
        "description": "Provides access to registered datasets as DataFrames.",
        "functions": [
            {
                "name": "get_dataframe",
                "signature": "dataclaw_data.get_dataframe(dataset_id, table_name=None, sql=None, n_rows=None) -> pd.DataFrame",
                "description": "Return a DataFrame for a dataset table or read-only SQL query.",
            },
        ],
    }


# ── Helpers ─────────────────────────────────────────────────────────────────


def _dataset_summary(ds: dict[str, Any]) -> dict[str, Any]:
    tables = []
    for t in ds.get("tables") or []:
        tables.append({
            "name": _table_key(t),
            "query_name": _safe_alias(t),
            "rows": t.get("rows", 0),
            "columns": t.get("columns", 0),
            "column_details": t.get("column_details", []),
        })
    return {
        "id": ds.get("id"),
        "name": ds.get("name"),
        "type": ds.get("type"),
        "status": ds.get("status"),
        "description": ds.get("description", ""),
        "tables": tables,
    }


def _find_table(dataset: dict, table_name: str) -> dict:
    for t in dataset.get("tables") or []:
        key = _table_key(t)
        if table_name in {key, t.get("name"), _safe_alias(t)}:
            return t
    raise ValueError(f"Table not found: {table_name}")


def _connect(dataset: dict):
    if dataset.get("type") == "duckdb":
        return duckdb.connect(dataset.get("connection", ":memory:"), read_only=True)
    return duckdb.connect()


def _relation_for_table(conn: Any, dataset: dict, table: dict) -> str:
    if dataset.get("type") == "duckdb":
        schema = table.get("schema")
        name = table.get("name")
        rel = _quote(name)
        return f"{_quote(schema)}.{rel}" if schema else rel

    path = table.get("path") or dataset.get("connection", "")
    ft = table.get("file_type") or _guess_file_type(path)
    if ft == "csv":
        return f"read_csv_auto('{_sql_str(path)}')"
    if ft == "parquet":
        return f"read_parquet('{_sql_str(path)}')"
    raise ValueError(f"Unsupported source: {table.get('name')}")


def _register_views(conn: Any, dataset: dict) -> list[dict[str, str]]:
    registered = []
    if dataset.get("type") == "duckdb":
        for t in dataset.get("tables") or []:
            registered.append({"name": _table_key(t)})
        return registered
    for t in dataset.get("tables") or []:
        alias = _safe_alias(t)
        relation = _relation_for_table(conn, dataset, t)
        conn.execute(f"CREATE OR REPLACE TEMP VIEW {_quote(alias)} AS SELECT * FROM {relation}")
        registered.append({"name": _table_key(t), "query_name": alias})
    return registered


def _column_details(conn: Any, relation: str, table: dict) -> list[dict[str, str]]:
    existing = table.get("column_details")
    if existing:
        return existing
    desc = conn.execute(f"SELECT * FROM {relation} LIMIT 0").description
    return [{"name": str(c[0]), "type": str(c[1]) if len(c) > 1 else "unknown"} for c in desc]


def _rows_result(result: Any, table_name: str | None = None, query_name: str | None = None) -> dict[str, Any]:
    columns = [desc[0] for desc in result.description]
    rows = [{col: _serialize(val) for col, val in zip(columns, row)} for row in result.fetchmany(MAX_QUERY_ROWS)]
    payload: dict[str, Any] = {"columns": columns, "rows": rows, "row_count": len(rows)}
    if table_name:
        payload["table_name"] = table_name
    if query_name:
        payload["query_name"] = query_name
    return payload


def _numeric_stats(conn: Any, relation: str, column_name: str) -> dict[str, Any] | None:
    quoted = _quote(column_name)
    try:
        row = conn.execute(
            f"SELECT min({quoted})::DOUBLE, max({quoted})::DOUBLE, avg({quoted})::DOUBLE, stddev_samp({quoted})::DOUBLE FROM {relation}"
        ).fetchone()
    except Exception:
        return None
    return {"min": _serialize(row[0]), "max": _serialize(row[1]), "mean": _serialize(row[2]), "std": _serialize(row[3])}


def _is_read_only(sql: str) -> bool:
    stripped = sql.strip().lower()
    if not stripped.startswith(("select", "with", "show", "describe", "summarize")):
        return False
    blocked = r"\b(insert|update|delete|drop|alter|create|copy|attach|detach|install|load|pragma|call)\b"
    return re.search(blocked, stripped) is None


def _table_key(t: dict) -> str:
    schema = t.get("schema")
    return f"{schema}.{t.get('name')}" if schema else str(t.get("name", ""))


def _safe_alias(t: dict) -> str:
    key = _table_key(t)
    return re.sub(r"[^a-zA-Z0-9_]+", "_", key).strip("_").lower() or "table"


def _guess_file_type(path: str) -> str | None:
    from pathlib import Path as P
    s = P(path).suffix.lower()
    return {"csv": "csv", ".csv": "csv", ".parquet": "parquet", "parquet": "parquet"}.get(s)


def _quote(name: str) -> str:
    return f'"{str(name).replace(chr(34), chr(34)+chr(34))}"'


def _sql_str(val: str) -> str:
    return str(val).replace("'", "''")


def _serialize(val: Any) -> Any:
    if val is None or isinstance(val, (int, float, str, bool)):
        return val
    return str(val)
