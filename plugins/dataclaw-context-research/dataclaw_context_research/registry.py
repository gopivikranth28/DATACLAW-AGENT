"""Persistent findings registry for context research."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dataclaw.config.paths import plugin_data_dir


def context_root() -> Path:
    return plugin_data_dir("context-research")


def findings_path() -> Path:
    return context_root() / "findings.json"


def programs_path() -> Path:
    return context_root() / "programs.json"


def cache_dir() -> Path:
    path = context_root() / "cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_findings() -> list[dict[str, Any]]:
    path = findings_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def write_findings(findings: list[dict[str, Any]]) -> None:
    path = findings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(findings, indent=2, default=str), encoding="utf-8")


def save_findings(new_findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    existing = read_findings()
    by_key = {_dedupe_key(item): item for item in existing}
    saved: list[dict[str, Any]] = []
    for finding in new_findings:
        item = dict(finding)
        item.setdefault("id", f"finding-{uuid.uuid4().hex[:10]}")
        item.setdefault("retrieved_at", now_iso())
        key = _dedupe_key(item)
        if key in by_key:
            merged = {**by_key[key], **item, "id": by_key[key].get("id", item["id"])}
            by_key[key] = merged
            saved.append(merged)
        else:
            by_key[key] = item
            saved.append(item)
    write_findings(list(by_key.values()))
    return saved


def filter_findings(
    *,
    dataset_id: str = "",
    finding_ids: list[str] | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    findings = read_findings()
    if dataset_id:
        findings = [f for f in findings if f.get("dataset_id") == dataset_id]
    if finding_ids:
        wanted = set(finding_ids)
        findings = [f for f in findings if f.get("id") in wanted]
    findings.sort(key=lambda item: item.get("retrieved_at", ""), reverse=True)
    if limit is not None:
        findings = findings[: max(0, limit)]
    return findings


def mark_saved_to_okf(finding_ids: list[str], bundle_id: str) -> None:
    wanted = set(finding_ids)
    findings = []
    for finding in read_findings():
        if finding.get("id") in wanted:
            finding = {**finding, "accepted_for_okf": True, "okf_bundle_id": bundle_id}
        findings.append(finding)
    write_findings(findings)


def read_programs() -> list[dict[str, Any]]:
    path = programs_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def write_programs(programs: list[dict[str, Any]]) -> None:
    path = programs_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(programs, indent=2, default=str), encoding="utf-8")


def save_program(program: dict[str, Any]) -> dict[str, Any]:
    item = dict(program)
    item.setdefault("id", f"program-{uuid.uuid4().hex[:10]}")
    item.setdefault("created_at", now_iso())
    item["updated_at"] = now_iso()
    programs = read_programs()
    for idx, existing in enumerate(programs):
        if existing.get("id") == item["id"]:
            programs[idx] = item
            write_programs(programs)
            return item
    programs.insert(0, item)
    write_programs(programs)
    return item


def find_program(program_id: str) -> dict[str, Any]:
    for program in read_programs():
        if program.get("id") == program_id:
            return program
    raise ValueError(f"Research program not found: {program_id}")


def filter_programs(*, dataset_id: str = "", limit: int = 20) -> list[dict[str, Any]]:
    programs = read_programs()
    if dataset_id:
        programs = [p for p in programs if p.get("dataset_id") == dataset_id]
    programs.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
    return programs[: max(0, int(limit))]


def _dedupe_key(finding: dict[str, Any]) -> str:
    return str(finding.get("url") or f"{finding.get('source')}:{finding.get('title')}:{finding.get('query')}")
