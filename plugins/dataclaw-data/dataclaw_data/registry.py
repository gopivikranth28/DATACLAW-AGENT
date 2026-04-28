"""Dataset registry — JSON file storage for dataset definitions."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

from dataclaw.config.paths import plugin_data_dir


def _datasets_file() -> Path:
    return plugin_data_dir("data") / "datasets.json"


def read_datasets() -> list[dict[str, Any]]:
    path = _datasets_file()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def write_datasets(datasets: list[dict[str, Any]]) -> None:
    path = _datasets_file()
    path.write_text(json.dumps(datasets, indent=2, default=str), encoding="utf-8")


def find_dataset(dataset_id: str) -> dict[str, Any]:
    for ds in read_datasets():
        if ds.get("id") == dataset_id:
            return ds
    raise ValueError(f"Dataset not found: {dataset_id}")


def create_dataset(
    *,
    name: str,
    ds_type: str,
    connection: str,
    description: str = "",
) -> dict[str, Any]:
    datasets = read_datasets()
    ds_id = str(uuid.uuid4())[:8]
    now = datetime.now(timezone.utc).isoformat()

    tables = _introspect_tables(ds_type, connection)

    dataset: dict[str, Any] = {
        "id": ds_id,
        "name": name,
        "type": ds_type,
        "connection": connection,
        "description": description,
        "status": "connected" if tables else "error",
        "tables": tables or [],
        "created_at": now,
        "updated_at": now,
    }
    datasets.append(dataset)
    write_datasets(datasets)
    return dataset


def update_dataset_fields(dataset_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    """Update fields on an existing dataset."""
    datasets = read_datasets()
    for ds in datasets:
        if ds.get("id") == dataset_id:
            for key, value in updates.items():
                if key not in ("id", "created_at", "tables") and value is not None:
                    ds[key] = value
            ds["updated_at"] = datetime.now(timezone.utc).isoformat()
            # Re-introspect if connection changed
            if "connection" in updates or "type" in updates:
                tables = _introspect_tables(ds.get("type", ""), ds.get("connection", ""))
                ds["tables"] = tables or []
                ds["status"] = "connected" if tables else "error"
            write_datasets(datasets)
            return ds
    raise ValueError(f"Dataset not found: {dataset_id}")


def delete_dataset(dataset_id: str) -> bool:
    datasets = read_datasets()
    filtered = [ds for ds in datasets if ds.get("id") != dataset_id]
    if len(filtered) == len(datasets):
        return False
    write_datasets(filtered)
    return True


def refresh_dataset(dataset_id: str) -> dict[str, Any]:
    datasets = read_datasets()
    for ds in datasets:
        if ds.get("id") == dataset_id:
            tables = _introspect_tables(ds.get("type", ""), ds.get("connection", ""))
            ds["tables"] = tables or []
            ds["status"] = "connected" if tables else "error"
            ds["updated_at"] = datetime.now(timezone.utc).isoformat()
            write_datasets(datasets)
            return ds
    raise ValueError(f"Dataset not found: {dataset_id}")


# ── Introspection ────────────────────────────────────��──────────────────────

def _introspect_tables(ds_type: str, connection: str) -> list[dict[str, Any]] | None:
    try:
        if ds_type == "duckdb":
            return _introspect_duckdb(connection)
        if ds_type in ("local_file", "csv", "parquet"):
            return _introspect_file(connection, ds_type)
        return None
    except Exception:
        return None


def _introspect_duckdb(connection: str) -> list[dict[str, Any]]:
    conn = duckdb.connect(connection, read_only=True)
    try:
        rows = conn.execute(
            """SELECT table_schema, table_name FROM information_schema.tables
               WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
               ORDER BY table_schema, table_name"""
        ).fetchall()
        result = []
        for schema, name in rows:
            qname = f'"{schema}"."{name}"'
            try:
                count = conn.execute(f"SELECT count(*) FROM {qname}").fetchone()[0]
                desc = conn.execute(f"SELECT * FROM {qname} LIMIT 0").description
                result.append({
                    "schema": schema,
                    "name": name,
                    "rows": count,
                    "columns": len(desc),
                    "column_details": [
                        {"name": str(c[0]), "type": str(c[1]) if len(c) > 1 else "unknown"}
                        for c in desc
                    ],
                })
            except Exception:
                result.append({"schema": schema, "name": name, "rows": 0, "columns": 0})
        return result
    finally:
        conn.close()


def _introspect_file(connection: str, ds_type: str) -> list[dict[str, Any]]:
    path = Path(connection)
    if not path.exists():
        return []

    if path.is_dir():
        tables = []
        suffixes = {".csv", ".parquet"} if ds_type == "local_file" else {f".{ds_type}"}
        for f in sorted(path.rglob("*")):
            if f.is_file() and f.suffix.lower() in suffixes:
                t = _introspect_single_file(f, path)
                if t:
                    tables.append(t)
        return tables

    t = _introspect_single_file(path)
    return [t] if t else []


def _introspect_single_file(path: Path, root: Path | None = None) -> dict[str, Any] | None:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        reader = "read_csv_auto"
    elif suffix == ".parquet":
        reader = "read_parquet"
    else:
        return None

    conn = duckdb.connect()
    try:
        count = conn.execute(f"SELECT count(*) FROM {reader}('{_sql_str(path)}')").fetchone()[0]
        desc = conn.execute(f"SELECT * FROM {reader}('{_sql_str(path)}') LIMIT 0").description
        name = str(path.relative_to(root)) if root else path.name
        return {
            "schema": "file",
            "name": name,
            "rows": count,
            "columns": len(desc),
            "column_details": [
                {"name": str(c[0]), "type": str(c[1]) if len(c) > 1 else "unknown"}
                for c in desc
            ],
            "path": str(path),
            "file_type": suffix.lstrip("."),
        }
    except Exception:
        return None
    finally:
        conn.close()


def _sql_str(path: Path) -> str:
    return str(path).replace("'", "''")
