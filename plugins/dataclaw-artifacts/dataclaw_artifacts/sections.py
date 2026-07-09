"""Typed artifact section contract.

This module is the shared bridge between visualization/dashboarding skills and
artifact rendering. The workspace report helper uses it during the transition
so legacy report sections and first-class artifacts describe the same shapes.
"""

from __future__ import annotations

import hashlib
import html as html_lib
import json
import re
from typing import Any

SECTION_TOKENS = [
    "--dc-bg",
    "--dc-surface",
    "--dc-surface-raised",
    "--dc-surface-muted",
    "--dc-ink",
    "--dc-muted",
    "--dc-line",
    "--dc-accent",
    "--dc-accent-2",
    "--dc-accent-3",
    "--dc-accent-soft",
    "--dc-good",
    "--dc-warn",
    "--dc-danger",
]
SECTION_KINDS = {
    "header",
    "metric_row",
    "chart",
    "table",
    "findings",
    "callout",
    "text",
    "insight_grid",
    "explanation",
    "comparison",
    "checklist",
    "hypothesis_ledger",
    "evidence_trace",
}
SECTION_ALIASES = {
    "kpi": "metric_row",
    "metrics": "metric_row",
    "markdown": "text",
    "insights": "insight_grid",
    "insight_cards": "insight_grid",
    "validation": "checklist",
    "readiness": "checklist",
    "hypotheses": "hypothesis_ledger",
    "evidence": "evidence_trace",
}
DATA_POLICIES = {"narrative", "aggregate_only", "preview"}
CHART_SUMMARY_MAX_BYTES = 200 * 1024
TABLE_PREVIEW_MAX_ROWS = 20
TABLE_PREVIEW_MAX_BYTES = 50 * 1024

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class SectionValidationError(ValueError):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": str(self), "details": self.details}


def normalize_section(section_type: str, data: dict[str, Any]) -> dict[str, Any]:
    kind = canonical_kind(section_type)
    section_id = str(data.get("section_id") or data.get("id") or _stable_section_id(kind, data))
    data_policy = str(data.get("data_policy") or _default_data_policy(kind))
    if data_policy not in DATA_POLICIES:
        raise SectionValidationError(
            "invalid_data_policy",
            f"Unsupported artifact section data_policy: {data_policy}",
            {"allowed": sorted(DATA_POLICIES)},
        )

    payload: dict[str, Any] = {}
    if kind == "chart":
        figure = _figure_from_data(data)
        encoded = json.dumps(figure, default=str).encode("utf-8")
        if len(encoded) > CHART_SUMMARY_MAX_BYTES:
            raise SectionValidationError(
                "chart_summary_too_large",
                f"Chart summary JSON is too large ({len(encoded)} bytes, max {CHART_SUMMARY_MAX_BYTES})",
                {"bytes": len(encoded), "max_bytes": CHART_SUMMARY_MAX_BYTES},
            )
        payload["summary_json_bytes"] = len(encoded)
        payload["series_count"] = len(figure.get("data") or []) if isinstance(figure.get("data"), list) else 0
    elif kind == "metric_row":
        metrics = data.get("metrics", [])
        if not isinstance(metrics, list):
            raise SectionValidationError("invalid_metrics", "metric_row requires list 'metrics'")
        payload["metric_count"] = len(metrics)
    elif kind == "table":
        columns = data.get("columns", [])
        rows = data.get("rows", [])
        if not isinstance(columns, list) or not isinstance(rows, list):
            raise SectionValidationError("invalid_table", "table requires list 'columns' and list 'rows'")
        payload["row_count"] = len(rows)
        payload["preview_max_rows"] = _positive_int(data.get("max_rows"), TABLE_PREVIEW_MAX_ROWS)
        payload["preview_max_bytes"] = _positive_int(data.get("max_bytes"), TABLE_PREVIEW_MAX_BYTES)
    elif kind == "findings":
        items = data.get("items", data.get("findings", []))
        if not isinstance(items, list):
            raise SectionValidationError("invalid_findings", "findings requires list 'items' or 'findings'")
        payload["finding_count"] = len(items)
        payload["items"] = [
            {
                "finding_id": clean_text(item.get("finding_id") or ""),
                "hypothesis_id": clean_text(item.get("hypothesis_id") or ""),
                "title": clean_text(item.get("title") or ""),
                "severity": clean_text(item.get("severity") or ""),
            }
            for item in items
            if isinstance(item, dict)
        ]
    elif kind == "insight_grid":
        items = data.get("items", data.get("insights", []))
        if not isinstance(items, list):
            raise SectionValidationError("invalid_insights", "insight_grid requires list 'items' or 'insights'")
        payload["insight_count"] = len(items)
        payload["items"] = [_ledger_item_summary(item) for item in items if isinstance(item, dict)]
    elif kind == "explanation":
        steps = data.get("steps", data.get("points", []))
        if steps is not None and not isinstance(steps, list):
            raise SectionValidationError("invalid_explanation", "explanation steps/points must be a list")
        payload["step_count"] = len(steps or [])
    elif kind == "comparison":
        groups = data.get("groups", data.get("items", []))
        metrics = data.get("metrics", [])
        if groups is not None and not isinstance(groups, list):
            raise SectionValidationError("invalid_comparison_groups", "comparison groups/items must be a list")
        if metrics is not None and not isinstance(metrics, list):
            raise SectionValidationError("invalid_comparison_metrics", "comparison metrics must be a list")
        payload["group_count"] = len(groups or [])
        payload["metric_count"] = len(metrics or [])
    elif kind == "checklist":
        checks = data.get("checks", data.get("items", []))
        if not isinstance(checks, list):
            raise SectionValidationError("invalid_checklist", "checklist requires list 'checks' or 'items'")
        payload["check_count"] = len(checks)
        payload["statuses"] = sorted({
            clean_text(item.get("status") or item.get("state") or "")
            for item in checks
            if isinstance(item, dict) and clean_text(item.get("status") or item.get("state") or "")
        })
    elif kind == "hypothesis_ledger":
        hypotheses = data.get("hypotheses", data.get("items", []))
        if not isinstance(hypotheses, list):
            raise SectionValidationError("invalid_hypotheses", "hypothesis_ledger requires list 'hypotheses' or 'items'")
        payload["hypothesis_count"] = len(hypotheses)
        payload["items"] = [_ledger_item_summary(item) for item in hypotheses if isinstance(item, dict)]
    elif kind == "evidence_trace":
        items = data.get("evidence", data.get("items", []))
        if not isinstance(items, list):
            raise SectionValidationError("invalid_evidence", "evidence_trace requires list 'evidence' or 'items'")
        payload["evidence_count"] = len(items)
        payload["items"] = [_ledger_item_summary(item) for item in items if isinstance(item, dict)]

    return {
        "section_id": section_id,
        "section_schema": 2,
        "kind": kind,
        "title": clean_text(data.get("title") or ""),
        "caption": clean_text(data.get("caption") or ""),
        "plan_step_id": clean_text(data.get("plan_step_id") or ""),
        "data_policy": data_policy,
        "payload": payload,
        "tokens": SECTION_TOKENS,
    }


