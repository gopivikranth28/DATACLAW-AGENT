"""Data registry router — dataset CRUD and preview endpoints."""

from __future__ import annotations

import uuid
from pathlib import Path, PurePosixPath
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from dataclaw.config.paths import plugin_data_dir
from dataclaw_data.registry import (
    read_datasets,
    find_dataset,
    create_dataset,
    delete_dataset,
    refresh_dataset,
    update_dataset_fields,
)
from dataclaw_data.tools import data_preview_data

UPLOADS_DIR = plugin_data_dir("data") / "uploads"

router = APIRouter()


class DatasetCreateRequest(BaseModel):
    name: str
    type: str  # "duckdb" | "local_file" | "csv" | "parquet" | "postgres" | "snowflake" | "bigquery"
    connection: str
    description: str = ""


class DatasetUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    definition: str | None = None
    connection: str | None = None
    type: str | None = None
    table_definitions: dict[str, str] | None = None
    column_definitions: dict[str, dict[str, str]] | None = None


@router.get("/datasets")
async def list_datasets() -> list[dict[str, Any]]:
    return read_datasets()


@router.post("/datasets")
async def create(req: DatasetCreateRequest) -> dict[str, Any]:
    return create_dataset(
        name=req.name,
        ds_type=req.type,
        connection=req.connection,
        description=req.description,
    )


_ALLOWED_SUFFIXES = {".csv", ".parquet"}


@router.post("/datasets/upload")
async def upload_dataset(
    files: list[UploadFile] = File(...),
    name: str = Form(""),
    description: str = Form(""),
) -> dict[str, Any]:
    """Upload CSV/Parquet file(s) or a folder and create a dataset."""
    # Filter to allowed file types
    valid = [f for f in files if PurePosixPath(f.filename or "").suffix.lower() in _ALLOWED_SUFFIXES]
    if not valid:
        raise HTTPException(400, "No .csv or .parquet files found in upload")

    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    prefix = uuid.uuid4().hex[:8]

    if len(valid) == 1:
        # Single file upload
        f = valid[0]
        fname = f"{prefix}_{f.filename}"
        dest = UPLOADS_DIR / fname
        dest.write_bytes(await f.read())

        suffix = PurePosixPath(f.filename or "").suffix.lower()
        ds_type = "csv" if suffix == ".csv" else "parquet"
        ds_name = name or Path(f.filename or "upload").stem
    else:
        # Multi-file / folder upload
        ds_name = name or "uploaded_folder"
        folder = UPLOADS_DIR / f"{prefix}_{ds_name}"
        folder.mkdir(parents=True, exist_ok=True)

        for f in valid:
            # Preserve relative path structure from webkitRelativePath
            rel = f.filename or f"file_{uuid.uuid4().hex[:4]}"
            dest = folder / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(await f.read())

        dest = folder
        ds_type = "local_file"

    return create_dataset(
        name=ds_name,
        ds_type=ds_type,
        connection=str(dest),
        description=description,
    )


@router.get("/datasets/{dataset_id}")
async def get_dataset(dataset_id: str) -> dict[str, Any]:
    try:
        return find_dataset(dataset_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Dataset not found")


@router.patch("/datasets/{dataset_id}")
async def update_dataset(dataset_id: str, req: DatasetUpdateRequest) -> dict[str, Any]:
    try:
        return update_dataset_fields(dataset_id, req.model_dump(exclude_unset=True))
    except ValueError:
        raise HTTPException(status_code=404, detail="Dataset not found")


@router.delete("/datasets/{dataset_id}")
async def remove_dataset(dataset_id: str) -> dict[str, str]:
    if not delete_dataset(dataset_id):
        raise HTTPException(status_code=404, detail="Dataset not found")
    return {"status": "deleted"}


@router.post("/datasets/{dataset_id}/refresh")
async def refresh(dataset_id: str) -> dict[str, Any]:
    try:
        return refresh_dataset(dataset_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Dataset not found")


@router.get("/datasets/{dataset_id}/preview")
async def preview(dataset_id: str, table: str, n_rows: int = 50) -> dict[str, Any]:
    try:
        return await data_preview_data(dataset_id=dataset_id, table_name=table, n_rows=n_rows)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


class DataFrameRequest(BaseModel):
    """Request from dataclaw_data notebook package."""
    dataset_id: str
    table_name: str | None = None
    sql: str | None = None
    n_rows: int | None = None
    session_id: str | None = None


@router.post("/dataframe")
async def dataframe(req: DataFrameRequest) -> dict[str, Any]:
    """Endpoint for the dataclaw_data notebook package — returns rows + columns."""
    from dataclaw_data.tools import data_preview_data, data_query_data
    try:
        if req.sql:
            return await data_query_data(dataset_id=req.dataset_id, sql=req.sql)
        elif req.table_name:
            return await data_preview_data(
                dataset_id=req.dataset_id, table_name=req.table_name,
                n_rows=req.n_rows or 10000,
            )
        else:
            raise HTTPException(400, "Provide table_name or sql")
    except ValueError as e:
        raise HTTPException(400, str(e))
