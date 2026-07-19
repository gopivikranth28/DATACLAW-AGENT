"""Append-only stores for structured EDA ledgers."""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dataclaw.config.paths import workspaces_dir

HYPOTHESIS_SOURCES = {
    "user_goal",
    "mode_expected_risk",
    "domain_prior",
    "data_signal",
    "prior_finding",
    "reviewer",
}
HYPOTHESIS_PRIORITIES = {"high", "medium", "low"}
HYPOTHESIS_STATUSES = {
    "open",
    "testing",
    "confirmed",
    "rejected",
    "unresolved_needs_domain_input",
    "out_of_scope",
}
FINDING_TYPES = {
    "distribution",
    "missingness",
    "outlier",
    "segment_difference",
    "correlation_candidate",
    "leakage_risk",
    "readiness",
    "rejected_hypothesis",
    "data_quality",
    "caveat",
}
FINDING_DISPOSITIONS = {"confirmed", "weakened", "rejected", "unresolved", "blocked"}
FINDING_STATUSES = {"active", "superseded"}
SEVERITIES = {"info", "warning", "blocker"}
CONFIDENCES = {"low", "medium", "high"}
INTERNAL_VALIDATION_STATUSES = {"validated", "failed", "not_checked"}
EXTERNAL_VALIDATION_STATUSES = {"validated", "unverified", "implausible", "not_checked"}
EXTERNAL_VALIDATION_BASES = {"domain_prior", "reference_lookup", "user_confirmation", "none"}
SELECTION_CORRECTIONS = {"none", "fdr_bh", "bonferroni", "holdout_confirmed"}

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_hypothesis_id() -> str:
    return f"hyp-{uuid.uuid4().hex[:8]}"


def new_finding_id() -> str:
    return f"eda-{uuid.uuid4().hex[:8]}"


def safe_session_id(session_id: str | None) -> str:
    raw = (session_id or "default").strip() or "default"
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in raw)


def session_dir(session_id: str | None = "default") -> Path:
    path = workspaces_dir() / "eda" / "findings" / safe_session_id(session_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def hypotheses_file(session_id: str | None = "default") -> Path:
    return session_dir(session_id) / "hypotheses.jsonl"


def findings_file(session_id: str | None = "default") -> Path:
    return session_dir(session_id) / "findings.jsonl"


def _path_lock(path: Path) -> threading.Lock:
    key = str(path)
    with _locks_guard:
        lock = _locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _locks[key] = lock
        return lock


def append_record(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(record, sort_keys=True, default=str)
    with _path_lock(path):
        with open(path, "a", encoding="utf-8") as f:
            f.write(encoded + "\n")
            f.flush()
            os.fsync(f.fileno())


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def append_hypothesis(record: dict[str, Any], session_id: str | None = "default") -> None:
    append_record(hypotheses_file(session_id), record)


def append_finding(record: dict[str, Any], session_id: str | None = "default") -> None:
    append_record(findings_file(session_id), record)


def hypothesis_events(session_id: str | None = "default") -> list[dict[str, Any]]:
    return read_jsonl(hypotheses_file(session_id))


def finding_events(session_id: str | None = "default") -> list[dict[str, Any]]:
    return read_jsonl(findings_file(session_id))


def fold_hypotheses(session_id: str | None = "default") -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for event in hypothesis_events(session_id):
        event_type = event.get("record_type")
        hypothesis_id = str(event.get("hypothesis_id") or "")
        if not hypothesis_id:
            continue
        if event_type == "hypothesis":
            current = dict(event)
            current.setdefault("status", "open")
            current.setdefault("linked_finding_ids", [])
            current.setdefault("history", [])
            current.setdefault("needs_reevaluation", False)
            by_id[hypothesis_id] = current
            continue
        if event_type != "hypothesis_update":
            continue
        current = by_id.setdefault(
            hypothesis_id,
            {
                "record_type": "hypothesis",
                "hypothesis_id": hypothesis_id,
                "statement": "",
                "rationale": "",
                "source": "",
                "priority": "medium",
                "status": "open",
                "linked_finding_ids": [],
                "history": [],
                "needs_reevaluation": False,
            },
        )
        prior_status = current.get("status")
        if event.get("status"):
            current["status"] = event["status"]
        if event.get("priority"):
            current["priority"] = event["priority"]
        linked = list(current.get("linked_finding_ids") or [])
        for finding_id in event.get("linked_finding_ids") or []:
            if finding_id and finding_id not in linked:
                linked.append(finding_id)
        current["linked_finding_ids"] = linked
        if event.get("needs_reevaluation"):
            current["needs_reevaluation"] = True
        if event.get("loop_index") is not None:
            current["loop_index"] = event.get("loop_index")
        if event.get("disposition_reason") is not None:
            current["disposition_reason"] = event.get("disposition_reason", "")
        if prior_status and event.get("status") and prior_status != event.get("status"):
            current["previous_status"] = prior_status
        current.setdefault("history", []).append(event)
    return sorted(by_id.values(), key=lambda h: str(h.get("created_at") or ""))


def fold_findings(session_id: str | None = "default") -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for event in finding_events(session_id):
        event_type = event.get("record_type")
        finding_id = str(event.get("finding_id") or "")
        if not finding_id:
            continue
        if event_type == "finding":
            record = dict(event)
            record.setdefault("status", "active")
            record.setdefault("superseded_by", "")
            record.setdefault("supersede_reason", "")
            by_id[finding_id] = record
        elif event_type == "supersede":
            current = by_id.get(finding_id)
            if current is None:
                continue
            current["status"] = "superseded"
            current["superseded_by"] = event.get("replacement_id") or ""
            current["supersede_reason"] = event.get("reason") or ""
            current["superseded_at"] = event.get("created_at") or ""
    return sorted(by_id.values(), key=lambda f: str(f.get("created_at") or ""))


def find_hypothesis(hypothesis_id: str, session_id: str | None = "default") -> dict[str, Any] | None:
    return next((h for h in fold_hypotheses(session_id) if h.get("hypothesis_id") == hypothesis_id), None)


def find_finding(finding_id: str, session_id: str | None = "default") -> dict[str, Any] | None:
    return next((f for f in fold_findings(session_id) if f.get("finding_id") == finding_id), None)


def active_findings(session_id: str | None = "default") -> list[dict[str, Any]]:
    return [f for f in fold_findings(session_id) if f.get("status") == "active"]


def filter_records(records: list[dict[str, Any]], **filters: Any) -> list[dict[str, Any]]:
    filtered = records
    for key, value in filters.items():
        if value in (None, ""):
            continue
        if isinstance(value, (list, tuple, set)):
            wanted = {str(v) for v in value}
            filtered = [r for r in filtered if str(r.get(key) or "") in wanted]
        else:
            filtered = [r for r in filtered if str(r.get(key) or "") == str(value)]
    return filtered
