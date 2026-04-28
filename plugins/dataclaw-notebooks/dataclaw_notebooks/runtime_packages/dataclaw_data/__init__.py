"""Dataclaw notebook data utilities.

Pre-installed in every Dataclaw notebook kernel. Provides access to
registered datasets as DataFrames without exposing connection strings.

Usage in notebooks:
    import dataclaw_data
    df = dataclaw_data.get_dataframe("my_dataset", table_name="sales")
    df = dataclaw_data.get_dataframe("my_dataset", sql="SELECT * FROM sales WHERE year = 2025")
"""

from __future__ import annotations

import os
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

    Exactly one of table_name or sql must be provided.
    """
    if bool(table_name) == bool(sql):
        raise ValueError("Provide exactly one of table_name or sql")

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

    response = requests.post(
        f"{_api_url()}/api/data/dataframe",
        json=payload,
        timeout=120,
    )
    if not response.ok:
        raise RuntimeError(f"Dataclaw data request failed: {response.status_code} {response.text}")
    body = response.json()
    return pd.DataFrame(body.get("rows", []), columns=body.get("columns", []))


def get_experiment_id() -> str | None:
    """Return the active MLflow experiment ID from the environment."""
    return os.environ.get("MLFLOW_EXPERIMENT_ID")


def _api_url() -> str:
    return os.environ.get("DATACLAW_API_URL", DEFAULT_API_URL).rstrip("/")
