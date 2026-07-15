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
    "narrative_band",
    "methodology_block",
    "evidence_rail",
    "ledger_timeline",
    "chart_interpretation",
    "hypothesis_ledger",
    "evidence_trace",
    "filterable_chart",
    "interactive_table",
    "selector_panel",
    "chart_table_explorer",
    "entity_card_grid",
}
SECTION_ALIASES = {
    "kpi": "metric_row",
    "metrics": "metric_row",
    "markdown": "text",
    "insights": "insight_grid",
    "insight_cards": "insight_grid",
    "validation": "checklist",
    "readiness": "checklist",
    "narrative": "narrative_band",
    "story_band": "narrative_band",
    "methodology": "methodology_block",
    "method": "methodology_block",
    "evidence": "evidence_trace",
    "evidence_panel": "evidence_rail",
    "timeline": "ledger_timeline",
    "ledger": "ledger_timeline",
    "chart_story": "chart_interpretation",
    "chart_plus_interpretation": "chart_interpretation",
    "hypotheses": "hypothesis_ledger",
    "data_table": "interactive_table",
    "filter_panel": "selector_panel",
    "explorer": "chart_table_explorer",
    "chart_explorer": "chart_table_explorer",
    "card_grid": "entity_card_grid",
    "entity_cards": "entity_card_grid",
    "archetype_cards": "entity_card_grid",
}
DATA_POLICIES = {"narrative", "aggregate_only", "preview"}
CHART_SUMMARY_MAX_BYTES = 200 * 1024
TABLE_PREVIEW_MAX_ROWS = 20
TABLE_PREVIEW_MAX_BYTES = 50 * 1024
INTERACTIVE_DATA_MAX_ROWS = 500
INTERACTIVE_DATA_MAX_BYTES = 160 * 1024
DISPLAY_FACT_USES = {"pill", "scan_point", "example", "annotation"}
DISPLAY_FACT_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,119}$")

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
    semantic_role = clean_text(data.get("semantic_role") or data.get("content_role") or data.get("semantic_intent") or "").lower().replace("-", "_")
    if semantic_role:
        payload["semantic_role"] = semantic_role
    if kind in {"chart", "chart_interpretation"}:
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
        if kind == "chart_interpretation":
            evidence = data.get("evidence", data.get("evidence_refs", []))
            if evidence is not None and not isinstance(evidence, list):
                raise SectionValidationError("invalid_chart_evidence", "chart_interpretation evidence/evidence_refs must be a list")
            payload["evidence_count"] = len(evidence or [])
            payload["has_interpretation"] = bool(clean_text(data.get("interpretation") or data.get("insight") or data.get("summary") or ""))
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
    elif kind == "interactive_table":
        columns = data.get("columns", [])
        rows = data.get("rows", [])
        filters = data.get("filters", data.get("controls", []))
        if columns is not None and not isinstance(columns, list):
            raise SectionValidationError("invalid_interactive_table_columns", "interactive_table columns must be a list")
        if not isinstance(rows, list):
            raise SectionValidationError("invalid_interactive_table", "interactive_table requires list 'rows'")
        if filters is not None and not isinstance(filters, list):
            raise SectionValidationError("invalid_interactive_table_filters", "interactive_table filters/controls must be a list")
        payload.update(_interactive_payload_summary(rows, kind))
        payload["row_count"] = len(rows)
        payload["column_count"] = len(columns or _columns_from_rows(rows))
        payload["filter_count"] = len(filters or [])
        payload["has_search"] = bool(data.get("search", data.get("enable_search", True)))
        payload["caption_required"] = True
    elif kind in {"filterable_chart", "chart_table_explorer"}:
        records = data.get("records", data.get("rows", []))
        chart = data.get("chart", {})
        filters = data.get("filters", data.get("controls", []))
        columns = data.get("columns", [])
        if not isinstance(records, list):
            raise SectionValidationError("invalid_interactive_records", f"{kind} requires list 'records' or 'rows'")
        if not isinstance(chart, dict):
            raise SectionValidationError("invalid_interactive_chart", f"{kind} requires dict 'chart'")
        if filters is not None and not isinstance(filters, list):
            raise SectionValidationError("invalid_interactive_filters", f"{kind} filters/controls must be a list")
        if columns is not None and not isinstance(columns, list):
            raise SectionValidationError("invalid_interactive_columns", f"{kind} columns must be a list")
        payload.update(_interactive_payload_summary(records, kind))
        payload["filter_count"] = len(filters or [])
        payload["column_count"] = len(columns or _columns_from_rows(records))
        payload["chart_type"] = clean_text(chart.get("type") or "bar")
        payload["has_interpretation"] = bool(clean_text(data.get("interpretation") or data.get("insight") or data.get("summary") or ""))
    elif kind == "selector_panel":
        controls = data.get("controls", data.get("filters", []))
        items = data.get("items", data.get("options", []))
        if not isinstance(controls, list):
            raise SectionValidationError("invalid_selector_controls", "selector_panel requires list 'controls' or 'filters'")
        if items is not None and not isinstance(items, list):
            raise SectionValidationError("invalid_selector_items", "selector_panel items/options must be a list")
        payload.update(_interactive_payload_summary(items or [], kind))
        payload["control_count"] = len(controls)
        payload["item_count"] = len(items or [])
    elif kind == "entity_card_grid":
        items = data.get("items", data.get("entities", []))
        if not isinstance(items, list):
            raise SectionValidationError("invalid_entity_cards", "entity_card_grid requires list 'items' or 'entities'")
        payload.update(_interactive_payload_summary(items, kind))
        payload["item_count"] = len(items)
    elif kind == "header":
        absorbed = data.get("absorbed_readout") if isinstance(data.get("absorbed_readout"), dict) else {}
        # An editorial hero may absorb the executive readout; the quality gate
        # needs to see that the narrative answer lives here.
        payload["has_narrative_abstract"] = bool(
            clean_text(data.get("abstract") or "") or clean_text(absorbed.get("summary") or "")
        )
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
                "evidence": _evidence_summary(item),
                "evidence_anchor": clean_text(item.get("evidence_anchor") or ""),
                "ref": clean_text(item.get("ref") or item.get("cell_id") or item.get("artifact_id") or item.get("path") or ""),
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
    elif kind == "narrative_band":
        body = clean_text(data.get("body") or data.get("text") or data.get("summary") or "")
        payload["paragraph_count"] = len([part for part in body.split("\n\n") if part.strip()])
        payload["point_count"] = _count_optional_items(data.get("bullets") or data.get("key_points") or data.get("takeaways"))
    elif kind == "methodology_block":
        methods = data.get("methods", data.get("steps", data.get("items", [])))
        checks = data.get("checks", [])
        if methods is not None and not isinstance(methods, list):
            raise SectionValidationError("invalid_methodology", "methodology_block methods/steps/items must be a list")
        if checks is not None and not isinstance(checks, list):
            raise SectionValidationError("invalid_methodology_checks", "methodology_block checks must be a list")
        payload["method_count"] = len(methods or [])
        payload["check_count"] = len(checks or [])
        payload["method_titles"] = [
            clean_text(item.get("title") or item.get("name") or item.get("label") or "")
            for item in methods or []
            if isinstance(item, dict)
        ]
        payload["check_titles"] = [
            clean_text(item.get("title") or item.get("name") or item.get("label") or "")
            for item in checks or []
            if isinstance(item, dict)
        ]
    elif kind == "evidence_rail":
        items = data.get("evidence", data.get("items", []))
        if not isinstance(items, list):
            raise SectionValidationError("invalid_evidence_rail", "evidence_rail requires list 'evidence' or 'items'")
        payload["evidence_count"] = len(items)
        payload["items"] = [_ledger_item_summary(item) for item in items if isinstance(item, dict)]
    elif kind == "ledger_timeline":
        events = data.get("events", data.get("timeline", data.get("items", [])))
        if not isinstance(events, list):
            raise SectionValidationError("invalid_timeline", "ledger_timeline requires list 'events', 'timeline', or 'items'")
        payload["event_count"] = len(events)
        payload["items"] = [_ledger_item_summary(item) for item in events if isinstance(item, dict)]
        payload["statuses"] = sorted({
            clean_text(item.get("status") or item.get("state") or item.get("disposition") or "")
            for item in events
            if isinstance(item, dict) and clean_text(item.get("status") or item.get("state") or item.get("disposition") or "")
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

    # Display facts are a typed authoring input, rather than visual copy the
    # renderer tries to infer from prose. They remain deliberately small: the
    # actual report renderer decides where an explicitly selected fact appears.
    display_facts = _normalize_display_facts(data, owner_kind="section", owner_id=section_id)
    if display_facts:
        payload["display_fact_count"] = len(display_facts)
        payload["display_facts"] = display_facts

    return {
        "section_id": section_id,
        "section_schema": 3,
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


def unescape_display_text(value: Any) -> str:
    """Resolve HTML entities in display text (titles, captions) before storage.

    Authored tool arguments and text extracted from existing HTML routinely
    arrive pre-escaped ("Archetypes &amp; Segmentation"); rendering escapes
    again and the reader sees the literal entity. Unescape until stable so a
    double-escaped source ("&amp;amp;") also resolves, then let the renderer
    apply the single canonical escape.
    """
    text = clean_text(value)
    for _ in range(3):
        unescaped = html_lib.unescape(text)
        if unescaped == text:
            break
        text = unescaped
    return text


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


def _evidence_summary(item: dict[str, Any]) -> Any:
    """Summarize item evidence without destroying its structure.

    A list of refs must survive as a list: flattening it through clean_text
    produced its Python repr, which downstream evidence checks misparse as a
    single unresolvable pseudo-reference.
    """
    evidence = item.get("evidence") if item.get("evidence") is not None else item.get("evidence_ref")
    if isinstance(evidence, list):
        return [entry if isinstance(entry, dict) else clean_text(entry) for entry in evidence]
    return clean_text(evidence or "")


def _ledger_item_summary(item: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "finding_id": clean_text(item.get("finding_id") or ""),
        "hypothesis_id": clean_text(item.get("hypothesis_id") or item.get("id") or ""),
        "title": clean_text(item.get("title") or item.get("statement") or item.get("name") or ""),
        "status": clean_text(item.get("status") or item.get("state") or ""),
        "severity": clean_text(item.get("severity") or ""),
        "evidence": _evidence_summary(item),
        "evidence_anchor": clean_text(item.get("evidence_anchor") or ""),
        "ref": clean_text(item.get("ref") or item.get("cell_id") or item.get("artifact_id") or item.get("path") or ""),
    }
    owner_id = clean_text(item.get("finding_id") or item.get("hypothesis_id") or item.get("id") or summary["title"])
    display_facts = _normalize_display_facts(item, owner_kind="item", owner_id=owner_id)
    if display_facts:
        summary["display_fact_count"] = len(display_facts)
        summary["display_facts"] = display_facts
    return summary


def _normalize_display_facts(data: dict[str, Any], *, owner_kind: str, owner_id: str) -> list[dict[str, Any]]:
    """Validate source-owned facts that a visual author may selectively show.

    ``visual_facts`` remains a backwards-compatible alias.  A fact is not a
    renderer instruction: it identifies exact source text, permitted display
    roles, and optional provenance references.  This keeps runtime composition
    evidence-bound across domains without forcing every report into a template.
    """
    primary = data.get("display_facts")
    legacy = data.get("visual_facts")
    if primary is not None and legacy is not None and primary != legacy:
        raise SectionValidationError(
            "ambiguous_display_facts",
            "Use either display_facts or the legacy visual_facts alias, not both with different values.",
        )
    raw = primary if primary is not None else legacy
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise SectionValidationError("invalid_display_facts", "display_facts must be a list of fact objects")

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, fact in enumerate(raw):
        if not isinstance(fact, dict):
            raise SectionValidationError(
                "invalid_display_fact",
                "Each display_facts entry must be an object with fact_id, text, and uses.",
                {"owner_kind": owner_kind, "owner_id": owner_id, "index": index},
            )
        fact_id = clean_text(fact.get("fact_id") or fact.get("id"))
        text = clean_text(fact.get("text") or fact.get("label") or fact.get("value"))
        uses_raw = fact.get("uses", fact.get("use"))
        uses = uses_raw if isinstance(uses_raw, list) else [uses_raw]
        normalized_uses: list[str] = []
        for use in uses:
            value = clean_text(use).lower().replace("-", "_")
            if value not in DISPLAY_FACT_USES:
                raise SectionValidationError(
                    "invalid_display_fact_use",
                    f"display fact use {value!r} is unsupported",
                    {"allowed": sorted(DISPLAY_FACT_USES), "fact_id": fact_id or None},
                )
            if value not in normalized_uses:
                normalized_uses.append(value)
        if not fact_id or not DISPLAY_FACT_ID.fullmatch(fact_id):
            raise SectionValidationError(
                "invalid_display_fact_id",
                "display fact_id must start with a letter and contain only letters, digits, underscores, or hyphens.",
                {"fact_id": fact_id or None, "owner_kind": owner_kind, "owner_id": owner_id},
            )
        if fact_id in seen:
            raise SectionValidationError("duplicate_display_fact_id", f"display fact_id {fact_id!r} is repeated for this owner")
        if not text:
            raise SectionValidationError("missing_display_fact_text", f"display fact {fact_id!r} needs exact source text")
        if not normalized_uses:
            raise SectionValidationError("missing_display_fact_uses", f"display fact {fact_id!r} needs at least one allowed use")
        references = _normalize_display_fact_references(fact.get("evidence", fact.get("evidence_refs", fact.get("source_refs"))))
        entry: dict[str, Any] = {"fact_id": fact_id, "text": text, "uses": normalized_uses}
        if references:
            entry["evidence_refs"] = references
        normalized.append(entry)
        seen.add(fact_id)
    return normalized


def _normalize_display_fact_references(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    values = value if isinstance(value, list) else [value]
    references: list[str] = []
    for entry in values:
        if isinstance(entry, dict):
            ref = clean_text(entry.get("ref") or entry.get("id") or entry.get("cell_id") or entry.get("artifact_id"))
        else:
            ref = clean_text(entry)
        if not ref:
            raise SectionValidationError("invalid_display_fact_evidence", "display fact evidence references must be non-empty")
        if ref not in references:
            references.append(ref)
    return references


def _default_data_policy(kind: str) -> str:
    if kind in {
        "header",
        "callout",
        "text",
        "findings",
        "insight_grid",
        "explanation",
        "checklist",
        "narrative_band",
        "methodology_block",
        "evidence_rail",
        "ledger_timeline",
        "hypothesis_ledger",
        "evidence_trace",
    }:
        return "narrative"
    if kind in {"table", "comparison", "interactive_table"}:
        return "preview"
    return "aggregate_only"


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _count_optional_items(value: Any) -> int:
    if value is None or value == "":
        return 0
    if isinstance(value, list):
        return len(value)
    return 1


def _data_json_size(value: Any) -> int:
    return len(json.dumps(value, sort_keys=True, default=str).encode("utf-8"))


def _columns_from_rows(rows: list[Any]) -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key in row:
            clean_key = clean_text(key)
            if clean_key and clean_key not in seen:
                seen.add(clean_key)
                keys.append(clean_key)
    return keys


def _interactive_payload_summary(records: list[Any], kind: str) -> dict[str, Any]:
    row_count = len(records)
    if row_count > INTERACTIVE_DATA_MAX_ROWS:
        raise SectionValidationError(
            "interactive_data_too_many_rows",
            f"{kind} embeds {row_count} records, max {INTERACTIVE_DATA_MAX_ROWS}; aggregate or sample before publishing",
            {"rows": row_count, "max_rows": INTERACTIVE_DATA_MAX_ROWS},
        )
    encoded_bytes = _data_json_size(records)
    if encoded_bytes > INTERACTIVE_DATA_MAX_BYTES:
        raise SectionValidationError(
            "interactive_data_too_large",
            f"{kind} embedded JSON is too large ({encoded_bytes} bytes, max {INTERACTIVE_DATA_MAX_BYTES})",
            {"bytes": encoded_bytes, "max_bytes": INTERACTIVE_DATA_MAX_BYTES},
        )
    return {
        "record_count": row_count,
        "data_json_bytes": encoded_bytes,
        "max_records": INTERACTIVE_DATA_MAX_ROWS,
        "max_bytes": INTERACTIVE_DATA_MAX_BYTES,
    }
