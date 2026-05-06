"""Kaggle agent tools — competitions, datasets, and submissions."""

from __future__ import annotations

import logging
import os
import zipfile
from pathlib import Path
from typing import Any

from dataclaw.config.paths import plugin_data_dir

from dataclaw_kaggle.client import run_kaggle, get_config
from dataclaw_kaggle import registry

logger = logging.getLogger(__name__)

# Module-level config, set by the plugin's register() method.
_plugin_cfg: dict[str, Any] = {}


def set_plugin_cfg(cfg: dict[str, Any]) -> None:
    global _plugin_cfg
    _plugin_cfg = cfg


def _creds() -> dict[str, str]:
    u, k = get_config(_plugin_cfg)
    return {"username": u, "key": k}


def _download_root() -> Path:
    custom = _plugin_cfg.get("download_dir", "")
    if custom:
        return Path(custom)
    return plugin_data_dir("kaggle")


def _competition_dir(slug: str) -> Path:
    d = _download_root() / "competitions" / slug
    d.mkdir(parents=True, exist_ok=True)
    return d


def _dataset_dir(ref: str) -> Path:
    safe = ref.replace("/", "_")
    d = _download_root() / "datasets" / safe
    d.mkdir(parents=True, exist_ok=True)
    return d


def _auto_register() -> bool:
    return _plugin_cfg.get("auto_register_datasets", True)


def _is_valid_cached_download(existing: dict[str, Any] | None) -> bool:
    """Return True if a registry-recorded download still has files on disk.

    Guards against stale registry entries where the download directory was
    deleted out from under us — without this, we'd return "already_downloaded"
    pointing at an empty/missing path.
    """
    if not existing or not existing.get("downloaded"):
        return False
    download_path = existing.get("download_path", "")
    if not download_path:
        return False
    p = Path(download_path)
    if not p.is_dir():
        return False
    return any(child.is_file() for child in p.iterdir())


def _is_within(target: Path, root: Path) -> bool:
    """Return True if `target` is the same as or a descendant of `root`."""
    try:
        target.relative_to(root)
        return True
    except ValueError:
        return False


def _extract_zips_in_dir(dest: Path) -> list[str]:
    """Extract any .zip files at the top level of `dest` in place and remove them.

    The Kaggle SDK does not unzip competition downloads at all, and only unzips
    dataset downloads when the file was freshly fetched — cached/stale zips are
    left on disk. Either case results in a registered dataset that contains a
    zip instead of CSV/parquet, which downstream introspection can't read.

    Returns the list of zip filenames that were successfully extracted. Corrupt
    zips are logged and left in place so the user can inspect them.
    """
    extracted: list[str] = []
    if not dest.is_dir():
        return extracted

    dest_resolved = dest.resolve()
    zip_paths = [p for p in dest.iterdir() if p.is_file() and p.suffix.lower() == ".zip"]

    for zip_path in zip_paths:
        try:
            with zipfile.ZipFile(zip_path) as zf:
                for member in zf.infolist():
                    member_name = member.filename
                    if not member_name:
                        continue
                    if Path(member_name).is_absolute():
                        logger.warning(
                            "Skipping absolute-path zip member %r in %s",
                            member_name, zip_path.name,
                        )
                        continue
                    target = (dest / member_name).resolve()
                    if not _is_within(target, dest_resolved):
                        logger.warning(
                            "Skipping unsafe zip member %r in %s (path escape)",
                            member_name, zip_path.name,
                        )
                        continue
                    zf.extract(member, dest)
        except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
            logger.warning("Failed to extract %s: %s", zip_path.name, exc)
            continue
        try:
            zip_path.unlink()
        except OSError as exc:
            logger.warning("Extracted but could not remove %s: %s", zip_path.name, exc)
        extracted.append(zip_path.name)

    return extracted


def _register_as_dataclaw_dataset(name: str, path: str, description: str) -> str | None:
    """Register a downloaded directory as a dataclaw-data dataset. Returns the dataset ID."""
    if not _auto_register():
        return None
    try:
        from dataclaw_data.registry import create_dataset
        ds = create_dataset(
            name=name,
            ds_type="local_file",
            connection=path,
            description=description,
        )
        return ds.get("id")
    except Exception:
        return None


