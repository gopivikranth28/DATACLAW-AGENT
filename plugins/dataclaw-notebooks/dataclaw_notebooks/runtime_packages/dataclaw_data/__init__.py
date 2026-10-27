"""Dataclaw notebook data utilities.

Pre-installed in every Dataclaw notebook kernel. Provides access to
registered datasets as DataFrames without exposing connection strings.

Usage in notebooks:
    import dataclaw_data
    # Full result (streamed as Parquet):
    df = dataclaw_data.get_dataframe("my_dataset", table_name="sales")
    df = dataclaw_data.get_dataframe("my_dataset", sql="SELECT * FROM sales WHERE year = 2025")
    # Bounded preview:
    preview = dataclaw_data.get_dataframe("my_dataset", table_name="sales", n_rows=1000)
"""

from __future__ import annotations

import os
import tempfile
import warnings
from pathlib import Path
from typing import Any

import pandas as pd
import requests

DEFAULT_API_URL = "http://127.0.0.1:8000"


def get_dataframe(
    dataset_id: str,
    table_name: str | None = None,
    sql: str | None = None,
    n_rows: int | None = None,
) -> pd.DataFrame:
    """Return a DataFrame for a dataset table or read-only SQL query.

    Exactly one of table_name or sql must be provided. With n_rows omitted,
    Dataclaw streams the complete result as Parquet. Passing n_rows explicitly
    requests a bounded preview subject to the configured preview ceiling.

    For large sources, prefer a selective SQL query (including server-side
    joins and column selection) instead of loading an entire wide table.
    """
    if bool(table_name) == bool(sql):
        raise ValueError("Provide exactly one of table_name or sql")
    if n_rows is not None and n_rows <= 0:
        raise ValueError("n_rows must be greater than zero")

    payload: dict[str, Any] = {"dataset_id": dataset_id}
    if table_name:
        payload["table_name"] = table_name
    if sql:
        payload["sql"] = sql
    if n_rows is not None:
        payload["n_rows"] = n_rows
    session_id = os.environ.get("DATACLAW_SESSION_ID")
    if session_id:
        payload["session_id"] = session_id

    if n_rows is None:
        return _get_full_dataframe(payload)
    return _get_preview_dataframe(payload)


def _get_preview_dataframe(payload: dict[str, Any]) -> pd.DataFrame:
    response = requests.post(
        f"{_api_url()}/api/data/dataframe",
        json=payload,
        headers=_auth_headers(),
        timeout=120,
    )
    if not response.ok:
        raise RuntimeError(f"Dataclaw data request failed: {response.status_code} {response.text}")
    body = response.json()
    frame = pd.DataFrame(body.get("rows", []), columns=body.get("columns", []))
    frame.attrs["dataclaw_truncated"] = bool(body.get("truncated"))
    frame.attrs["dataclaw_row_limit"] = body.get("row_limit")
    frame.attrs["dataclaw_access_mode"] = "preview"
    if body.get("truncated"):
        warnings.warn(
            "Dataclaw limited this preview to "
            f"{body.get('row_limit')} rows. Omit n_rows for the full result "
            "or use a selective SQL query for large analyses.",
            RuntimeWarning,
            stacklevel=2,
        )
    return frame


def _get_full_dataframe(payload: dict[str, Any]) -> pd.DataFrame:
    temp_path: Path | None = None
    try:
        with requests.post(
            f"{_api_url()}/api/data/dataframe/export",
            json=payload,
            headers=_auth_headers(),
            stream=True,
            timeout=(10, 1800),
        ) as response:
            if not response.ok:
                raise RuntimeError(
                    "Dataclaw data request failed: "
                    f"{response.status_code} {response.text}"
                )

            with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as temp_file:
                temp_path = Path(temp_file.name)
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        temp_file.write(chunk)

        frame = _read_parquet(temp_path)
        frame.attrs["dataclaw_truncated"] = False
        frame.attrs["dataclaw_row_limit"] = None
        frame.attrs["dataclaw_access_mode"] = "full"
        return frame
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def _read_parquet(path: Path) -> pd.DataFrame:
    """Read Parquet without requiring pandas' optional PyArrow dependency."""
    try:
        import duckdb
    except ImportError:
        try:
            return pd.read_parquet(path)
        except ImportError as exc:
            raise RuntimeError(
                "Reading full Dataclaw results requires duckdb or a pandas "
                "Parquet engine in the notebook environment"
            ) from exc

    conn = duckdb.connect()
    try:
        return conn.read_parquet(str(path)).df()
    finally:
        conn.close()


def get_experiment_id() -> str | None:
    """Return the active MLflow experiment ID from the environment."""
    return os.environ.get("MLFLOW_EXPERIMENT_ID")


def _api_url() -> str:
    return os.environ.get("DATACLAW_API_URL", DEFAULT_API_URL).rstrip("/")


def _auth_headers() -> dict[str, str]:
    token = os.environ.get("DATACLAW_TOKEN")
    return {"X-Dataclaw-Token": token} if token else {}
