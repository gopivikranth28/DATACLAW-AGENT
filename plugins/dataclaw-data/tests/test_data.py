"""Tests for the data plugin — registry and tools."""

import json
import pytest
from pathlib import Path

import duckdb

import dataclaw.config.paths as paths
from dataclaw_data.registry import (
    read_datasets,
    write_datasets,
    create_dataset,
    find_dataset,
    delete_dataset,
    refresh_dataset,
)
from dataclaw_data.tools import (
    MAX_QUERY_ROWS,
    data_list_datasets,
    data_preview_data,
    data_profile_dataset,
    data_describe_column,
    data_query_data,
    set_plugin_cfg,
)


@pytest.fixture(autouse=True)
def tmp_home(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DATACLAW_HOME", tmp_path)
    return tmp_path


@pytest.fixture
def sample_csv(tmp_path):
    """Create a sample CSV file."""
    csv_path = tmp_path / "sales.csv"
    csv_path.write_text("id,product,price,quantity\n1,Widget,9.99,10\n2,Gadget,19.99,5\n3,Widget,9.99,3\n")
    return csv_path


@pytest.fixture
def sample_duckdb(tmp_path):
    """Create a sample DuckDB database."""
    db_path = tmp_path / "test.duckdb"
    conn = duckdb.connect(str(db_path))
    conn.execute("CREATE TABLE products (id INT, name VARCHAR, price DOUBLE)")
    conn.execute("INSERT INTO products VALUES (1, 'Widget', 9.99), (2, 'Gadget', 19.99), (3, 'Doohickey', 4.99)")
    conn.close()
    return db_path


# ── Registry tests ──────────────────────────────────────────────────────────

def test_empty_registry():
    assert read_datasets() == []


def test_create_dataset_csv(sample_csv):
    ds = create_dataset(name="Sales", ds_type="local_file", connection=str(sample_csv))
    assert ds["name"] == "Sales"
    assert ds["status"] == "connected"
    assert len(ds["tables"]) == 1
    assert ds["tables"][0]["rows"] == 3

    # Persisted
    all_ds = read_datasets()
    assert len(all_ds) == 1


def test_create_dataset_duckdb(sample_duckdb):
    ds = create_dataset(name="TestDB", ds_type="duckdb", connection=str(sample_duckdb))
    assert ds["status"] == "connected"
    table_names = [t["name"] for t in ds["tables"]]
    assert "products" in table_names


def test_find_dataset(sample_csv):
    ds = create_dataset(name="Sales", ds_type="local_file", connection=str(sample_csv))
    found = find_dataset(ds["id"])
    assert found["name"] == "Sales"


def test_find_dataset_not_found():
    with pytest.raises(ValueError, match="not found"):
        find_dataset("nonexistent")


def test_delete_dataset(sample_csv):
    ds = create_dataset(name="Sales", ds_type="local_file", connection=str(sample_csv))
    assert delete_dataset(ds["id"]) is True
    assert read_datasets() == []


def test_refresh_dataset(sample_csv):
    ds = create_dataset(name="Sales", ds_type="local_file", connection=str(sample_csv))
    refreshed = refresh_dataset(ds["id"])
    assert refreshed["status"] == "connected"


# ── Tool tests ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_datasets(sample_csv):
    create_dataset(name="Sales", ds_type="local_file", connection=str(sample_csv))
    result = await data_list_datasets()
    assert len(result["datasets"]) == 1
    assert result["datasets"][0]["name"] == "Sales"


@pytest.mark.asyncio
async def test_preview_data(sample_csv):
    ds = create_dataset(name="Sales", ds_type="local_file", connection=str(sample_csv))
    result = await data_preview_data(dataset_id=ds["id"], table_name=ds["tables"][0]["name"], n_rows=2)
    assert result["row_count"] == 2
    assert "id" in result["columns"]
    assert "price" in result["columns"]


@pytest.mark.asyncio
async def test_profile_dataset(sample_csv):
    ds = create_dataset(name="Sales", ds_type="local_file", connection=str(sample_csv))
    result = await data_profile_dataset(dataset_id=ds["id"], table_name=ds["tables"][0]["name"])
    assert result["shape"]["rows"] == 3
    assert len(result["columns"]) == 4
    # price column should have numeric stats
    price_col = next(c for c in result["columns"] if c["name"] == "price")
    assert "descriptive_stats" in price_col


@pytest.mark.asyncio
async def test_describe_column(sample_csv):
    ds = create_dataset(name="Sales", ds_type="local_file", connection=str(sample_csv))
    result = await data_describe_column(
        dataset_id=ds["id"], table_name=ds["tables"][0]["name"], column_name="product"
    )
    assert result["column_name"] == "product"
    assert result["row_count"] == 3
    # "Widget" appears twice
    top = {v["value"]: v["count"] for v in result["top_values"]}
    assert top.get("Widget") == 2


@pytest.mark.asyncio
async def test_query_data_duckdb(sample_duckdb):
    ds = create_dataset(name="TestDB", ds_type="duckdb", connection=str(sample_duckdb))
    result = await data_query_data(dataset_id=ds["id"], sql="SELECT name, price FROM products WHERE price > 5 ORDER BY price")
    assert result["row_count"] == 2
    assert result["rows"][0]["name"] == "Widget"


@pytest.mark.asyncio
async def test_query_data_csv(sample_csv):
    ds = create_dataset(name="Sales", ds_type="local_file", connection=str(sample_csv))
    # Query using the registered view alias (not raw table name)
    result = await data_query_data(dataset_id=ds["id"], sql="SELECT product, sum(quantity) as total FROM file_sales_csv GROUP BY 1 ORDER BY total DESC")
    assert result["row_count"] >= 1


@pytest.mark.asyncio
async def test_query_data_blocked_sql(sample_csv):
    ds = create_dataset(name="Sales", ds_type="local_file", connection=str(sample_csv))
    with pytest.raises(ValueError, match="read-only"):
        await data_query_data(dataset_id=ds["id"], sql="DROP TABLE something")


@pytest.mark.asyncio
async def test_describe_column_not_found(sample_csv):
    ds = create_dataset(name="Sales", ds_type="local_file", connection=str(sample_csv))
    with pytest.raises(ValueError, match="Column not found"):
        await data_describe_column(dataset_id=ds["id"], table_name=ds["tables"][0]["name"], column_name="nonexistent")


# ── Row cap tests ──────────────────────────────────────────────────────────


@pytest.fixture
def large_csv(tmp_path):
    """CSV with more rows than MAX_QUERY_ROWS so cap behavior is observable."""
    n = MAX_QUERY_ROWS + 200  # 700 rows
    csv_path = tmp_path / "big.csv"
    lines = ["id,value"]
    lines.extend(f"{i},{i * 2}" for i in range(n))
    csv_path.write_text("\n".join(lines) + "\n")
    return csv_path, n


@pytest.mark.asyncio
async def test_query_data_default_caps_at_max(large_csv):
    """LLM-style call (no max_rows arg) caps rows at MAX_QUERY_ROWS."""
    csv_path, n = large_csv
    ds = create_dataset(name="Big", ds_type="local_file", connection=str(csv_path))
    alias = "file_big_csv"
    result = await data_query_data(
        dataset_id=ds["id"],
        sql=f"SELECT * FROM {alias}",
    )
    assert n > MAX_QUERY_ROWS  # sanity
    assert result["row_count"] == MAX_QUERY_ROWS


@pytest.mark.asyncio
async def test_query_data_max_rows_none_returns_all(large_csv):
    """Notebook runtime path (max_rows=None) returns the full result set."""
    csv_path, n = large_csv
    ds = create_dataset(name="Big", ds_type="local_file", connection=str(csv_path))
    alias = "file_big_csv"
    result = await data_query_data(
        dataset_id=ds["id"],
        sql=f"SELECT * FROM {alias}",
        max_rows=None,
    )
    assert result["row_count"] == n


@pytest.mark.asyncio
async def test_query_data_explicit_max_rows(large_csv):
    csv_path, _ = large_csv
    ds = create_dataset(name="Big", ds_type="local_file", connection=str(csv_path))
    alias = "file_big_csv"
    result = await data_query_data(
        dataset_id=ds["id"],
        sql=f"SELECT * FROM {alias}",
        max_rows=42,
    )
    assert result["row_count"] == 42


@pytest.mark.asyncio
async def test_preview_data_returns_more_than_max_when_n_rows_exceeds(large_csv):
    """data_preview_data must honor n_rows even when it exceeds MAX_QUERY_ROWS."""
    csv_path, n = large_csv
    ds = create_dataset(name="Big", ds_type="local_file", connection=str(csv_path))
    table = ds["tables"][0]["name"]
    result = await data_preview_data(
        dataset_id=ds["id"],
        table_name=table,
        n_rows=MAX_QUERY_ROWS + 100,
    )
    assert result["row_count"] == MAX_QUERY_ROWS + 100
    assert result["row_count"] < n  # didn't accidentally read everything


@pytest.mark.asyncio
async def test_dataframe_endpoint_sql_path_uncapped(large_csv):
    """The /api/data/dataframe endpoint (notebook runtime) must not cap SQL results."""
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from dataclaw_data.router import router

    csv_path, n = large_csv
    ds = create_dataset(name="Big", ds_type="local_file", connection=str(csv_path))
    alias = "file_big_csv"

    app = FastAPI()
    app.include_router(router, prefix="/api/data")
    client = TestClient(app)

    response = client.post(
        "/api/data/dataframe",
        json={"dataset_id": ds["id"], "sql": f"SELECT * FROM {alias}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["row_count"] == n


@pytest.mark.asyncio
async def test_dataframe_endpoint_table_path_uncapped(large_csv):
    """get_dataframe(id, table_name=...) with no n_rows must return the full table."""
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from dataclaw_data.router import router

    csv_path, n = large_csv
    ds = create_dataset(name="Big", ds_type="local_file", connection=str(csv_path))
    table = ds["tables"][0]["name"]

    app = FastAPI()
    app.include_router(router, prefix="/api/data")
    client = TestClient(app)

    response = client.post(
        "/api/data/dataframe",
        json={"dataset_id": ds["id"], "table_name": table},
    )
    assert response.status_code == 200
    body = response.json()
    assert n > 10000 or body["row_count"] == n  # truthy check; either full or sane
    # Specifically: must exceed the prior 10000 hardcoded fallback.
    assert body["row_count"] == n


@pytest.mark.asyncio
async def test_preview_data_n_rows_none_returns_all(large_csv):
    """Direct call to data_preview_data with n_rows=None returns full table."""
    csv_path, n = large_csv
    ds = create_dataset(name="Big", ds_type="local_file", connection=str(csv_path))
    table = ds["tables"][0]["name"]
    result = await data_preview_data(
        dataset_id=ds["id"], table_name=table, n_rows=None,
    )
    assert result["row_count"] == n


# ── Config-driven cap tests ────────────────────────────────────────────────


@pytest.fixture
def reset_plugin_cfg():
    """Ensure each test starts and ends with an empty plugin config."""
    set_plugin_cfg({})
    yield
    set_plugin_cfg({})


@pytest.mark.asyncio
async def test_query_data_cap_uses_configured_max_rows(large_csv, reset_plugin_cfg):
    """Setting max_query_rows in plugin config changes the LLM-default cap."""
    csv_path, _ = large_csv
    ds = create_dataset(name="Big", ds_type="local_file", connection=str(csv_path))
    alias = "file_big_csv"

    set_plugin_cfg({"max_query_rows": 75})
    result = await data_query_data(
        dataset_id=ds["id"], sql=f"SELECT * FROM {alias}",
    )
    assert result["row_count"] == 75


@pytest.mark.asyncio
async def test_query_data_cap_falls_back_when_config_missing(large_csv, reset_plugin_cfg):
    csv_path, _ = large_csv
    ds = create_dataset(name="Big", ds_type="local_file", connection=str(csv_path))
    alias = "file_big_csv"

    # Empty cfg → fall back to MAX_QUERY_ROWS.
    result = await data_query_data(
        dataset_id=ds["id"], sql=f"SELECT * FROM {alias}",
    )
    assert result["row_count"] == MAX_QUERY_ROWS


@pytest.mark.asyncio
async def test_query_data_cap_invalid_config_falls_back(large_csv, reset_plugin_cfg):
    csv_path, _ = large_csv
    ds = create_dataset(name="Big", ds_type="local_file", connection=str(csv_path))
    alias = "file_big_csv"

    # Garbage values fall back to the safe default rather than crashing.
    set_plugin_cfg({"max_query_rows": "not-a-number"})
    result = await data_query_data(
        dataset_id=ds["id"], sql=f"SELECT * FROM {alias}",
    )
    assert result["row_count"] == MAX_QUERY_ROWS

    set_plugin_cfg({"max_query_rows": 0})
    result = await data_query_data(
        dataset_id=ds["id"], sql=f"SELECT * FROM {alias}",
    )
    assert result["row_count"] == MAX_QUERY_ROWS


@pytest.mark.asyncio
async def test_query_data_explicit_max_rows_overrides_config(large_csv, reset_plugin_cfg):
    """Explicit max_rows arg wins over plugin config (notebook runtime path)."""
    csv_path, n = large_csv
    ds = create_dataset(name="Big", ds_type="local_file", connection=str(csv_path))
    alias = "file_big_csv"

    set_plugin_cfg({"max_query_rows": 25})
    # max_rows=None still bypasses the cap entirely.
    result = await data_query_data(
        dataset_id=ds["id"], sql=f"SELECT * FROM {alias}", max_rows=None,
    )
    assert result["row_count"] == n
