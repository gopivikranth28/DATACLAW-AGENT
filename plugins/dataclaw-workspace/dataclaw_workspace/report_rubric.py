"""Loader for the report rubric — the canonical machine-readable report standard.

The rubric (report_rubric.yaml) is the single source of truth for what a good
dataclaw report is: gate thresholds, criteria severities, and which criteria are
live versus deferred. The quality gate, the storyboard designer, and (eventually)
the self-critique loop all read the same file so the standard cannot drift
between how a report is written, critiqued, and judged.

See docs/report-builder-architecture.md, Appendix A, for the full specification.
"""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_RUBRIC_PATH = Path(__file__).with_name("report_rubric.yaml")

_REQUIRED_CRITERION_FIELDS = {"id", "axis", "severity", "status", "scope", "signal", "remediable", "on_fail", "remediation", "rationale"}
_VALID_AXES = {"rigor", "narrative", "integrity"}
_VALID_SEVERITIES = {"fail", "warn"}
_VALID_STATUSES = {"live", "deferred"}


class RubricError(ValueError):
    """The rubric file is missing, malformed, or internally inconsistent."""


@lru_cache(maxsize=1)
def load_report_rubric() -> dict[str, Any]:
    """Load and validate the rubric. Cached; treat the returned dict as read-only."""
    try:
        raw = _RUBRIC_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise RubricError(f"report rubric not found at {_RUBRIC_PATH}: {exc}") from exc
    rubric = yaml.safe_load(raw)
    _validate(rubric)
    return rubric


def _validate(rubric: Any) -> None:
    if not isinstance(rubric, dict):
        raise RubricError("rubric root must be a mapping")
    version = rubric.get("rubric_version")
    if not isinstance(version, int) or version < 1:
        raise RubricError("rubric_version must be a positive integer")
    thresholds = rubric.get("thresholds")
    if not isinstance(thresholds, dict):
        raise RubricError("rubric must define a thresholds mapping")
    for key, value in thresholds.items():
        # bool is an int subclass; a YAML true/false is never a valid threshold.
        if not isinstance(value, int) or isinstance(value, bool):
            raise RubricError(f"threshold {key!r} must be an integer, got {value!r}")
    criteria = rubric.get("criteria")
    if not isinstance(criteria, list) or not criteria:
        raise RubricError("rubric must define a non-empty criteria list")
    seen: set[str] = set()
    for criterion in criteria:
        if not isinstance(criterion, dict):
            raise RubricError("every criterion must be a mapping")
        missing = _REQUIRED_CRITERION_FIELDS - criterion.keys()
        if missing:
            raise RubricError(f"criterion {criterion.get('id')!r} missing fields: {sorted(missing)}")
        cid = criterion["id"]
        if cid in seen:
            raise RubricError(f"duplicate criterion id {cid!r}")
        seen.add(cid)
        if criterion["axis"] not in _VALID_AXES:
            raise RubricError(f"criterion {cid!r} has invalid axis {criterion['axis']!r}")
        if criterion["severity"] not in _VALID_SEVERITIES:
            raise RubricError(f"criterion {cid!r} has invalid severity {criterion['severity']!r}")
        if criterion["status"] not in _VALID_STATUSES:
            raise RubricError(f"criterion {cid!r} has invalid status {criterion['status']!r}")
    # Second pass: a replaced criterion must not exist anywhere in the file,
    # regardless of declaration order.
    for criterion in criteria:
        replaces = criterion.get("replaces")
        if replaces is not None and (not isinstance(replaces, str) or replaces in seen):
            raise RubricError(f"criterion {criterion['id']!r} has invalid replaces {replaces!r}")


def rubric_version() -> int:
    return load_report_rubric()["rubric_version"]


def rubric_thresholds() -> dict[str, int]:
    # Copies: the loader's cache is process-wide, so a caller mutation must
    # never poison the rubric for everyone else.
    return dict(load_report_rubric()["thresholds"])


def rubric_criteria() -> dict[str, dict[str, Any]]:
    """All criteria keyed by id, in file order."""
    return {criterion["id"]: deepcopy(criterion) for criterion in load_report_rubric()["criteria"]}


def live_criterion_ids() -> list[str]:
    """Ids of the criteria the gate enforces today, in file order."""
    return [c["id"] for c in load_report_rubric()["criteria"] if c["status"] == "live"]
