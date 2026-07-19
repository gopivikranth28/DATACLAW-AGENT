"""Evidence helpers for EDA finding anchors."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

TABLE_PREVIEW_MAX_ROWS = 20
TABLE_PREVIEW_MAX_BYTES = 50 * 1024

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_last_notebook_anchor: dict[str, dict[str, Any]] = {}


def source_sha256(source: str) -> str:
    return hashlib.sha256((source or "").encode("utf-8")).hexdigest()


def stash_notebook_anchor(session_id: str, result: dict[str, Any]) -> None:
    cell_id = str(result.get("cell_id") or "")
    source = str(result.get("source") or "")
    if not cell_id or not source:
        return
    _last_notebook_anchor[session_id or "default"] = {
        "kind": "notebook_cell",
        "cell_id": cell_id,
        "cell_index": result.get("cell_index"),
        "source_sha256": result.get("source_sha256") or source_sha256(source),
        "stale": False,
    }


def last_notebook_anchor(session_id: str) -> dict[str, Any] | None:
    anchor = _last_notebook_anchor.get(session_id or "default")
    return dict(anchor) if anchor else None


def normalize_evidence(evidence: Any, *, session_id: str = "default") -> list[dict[str, Any]]:
    if evidence in (None, "", []):
        anchors: list[dict[str, Any]] = []
    elif isinstance(evidence, list):
        anchors = [a for a in evidence if isinstance(a, dict)]
    elif isinstance(evidence, dict):
        if "anchors" in evidence and isinstance(evidence["anchors"], list):
            anchors = [a for a in evidence["anchors"] if isinstance(a, dict)]
        else:
            anchors = [evidence]
    else:
        anchors = [{"kind": "interpretive_note", "text": clean_text(str(evidence))}]

    if not any(a.get("kind") == "notebook_cell" for a in anchors):
        stashed = last_notebook_anchor(session_id)
        if stashed is not None:
            anchors.insert(0, stashed)

    return [_normalize_anchor(anchor) for anchor in anchors]


def has_evidence_ref(evidence: list[dict[str, Any]]) -> bool:
    for anchor in evidence:
        kind = anchor.get("kind")
        if kind == "notebook_cell" and anchor.get("cell_id") and anchor.get("source_sha256"):
            return True
        if kind in {"artifact_section", "dataset_profile", "query_card"} and anchor.get("id"):
            return True
        if kind == "inline_summary" and anchor.get("summary"):
            return True
        if kind == "interpretive_note" and anchor.get("text"):
            return True
    return False


def evidence_refs(evidence: list[dict[str, Any]]) -> list[str]:
    refs: list[str] = []
    for anchor in evidence:
        kind = str(anchor.get("kind") or "")
        if kind == "notebook_cell":
            refs.append(f"notebook_cell:{anchor.get('cell_id')}")
        elif kind in {"artifact_section", "dataset_profile", "query_card"}:
            refs.append(f"{kind}:{anchor.get('id')}")
        elif kind == "inline_summary":
            refs.append("inline_summary")
        elif kind == "interpretive_note":
            refs.append("interpretive_note")
    return [ref for ref in refs if not ref.endswith(":")]


def clean_text(value: Any) -> str:
    return _CONTROL_CHARS.sub("?", "" if value is None else str(value))


def _normalize_anchor(anchor: dict[str, Any]) -> dict[str, Any]:
    kind = str(anchor.get("kind") or anchor.get("type") or "interpretive_note")
    if kind == "notebook_cell":
        return {
            "kind": "notebook_cell",
            "cell_id": clean_text(anchor.get("cell_id") or ""),
            "cell_index": anchor.get("cell_index"),
            "source_sha256": clean_text(anchor.get("source_sha256") or ""),
            "stale": bool(anchor.get("stale", False)),
        }
    if kind in {"artifact_section", "dataset_profile", "query_card"}:
        return {
            "kind": kind,
            "id": clean_text(anchor.get("id") or anchor.get(f"{kind}_id") or ""),
            "title": clean_text(anchor.get("title") or ""),
            "stale": bool(anchor.get("stale", False)),
        }
    if kind == "inline_summary":
        summary = _cap_inline_summary(anchor.get("summary", anchor.get("data", {})))
        return {
            "kind": "inline_summary",
            "summary": summary,
            "rows": anchor.get("rows"),
            "preview_max_rows": TABLE_PREVIEW_MAX_ROWS,
            "preview_max_bytes": TABLE_PREVIEW_MAX_BYTES,
        }
    return {"kind": "interpretive_note", "text": clean_text(anchor.get("text") or anchor.get("note") or "")}


def _cap_inline_summary(value: Any) -> Any:
    if isinstance(value, list):
        value = value[:TABLE_PREVIEW_MAX_ROWS]
    encoded = json.dumps(value, default=str)
    if len(encoded.encode("utf-8")) <= TABLE_PREVIEW_MAX_BYTES:
        return _clean_json(value)
    truncated = encoded.encode("utf-8")[:TABLE_PREVIEW_MAX_BYTES].decode("utf-8", errors="ignore")
    return {"truncated": True, "preview": clean_text(truncated)}


def _clean_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {clean_text(k): _clean_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean_json(v) for v in value]
    if isinstance(value, str):
        return clean_text(value)
    return value
