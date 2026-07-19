"""Append-only store for analysis review runs and findings."""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dataclaw.config.paths import workspaces_dir

SCOPES = {"plan_step", "artifact", "living_report", "session"}
REVIEWER_TYPES = {"checklist", "subagent", "mixed"}
SEVERITIES = {"info", "warning", "required"}
SEVERITY_RANK = {"info": 0, "warning": 1, "required": 2}
CATEGORIES = {
    "unsupported_claim",
    "data_quality_caveat",
    "denominator_grain",
    "query_risk",
    "modeling_comparability",
    "reproducibility_gap",
    "misleading_visualization",
    "broken_link",
    "security_export_risk",
    "hypothesis_hygiene",
}
FINDING_STATUSES = {"open", "resolved", "accepted_with_rationale", "dismissed_as_not_applicable"}
FINAL_FINDING_STATUSES = {"resolved", "accepted_with_rationale", "dismissed_as_not_applicable"}
GATE_STATUSES = {"pass", "fail", "unknown"}

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_review_id() -> str:
    return f"rev-{uuid.uuid4().hex[:8]}"


def new_finding_id() -> str:
    return f"rvf-{uuid.uuid4().hex[:8]}"


def safe_session_id(session_id: str | None) -> str:
    raw = (session_id or "default").strip() or "default"
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in raw)


def review_root() -> Path:
    path = workspaces_dir() / "analysis-review"
    path.mkdir(parents=True, exist_ok=True)
    return path


def events_file(session_id: str | None = "default") -> Path:
    path = review_root() / safe_session_id(session_id) / "review_events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _path_lock(path: Path) -> threading.Lock:
    key = str(path)
    with _locks_guard:
        lock = _locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _locks[key] = lock
        return lock


def append_event(record: dict[str, Any], session_id: str | None = "default") -> None:
    path = events_file(session_id)
    encoded = json.dumps(record, sort_keys=True, default=str)
    with _path_lock(path):
        with open(path, "a", encoding="utf-8") as f:
            f.write(encoded + "\n")
            f.flush()
            os.fsync(f.fileno())


def read_events(session_id: str | None = "default") -> list[dict[str, Any]]:
    path = events_file(session_id)
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def append_review_run(record: dict[str, Any], session_id: str | None = "default") -> None:
    append_event({"record_type": "review_run", **record}, session_id)


def append_review_finding(record: dict[str, Any], session_id: str | None = "default") -> None:
    append_event({"record_type": "review_finding", **record}, session_id)


def append_finding_resolution(record: dict[str, Any], session_id: str | None = "default") -> None:
    append_event({"record_type": "review_finding_resolution", **record}, session_id)


def normalize_scope(scope: str) -> str:
    normalized = str(scope or "").strip()
    if normalized not in SCOPES:
        raise ValueError(f"Unsupported review scope: {scope}")
    return normalized


def normalize_target(scope: str, target_id: str | None, *, plan_step_id: str = "", session_id: str = "default") -> str:
    if scope == "plan_step":
        target = str(plan_step_id or target_id or "").strip()
    elif scope == "session":
        target = str(target_id or session_id or "default").strip()
    else:
        target = str(target_id or "").strip()
    if not target:
        raise ValueError(f"target_id is required for review scope {scope}")
    return target


def normalize_severity(severity: str) -> str:
    normalized = str(severity or "warning").strip()
    return normalized if normalized in SEVERITIES else "warning"


def severity_at_least(severity: str, floor: str) -> bool:
    return SEVERITY_RANK[normalize_severity(severity)] >= SEVERITY_RANK[normalize_severity(floor)]


def fold_review_runs(session_id: str | None = "default") -> list[dict[str, Any]]:
    runs: dict[str, dict[str, Any]] = {}
    for event in read_events(session_id):
        if event.get("record_type") != "review_run":
            continue
        review_id = str(event.get("review_id") or "")
        if not review_id:
            continue
        run = dict(event)
        run.setdefault("finding_ids", [])
        runs[review_id] = run
    return sorted(runs.values(), key=lambda r: str(r.get("created_at") or ""))


def fold_review_findings(session_id: str | None = "default") -> list[dict[str, Any]]:
    findings: dict[str, dict[str, Any]] = {}
    for event in read_events(session_id):
        record_type = event.get("record_type")
        finding_id = str(event.get("finding_id") or "")
        if not finding_id:
            continue
        if record_type == "review_finding":
            finding = dict(event)
            finding.setdefault("status", "open")
            finding.setdefault("history", [])
            findings[finding_id] = finding
            continue
        if record_type != "review_finding_resolution":
            continue
        current = findings.get(finding_id)
        if current is None:
            continue
        current["status"] = event.get("status") or current.get("status") or "open"
        current["resolved_at"] = event.get("created_at") or ""
        current["resolution_rationale"] = event.get("rationale") or ""
        current["resolution_evidence_link"] = event.get("evidence_link") or ""
        current.setdefault("history", []).append(event)
    return sorted(findings.values(), key=lambda f: str(f.get("created_at") or ""))


def find_review_finding(finding_id: str, session_id: str | None = "default") -> dict[str, Any] | None:
    return next((f for f in fold_review_findings(session_id) if f.get("finding_id") == finding_id), None)


def filter_runs(
    runs: list[dict[str, Any]],
    *,
    scope: str | None = None,
    target_id: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    filtered = runs
    if scope:
        filtered = [r for r in filtered if r.get("scope") == scope]
    if target_id:
        filtered = [r for r in filtered if r.get("target_id") == target_id]
    if status:
        filtered = [r for r in filtered if r.get("status") == status]
    return filtered


def filter_findings(
    findings: list[dict[str, Any]],
    *,
    scope: str | None = None,
    target_id: str | None = None,
    status: str | None = None,
    severity: str | None = None,
    category: str | None = None,
) -> list[dict[str, Any]]:
    filtered = findings
    if scope:
        filtered = [f for f in filtered if f.get("scope") == scope]
    if target_id:
        filtered = [f for f in filtered if f.get("target_id") == target_id]
    if status:
        filtered = [f for f in filtered if f.get("status") == status]
    if severity:
        filtered = [f for f in filtered if f.get("severity") == severity]
    if category:
        filtered = [f for f in filtered if f.get("category") == category]
    return filtered


def open_required_findings(
    *,
    scope: str,
    target_id: str,
    session_id: str | None = "default",
) -> list[dict[str, Any]]:
    return [
        finding
        for finding in filter_findings(fold_review_findings(session_id), scope=scope, target_id=target_id, status="open")
        if finding.get("severity") == "required"
    ]


def latest_review_run(*, scope: str, target_id: str, session_id: str | None = "default") -> dict[str, Any] | None:
    runs = filter_runs(fold_review_runs(session_id), scope=scope, target_id=target_id)
    return runs[-1] if runs else None