def canonical_kind(section_type: str) -> str:
    kind = section_type.strip().lower()
    kind = SECTION_ALIASES.get(kind, kind)
    if kind not in SECTION_KINDS:
        raise SectionValidationError(
            "unsupported_section_type",
            f"Unsupported artifact section_type: {section_type}",
            {"allowed": sorted(SECTION_KINDS | set(SECTION_ALIASES))},
        )
    return kind


def section_attrs(section: dict[str, Any]) -> str:
    attrs = {
        "data-dc-section": section.get("kind", ""),
        "data-dc-section-id": section.get("section_id", ""),
        "data-dc-plan-step-id": section.get("plan_step_id", ""),
        "data-dc-data-policy": section.get("data_policy", ""),
    }
    return " ".join(
        f'{name}="{html_lib.escape(str(value), quote=True)}"'
        for name, value in attrs.items()
        if value
    )


def section_meta_script(section: dict[str, Any]) -> str:
    payload = json.dumps(section, default=str).replace("</", "<\\/")
    return f'<script type="application/json" data-dc-section-meta>{payload}</script>'


def clean_text(value: Any) -> str:
    return _CONTROL_CHARS.sub("?", "" if value is None else str(value))


def _figure_from_data(data: dict[str, Any]) -> dict[str, Any]:
    figure = data.get("figure")
    if not figure and data.get("figure_json"):
        try:
            figure = json.loads(str(data["figure_json"]))
        except Exception as exc:
            raise SectionValidationError("invalid_chart_json", "chart figure_json is not valid JSON") from exc
    if not isinstance(figure, dict):
        raise SectionValidationError("invalid_chart", "chart requires 'figure' dict or 'figure_json'")
    return figure


def _stable_section_id(kind: str, data: dict[str, Any]) -> str:
    seed = {
        "kind": kind,
        "title": data.get("title") or "",
        "caption": data.get("caption") or "",
        "plan_step_id": data.get("plan_step_id") or "",
        "key": data.get("semantic_key") or data.get("slug") or "",
    }
    if not seed["key"]:
        seed["content"] = data
    digest = hashlib.sha256(json.dumps(seed, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:10]
    return f"sec-{kind}-{digest}"


def _ledger_item_summary(item: dict[str, Any]) -> dict[str, str]:
    return {
        "finding_id": clean_text(item.get("finding_id") or ""),
        "hypothesis_id": clean_text(item.get("hypothesis_id") or item.get("id") or ""),
        "title": clean_text(item.get("title") or item.get("statement") or item.get("name") or ""),
        "status": clean_text(item.get("status") or item.get("state") or ""),
        "severity": clean_text(item.get("severity") or ""),
    }


def _default_data_policy(kind: str) -> str:
    if kind in {
        "header",
        "callout",
        "text",
        "findings",
        "insight_grid",
        "explanation",
        "checklist",
        "hypothesis_ledger",
        "evidence_trace",
    }:
        return "narrative"
    if kind in {"table", "comparison"}:
        return "preview"
    return "aggregate_only"


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default
