"""Agent tools for OKF bundles."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from dataclaw_okf.generator import generate_bundle, is_bundle_stale
from dataclaw_okf.registry import exports_root, find_bundle, read_bundles


MAX_FILE_CHARS = 12000


async def okf_generate_bundle(
    *,
    dataset_id: str,
    force: bool = False,
    **kwargs: Any,
) -> dict[str, Any]:
    """Generate an OKF bundle from a registered dataset."""
    return _summarize_bundle(generate_bundle(dataset_id, force=force))


async def okf_list_bundles(**kwargs: Any) -> dict[str, Any]:
    """List OKF bundles with staleness indicators."""
    bundles = []
    for bundle in read_bundles():
        bundles.append(_summarize_bundle({**bundle, "stale": is_bundle_stale(bundle)}))
    return {"bundles": bundles, "count": len(bundles)}


async def okf_read_bundle(
    *,
    bundle_id: str,
    path: str = "",
    **kwargs: Any,
) -> dict[str, Any]:
    """Read a bundle index or one markdown file."""
    bundle = find_bundle(bundle_id)
    root = Path(str(bundle.get("path", "")))
    if not path:
        return {
            "bundle": _summarize_bundle({**bundle, "stale": is_bundle_stale(bundle)}),
            "files": bundle.get("files", []),
        }
    file_path = _resolve_bundle_file(root, path)
    content = file_path.read_text(encoding="utf-8")
    truncated = len(content) > MAX_FILE_CHARS
    return {
        "bundle_id": bundle_id,
        "path": str(file_path.relative_to(root)),
        "content": content[:MAX_FILE_CHARS],
        "truncated": truncated,
    }


async def okf_search_bundle(
    *,
    bundle_id: str,
    query: str,
    limit: int = 10,
    **kwargs: Any,
) -> dict[str, Any]:
    """Keyword search markdown files in a bundle."""
    bundle = find_bundle(bundle_id)
    root = Path(str(bundle.get("path", "")))
    terms = [t.lower() for t in query.split() if t.strip()]
    if not terms:
        return {"matches": [], "count": 0}

    matches = []
    for rel in bundle.get("files", []):
        path = _resolve_bundle_file(root, str(rel))
        text = path.read_text(encoding="utf-8")
        lower = text.lower()
        score = sum(lower.count(term) for term in terms)
        if score <= 0:
            continue
        snippet = _snippet(text, terms)
        matches.append({"path": rel, "score": score, "snippet": snippet})

    matches.sort(key=lambda item: item["score"], reverse=True)
    capped = matches[: max(1, int(limit))]
    return {"matches": capped, "count": len(capped), "total_matches": len(matches)}


async def okf_export_bundle(
    *,
    bundle_id: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """Create a zip archive for a bundle."""
    bundle = find_bundle(bundle_id)
    root = Path(str(bundle.get("path", "")))
    if not root.exists():
        raise ValueError(f"OKF bundle files are missing: {bundle_id}")
    archive_base = exports_root() / bundle_id
    archive = shutil.make_archive(str(archive_base), "zip", root_dir=root)
    return {
        "bundle_id": bundle_id,
        "archive_path": archive,
        "file_count": bundle.get("file_count", 0),
    }


def _summarize_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": bundle.get("id"),
        "dataset_id": bundle.get("dataset_id"),
        "dataset_name": bundle.get("dataset_name"),
        "path": bundle.get("path"),
        "created_at": bundle.get("created_at"),
        "updated_at": bundle.get("updated_at"),
        "source_hash": bundle.get("source_hash"),
        "file_count": bundle.get("file_count", 0),
        "format": bundle.get("format", "okf-v0.1-markdown"),
        "status": bundle.get("status"),
        "stale": bool(bundle.get("stale", False)),
    }


def _resolve_bundle_file(root: Path, rel: str) -> Path:
    if not root.exists():
        raise ValueError(f"OKF bundle path is missing: {root}")
    target = (root / rel).resolve()
    root_resolved = root.resolve()
    try:
        target.relative_to(root_resolved)
    except ValueError:
        raise ValueError(f"Path escapes OKF bundle: {rel}")
    if not target.is_file():
        raise ValueError(f"OKF file not found: {rel}")
    return target


def _snippet(text: str, terms: list[str]) -> str:
    lower = text.lower()
    idx = min([lower.find(t) for t in terms if lower.find(t) >= 0] or [0])
    start = max(0, idx - 120)
    end = min(len(text), idx + 280)
    return text[start:end].replace("\n", " ").strip()