async def _enable_dataset_for_session(dataset_id: str, session_id: str) -> None:
    """Append a newly created dataset ID to the session's datasetIds allowlist."""
    if not dataset_id or not session_id:
        return
    try:
        from dataclaw.storage.sessions import get_session, update_session
        session = await get_session(session_id)
        if session is None:
            return
        current_ids = session.get("datasetIds")
        if current_ids is None:
            # None means "all datasets allowed" — no action needed
            return
        if dataset_id not in current_ids:
            current_ids.append(dataset_id)
            await update_session(session_id, {"datasetIds": current_ids})
    except Exception:
        pass


def _extract_slug(ref: str) -> str:
    """Extract the competition slug from a ref that may be a full URL."""
    if ref.startswith("https://"):
        return ref.rstrip("/").rsplit("/", 1)[-1]
    return ref


def _serialize_competition(c: Any) -> dict[str, Any]:
    """Turn a Kaggle Competition object into a plain dict."""
    ref = getattr(c, "ref", str(c))
    slug = _extract_slug(ref)
    tags = getattr(c, "tags", None) or []
    tag_names = [getattr(t, "name", str(t)) for t in tags] if tags else []
    return {
        "slug": slug,
        "title": getattr(c, "title", ""),
        "description": getattr(c, "description", ""),
        "category": getattr(c, "category", ""),
        "deadline": str(getattr(c, "deadline", "")),
        "reward": getattr(c, "reward", ""),
        "team_count": getattr(c, "team_count", 0),
        "evaluation_metric": getattr(c, "evaluation_metric", ""),
        "max_daily_submissions": getattr(c, "max_daily_submissions", 0),
        "max_team_size": getattr(c, "max_team_size", 0),
        "tags": tag_names,
        "user_has_entered": getattr(c, "user_has_entered", False),
        "user_rank": getattr(c, "user_rank", None),
        "url": f"https://www.kaggle.com/c/{slug}",
    }


def _serialize_dataset(d: Any) -> dict[str, Any]:
    """Turn a Kaggle Dataset object into a plain dict."""
    ref = getattr(d, "ref", str(d))
    url = ref if ref.startswith("https://") else f"https://www.kaggle.com/datasets/{ref}"
    return {
        "ref": ref,
        "title": getattr(d, "title", ""),
        "size": getattr(d, "total_bytes", 0),
        "download_count": getattr(d, "download_count", 0),
        "last_updated": str(getattr(d, "last_updated", "")),
        "url": url,
    }


# ── Tool implementations ───────────────────────────────────────────────────


async def kaggle_list_competitions(
    search: str = "",
    category: str = "",
    sort_by: str = "latestDeadline",
    page: int = 1,
    **kwargs: Any,
) -> dict[str, Any]:
    """List or search Kaggle competitions."""
    kw: dict[str, Any] = {**_creds(), "sort_by": sort_by, "page": page}
    if search:
        kw["search"] = search
    if category:
        kw["category"] = category
    response = await run_kaggle("competitions_list", **kw)
    items = getattr(response, "competitions", None) or response or []
    competitions = [_serialize_competition(c) for c in items]
    return {"competitions": competitions, "count": len(competitions), "page": page}


