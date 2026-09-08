"""Tests for OKF bundle generation and tools."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

import dataclaw.config.paths as paths
from dataclaw_data.registry import create_dataset, update_dataset_fields
from dataclaw_okf.generator import generate_bundle, is_bundle_stale
from dataclaw_okf.registry import find_bundle, read_bundles
from dataclaw_okf.tools import (
    okf_export_bundle,
    okf_generate_bundle,
    okf_list_bundles,
    okf_read_bundle,
    okf_search_bundle,
)


@pytest.fixture(autouse=True)
def tmp_home(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DATACLAW_HOME", tmp_path)
    return tmp_path


@pytest.fixture
def sample_dataset(tmp_path):
    csv_path = tmp_path / "sales.csv"
    csv_path.write_text(
        "id,product,price,quantity\n"
        "1,Widget,9.99,10\n"
        "2,Gadget,19.99,5\n"
        "3,Widget,9.99,3\n",
        encoding="utf-8",
    )
    return create_dataset(
        name="Sales",
        ds_type="local_file",
        connection=str(csv_path),
        description="Retail sales transactions",
    )


def test_generate_bundle_creates_markdown_catalog(sample_dataset):
    bundle = generate_bundle(sample_dataset["id"])

    assert bundle["status"] == "generated"
    assert bundle["dataset_id"] == sample_dataset["id"]
    assert bundle["file_count"] >= 5

    root = Path(bundle["path"])
    assert (root / "index.md").is_file()
    assert (root / "log.md").is_file()
    assert (root / "tables/index.md").is_file()
    assert (root / "columns/index.md").is_file()
    assert (root / "quality/index.md").is_file()
    assert (root / "datasets/sales.md").is_file()
    assert any(f.startswith("tables/") for f in bundle["files"])

    text = (root / "index.md").read_text(encoding="utf-8")
    assert "okf_version: \"0.1\"" in text
    assert "[Tables](tables/)" in text
    assert "Retail sales transactions" in text  # OKF index entries include short descriptions.

    dataset_card = (root / "datasets/sales.md").read_text(encoding="utf-8")
    assert "type: \"Dataclaw Dataset\"" in dataset_card
    assert "description: \"Retail sales transactions\"" in dataset_card
    assert "](/tables/" in dataset_card

    quality_files = [f for f in bundle["files"] if f.startswith("quality/")]
    assert quality_files
    quality = (root / quality_files[0]).read_text(encoding="utf-8")
    assert "type: \"Dataclaw Data Quality Notes\"" in quality
    assert "## Profile Summary" in quality
    assert "Duplicate rows: `0`" in quality
    assert "| `product` | `VARCHAR` | 0 | 0.0% | 0 | 0.0% | 2 | 66.7% |" in quality
    assert "| `price` |" in quality

    persisted = find_bundle(bundle["id"])
    assert persisted["source_hash"] == bundle["source_hash"]


def test_generated_markdown_conforms_to_okf_reserved_file_rules(sample_dataset):
    bundle = generate_bundle(sample_dataset["id"])
    root = Path(bundle["path"])

    for rel in bundle["files"]:
        path = root / rel
        text = path.read_text(encoding="utf-8")
        if path.name == "index.md":
            if rel == "index.md":
                assert text.startswith("---\nokf_version: \"0.1\"\n---\n")
            else:
                assert not text.startswith("---")
            continue
        if path.name == "log.md":
            assert text.startswith("# Bundle Update Log")
            assert not text.startswith("---")
            continue
        assert text.startswith("---\n")
        frontmatter = text.split("---", 2)[1]
        assert "type: " in frontmatter


def test_generate_bundle_is_idempotent_until_dataset_changes(sample_dataset):
    first = generate_bundle(sample_dataset["id"])
    second = generate_bundle(sample_dataset["id"])

    assert second["status"] == "unchanged"
    assert second["id"] == first["id"]
    assert is_bundle_stale(second) is False

    update_dataset_fields(sample_dataset["id"], {"description": "Updated description"})
    assert is_bundle_stale(second) is True

    regenerated = generate_bundle(sample_dataset["id"])
    assert regenerated["status"] == "generated"
    assert regenerated["id"] == first["id"]
    assert regenerated["source_hash"] != first["source_hash"]


def test_quality_profile_reports_missing_like_tokens_and_numeric_text(tmp_path):
    csv_path = tmp_path / "kaggle_like.csv"
    csv_path.write_text(
        "id,garage_area,alley\n"
        "1,100,Grvl\n"
        "2,NA,NA\n"
        "3,240,\n"
        "4,300,None\n",
        encoding="utf-8",
    )
    ds = create_dataset(
        name="Kaggle Like",
        ds_type="csv",
        connection=str(csv_path),
        description="Dataset with encoded missing values",
    )

    bundle = generate_bundle(ds["id"])
    root = Path(bundle["path"])
    quality_files = [f for f in bundle["files"] if f.startswith("quality/")]
    quality = (root / quality_files[0]).read_text(encoding="utf-8")

    assert "Missing-Like Tokens" in quality
    assert "`garage_area` contains many missing-like tokens" in quality
    assert "`garage_area` is stored as text" in quality
    assert "`alley` contains many missing-like tokens" in quality


@pytest.mark.asyncio
async def test_okf_tools_list_read_search_and_export(sample_dataset):
    generated = await okf_generate_bundle(dataset_id=sample_dataset["id"])
    bundle_id = generated["id"]

    listed = await okf_list_bundles()
    assert listed["count"] == 1
    assert listed["bundles"][0]["id"] == bundle_id

    index = await okf_read_bundle(bundle_id=bundle_id)
    assert "index.md" in index["files"]

    dataset_file = await okf_read_bundle(bundle_id=bundle_id, path="datasets/sales.md")
    assert "Dataset Card: Sales" in dataset_file["content"]
    assert dataset_file["truncated"] is False

    matches = await okf_search_bundle(bundle_id=bundle_id, query="retail sales")
    assert matches["count"] >= 1
    assert any(m["path"] == "datasets/sales.md" for m in matches["matches"])

    quality_matches = await okf_search_bundle(bundle_id=bundle_id, query="duplicate null")
    assert quality_matches["count"] >= 1
    assert any(m["path"].startswith("quality/") for m in quality_matches["matches"])

    exported = await okf_export_bundle(bundle_id=bundle_id)
    archive = Path(exported["archive_path"])
    assert archive.is_file()
    with zipfile.ZipFile(archive) as zf:
        assert "index.md" in zf.namelist()
        assert "datasets/sales.md" in zf.namelist()


def test_registry_starts_empty():
    assert read_bundles() == []
