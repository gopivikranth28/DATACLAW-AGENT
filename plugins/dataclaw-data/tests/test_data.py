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
    data_list_datasets,
    data_preview_data,
    data_profile_dataset,
    data_describe_column,
    data_query_data,
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