async def kaggle_competition_details(
    competition: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """Get detailed information about a Kaggle competition."""
    # Fetch competition metadata via search
    meta_response = await run_kaggle("competitions_list", search=competition, **_creds())
    meta_items = getattr(meta_response, "competitions", None) or meta_response or []
    meta = {}
    for c in meta_items:
        slug = _extract_slug(getattr(c, "ref", ""))
        if slug == competition:
            meta = _serialize_competition(c)
            break

    # Fetch file list for the competition
    response = await run_kaggle("competition_list_files", competition, **_creds())
    raw_files = getattr(response, "files", None) or response or []
    file_list = [
        {"name": getattr(f, "name", str(f)), "size": getattr(f, "total_bytes", 0)}
        for f in raw_files
    ]

    entry = registry.track_competition(competition, {**meta, "files_info": file_list})
    return {
        **meta,
        "slug": competition,
        "url": f"https://www.kaggle.com/c/{competition}",
        "files": file_list,
        "file_count": len(file_list),
    }


async def kaggle_leaderboard(
    competition: str,
    page: int = 1,
    **kwargs: Any,
) -> dict[str, Any]:
    """View the leaderboard for a Kaggle competition."""
    results = await run_kaggle("competition_leaderboard_view", competition, **_creds())
    entries = [
        {
            "rank": idx + 1,
            "team_name": getattr(e, "team_name", str(e)),
            "score": getattr(e, "score", ""),
            "entries": getattr(e, "submissions", 0),
        }
        for idx, e in enumerate(results or [])
    ]
    return {"competition": competition, "leaderboard": entries, "count": len(entries)}


async def kaggle_download_competition(
    competition: str,
    file_name: str = "",
    force: bool = False,
    **kwargs: Any,
) -> dict[str, Any]:
    """Download data files for a Kaggle competition."""
    dest = _competition_dir(competition)

    # Check if already downloaded
    existing = registry.get_competition(competition)
    if _is_valid_cached_download(existing) and not force:
        cached_path = Path(existing["download_path"])
        if _extract_zips_in_dir(cached_path):
            refreshed_files = [f.name for f in cached_path.iterdir() if f.is_file()]
            existing = registry.record_download(
                kind="competitions",
                key=competition,
                download_path=str(cached_path),
                files=refreshed_files,
                dataclaw_dataset_id=existing.get("dataclaw_dataset_id"),
            )
        return {
            "status": "already_downloaded",
            "competition": competition,
            "download_path": existing["download_path"],
            "files": existing.get("files", []),
            "dataclaw_dataset_id": existing.get("dataclaw_dataset_id"),
        }

    try:
        if file_name:
            await run_kaggle(
                "competition_download_file",
                competition,
                file_name,
                path=str(dest),
                force=force,
                **_creds(),
            )
        else:
            await run_kaggle(
                "competition_download_files",
                competition,
                path=str(dest),
                force=force,
                **_creds(),
            )
    except Exception as exc:
        msg = str(exc)
        if "403" in msg or "accept" in msg.lower() or "rules" in msg.lower():
            return {
                "status": "error",
                "error": f"You must accept the competition rules at https://www.kaggle.com/c/{competition}/rules before downloading.",
            }
        return {"status": "error", "error": msg}

    # Unpack any zip files left on disk (Kaggle's competition API never unzips,
    # and dataset_download_files leaves stale zips when not re-fetched).
    _extract_zips_in_dir(dest)

    # List downloaded files
    downloaded_files = [f.name for f in dest.iterdir() if f.is_file()]

    # Register in kaggle registry
    registry.track_competition(competition, {
        "title": competition,
        "url": f"https://www.kaggle.com/c/{competition}",
    })

    # Auto-register with dataclaw-data
    dc_id = _register_as_dataclaw_dataset(
        name=f"Kaggle: {competition}",
        path=str(dest),
        description=f"Competition data from https://www.kaggle.com/c/{competition}",
    )

    entry = registry.record_download(
        kind="competitions",
        key=competition,
        download_path=str(dest),
        files=downloaded_files,
        dataclaw_dataset_id=dc_id,
    )

    # Enable the new dataset for the current session
    if dc_id:
        session_id = kwargs.get("session_id") or kwargs.get("dataclaw_session_id", "")
        await _enable_dataset_for_session(dc_id, session_id)

    return {
        "status": "downloaded",
        "competition": competition,
        "download_path": str(dest),
        "files": downloaded_files,
        "dataclaw_dataset_id": dc_id,
    }


async def kaggle_search_datasets(
    search: str,
    sort_by: str = "hottest",
    file_type: str = "",
    page: int = 1,
    **kwargs: Any,
) -> dict[str, Any]:
    """Search Kaggle datasets by keyword."""
    kw: dict[str, Any] = {**_creds(), "search": search, "sort_by": sort_by, "page": page}
    if file_type:
        kw["file_type"] = file_type
    results = await run_kaggle("dataset_list", **kw)
    datasets = [_serialize_dataset(d) for d in (results or [])]
    return {"datasets": datasets, "count": len(datasets), "page": page}


async def kaggle_download_dataset(
    dataset: str,
    force: bool = False,
    **kwargs: Any,
) -> dict[str, Any]:
    """Download a Kaggle dataset by its ref (owner/dataset-name)."""
    dest = _dataset_dir(dataset)

    # Check if already downloaded
    existing = registry.get_dataset(dataset)
    if _is_valid_cached_download(existing) and not force:
        cached_path = Path(existing["download_path"])
        if _extract_zips_in_dir(cached_path):
            refreshed_files = [f.name for f in cached_path.iterdir() if f.is_file()]
            existing = registry.record_download(
                kind="datasets",
                key=dataset,
                download_path=str(cached_path),
                files=refreshed_files,
                dataclaw_dataset_id=existing.get("dataclaw_dataset_id"),
            )
        return {
            "status": "already_downloaded",
            "dataset": dataset,
            "download_path": existing["download_path"],
            "files": existing.get("files", []),
            "dataclaw_dataset_id": existing.get("dataclaw_dataset_id"),
        }

    try:
        await run_kaggle(
            "dataset_download_files",
            dataset,
            path=str(dest),
            unzip=True,
            force=force,
            **_creds(),
        )
    except Exception as exc:
        return {"status": "error", "error": str(exc)}

    # Catch the case where the SDK left a stale zip (already-cached file path).
    _extract_zips_in_dir(dest)

    downloaded_files = [f.name for f in dest.iterdir() if f.is_file()]

    # Track in registry
    registry.track_dataset(dataset, {
        "title": dataset,
        "url": f"https://www.kaggle.com/datasets/{dataset}",
    })

    # Auto-register with dataclaw-data
    dc_id = _register_as_dataclaw_dataset(
        name=f"Kaggle: {dataset}",
        path=str(dest),
        description=f"Dataset from https://www.kaggle.com/datasets/{dataset}",
    )

    registry.record_download(
        kind="datasets",
        key=dataset,
        download_path=str(dest),
        files=downloaded_files,
        dataclaw_dataset_id=dc_id,
    )

    # Enable the new dataset for the current session
    if dc_id:
        session_id = kwargs.get("session_id") or kwargs.get("dataclaw_session_id", "")
        await _enable_dataset_for_session(dc_id, session_id)

    return {
        "status": "downloaded",
        "dataset": dataset,
        "download_path": str(dest),
        "files": downloaded_files,
        "dataclaw_dataset_id": dc_id,
    }


def _resolve_project_dir(kwargs: dict[str, Any]) -> Path | None:
    """Resolve the active project directory from session context."""
    project_id = kwargs.get("project_id", "")
    if not project_id:
        return None
    try:
        from dataclaw_projects.registry import get_project
        project = get_project(project_id)
        directory = project.get("directory", "")
        return Path(directory) if directory else None
    except Exception:
        return None


async def kaggle_submit(
    competition: str,
    file_path: str,
    message: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """Submit a prediction file to a Kaggle competition."""
    p = Path(file_path)
    if not p.is_absolute():
        project_dir = _resolve_project_dir(kwargs)
        if project_dir:
            p = project_dir / p
    if not p.is_file():
        return {"status": "error", "error": f"File not found: {file_path}"}

    try:
        result = await run_kaggle(
            "competition_submit",
            str(p),
            message,
            competition,
            **_creds(),
        )
    except Exception as exc:
        return {"status": "error", "error": str(exc)}

    resolved_path = str(p)
    entry = registry.record_submission(
        competition=competition,
        file_path=resolved_path,
        message=message,
        result={"status": "submitted"},
    )

    return {
        "status": "submitted",
        "competition": competition,
        "file_path": resolved_path,
        "message": message,
        "submission_id": entry["id"],
        "url": f"https://www.kaggle.com/c/{competition}/submissions",
    }


async def kaggle_submissions(
    competition: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """List your submissions for a Kaggle competition with scores and status."""
    try:
        results = await run_kaggle("competition_submissions", competition, **_creds())
    except Exception as exc:
        return {"status": "error", "error": str(exc)}

    submissions = [
        {
            "ref": getattr(s, "ref", ""),
            "date": str(getattr(s, "date", "")),
            "description": getattr(s, "description", ""),
            "status": str(getattr(s, "status", "")),
            "public_score": getattr(s, "public_score", None),
            "private_score": getattr(s, "private_score", None),
            "file_name": getattr(s, "file_name", ""),
            "submitted_by": getattr(s, "submitted_by", ""),
            "team_name": getattr(s, "team_name", ""),
        }
        for s in (results or [])
    ]
    return {"competition": competition, "submissions": submissions, "count": len(submissions)}
