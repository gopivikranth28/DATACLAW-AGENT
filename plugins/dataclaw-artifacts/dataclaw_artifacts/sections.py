"""Typed artifact section contract.

This module is the shared bridge between visualization/report-design skills and
artifact rendering. The workspace report helper uses it during the transition
so legacy report sections and first-class artifacts describe the same shapes.
"""

from __future__ import annotations

import hashlib
import html as html_lib
import json
import math
import re
from datetime import datetime
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
    "advanced_visual",
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
    "bespoke_visual": "advanced_visual",
    "handcrafted_visual": "advanced_visual",
    "visual_story": "advanced_visual",
}
DATA_POLICIES = {"narrative", "aggregate_only", "preview"}
CHART_SUMMARY_MAX_BYTES = 200 * 1024
TABLE_PREVIEW_MAX_ROWS = 20
TABLE_PREVIEW_MAX_BYTES = 50 * 1024
INTERACTIVE_DATA_MAX_ROWS = 500
INTERACTIVE_DATA_MAX_BYTES = 160 * 1024
DISPLAY_FACT_USES = {"pill", "scan_point", "example", "annotation"}
DISPLAY_FACT_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,119}$")
ADVANCED_VISUAL_FIELDS: dict[str, tuple[str, ...]] = {
    "dot_plot": ("label", "value"),
    "lollipop": ("label", "value"),
    "slopegraph": ("label", "start", "end"),
    "range_band": ("label", "low", "high"),
    "matrix": ("x", "y", "value"),
    "timeline": ("label", "time"),
    "flow": ("source", "target"),
    "bracket": ("source", "target"),
}
ADVANCED_VISUAL_OPTIONAL_FIELDS: dict[str, tuple[str, ...]] = {
    "range_band": ("value",),
    "timeline": ("detail",),
    "flow": ("value",),
    "bracket": ("value",),
}
ADVANCED_VISUAL_MAX_RECORDS = {
    "dot_plot": 30,
    "lollipop": 30,
    "slopegraph": 20,
    "range_band": 30,
    "matrix": 144,
    "timeline": 12,
    "flow": 80,
    "bracket": 64,
}
ADVANCED_VISUAL_NUMERIC_ROLES = {
    "dot_plot": ("value",),
    "lollipop": ("value",),
    "slopegraph": ("start", "end"),
    "range_band": ("low", "high", "value"),
    "matrix": ("value",),
    "flow": ("value",),
    "bracket": ("value",),
}
ADVANCED_VISUAL_TEXT_ROLES = {
    "dot_plot": ("label",),
    "lollipop": ("label",),
    "slopegraph": ("label",),
    "range_band": ("label",),
    "matrix": ("x", "y"),
    "timeline": ("label", "time", "detail"),
    "flow": ("source", "target"),
    "bracket": ("source", "target"),
}
ADVANCED_VISUAL_META_FIELDS = {
    "type", "unit", "aria_label", "sort", "zero_baseline", "start_label",
    "end_label", "stages", "scale",
}

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class SectionValidationError(ValueError):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": str(self), "details": self.details}


def _advanced_number(value: Any, *, role: str, row_index: int) -> float | int:
    if isinstance(value, bool) or value is None or value == "":
        raise SectionValidationError(
            "advanced_visual_invalid_number",
            f"advanced_visual row {row_index + 1} field '{role}' must be a finite number",
        )
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise SectionValidationError(
            "advanced_visual_invalid_number",
            f"advanced_visual row {row_index + 1} field '{role}' must be a finite number",
        ) from exc
    if not math.isfinite(number):
        raise SectionValidationError(
            "advanced_visual_invalid_number",
            f"advanced_visual row {row_index + 1} field '{role}' must be a finite number",
        )
    return int(number) if number.is_integer() else number


def _advanced_text(value: Any, *, role: str, row_index: int, optional: bool = False) -> str:
    text = clean_text(value).strip()
    if not text and not optional:
        raise SectionValidationError(
            "advanced_visual_blank_label",
            f"advanced_visual row {row_index + 1} field '{role}' must be non-empty",
        )
    limit = 240 if role == "detail" else 120
    if len(text) > limit:
        raise SectionValidationError(
            "advanced_visual_text_too_long",
            f"advanced_visual row {row_index + 1} field '{role}' exceeds {limit} characters",
        )
    return text


def _validate_acyclic_links(records: list[dict[str, Any]], source_key: str, target_key: str) -> int:
    graph: dict[str, set[str]] = {}
    incoming: dict[str, int] = {}
    for record in records:
        source = str(record[source_key])
        target = str(record[target_key])
        graph.setdefault(source, set()).add(target)
        graph.setdefault(target, set())
        incoming.setdefault(source, 0)
        incoming[target] = incoming.get(target, 0) + 1
    queue = [node for node, count in incoming.items() if count == 0]
    depth = {node: 0 for node in queue}
    visited = 0
    while queue:
        node = queue.pop(0)
        visited += 1
        for target in graph.get(node, set()):
            depth[target] = max(depth.get(target, 0), depth.get(node, 0) + 1)
            incoming[target] -= 1
            if incoming[target] == 0:
                queue.append(target)
    if visited != len(incoming):
        raise SectionValidationError(
            "advanced_visual_cyclic_flow",
            "advanced_visual flow/bracket links must form an acyclic progression",
        )
    return max(depth.values(), default=0) + 1


def prepare_advanced_visual_data(data: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    """Validate and minimize an advanced visual's embedded aggregate payload.

    Only mapped fields are retained. This is the enforcement boundary that
    prevents unused raw/PII columns from leaking into the single-file report.
    """
    records = data.get("records", data.get("rows", []))
    visual = data.get("visual", data.get("visual_spec", {}))
    if not isinstance(records, list) or not records:
        raise SectionValidationError(
            "invalid_advanced_visual_records",
            "advanced_visual requires a non-empty list of aggregate 'records' or 'rows'",
        )
    if not isinstance(visual, dict):
        raise SectionValidationError(
            "invalid_advanced_visual_spec",
            "advanced_visual requires a dict 'visual' or 'visual_spec'",
        )
    visual_type = clean_text(visual.get("type") or "").lower().replace("-", "_")
    required_roles = ADVANCED_VISUAL_FIELDS.get(visual_type)
    if required_roles is None:
        raise SectionValidationError(
            "unsupported_advanced_visual_type",
            f"Unsupported advanced visual type: {visual_type or '<missing>'}",
            {"allowed": sorted(ADVANCED_VISUAL_FIELDS)},
        )
    max_records = ADVANCED_VISUAL_MAX_RECORDS[visual_type]
    if len(records) > max_records:
        raise SectionValidationError(
            "advanced_visual_too_many_records",
            f"advanced_visual type '{visual_type}' has {len(records)} records, max {max_records}",
            {"records": len(records), "max_records": max_records},
        )
    optional_roles = ADVANCED_VISUAL_OPTIONAL_FIELDS.get(visual_type, ())
    missing_mappings = [role for role in required_roles if not clean_text(visual.get(role) or "")]
    if missing_mappings:
        raise SectionValidationError(
            "advanced_visual_missing_fields",
            f"advanced_visual type '{visual_type}' is missing field mappings: {', '.join(missing_mappings)}",
            {"required": list(required_roles)},
        )
    mappings = {
        role: clean_text(visual.get(role) or "").strip()
        for role in (*required_roles, *optional_roles)
        if clean_text(visual.get(role) or "").strip()
    }
    projected: list[dict[str, Any]] = []
    discarded: set[str] = set()
    seen_keys: set[tuple[str, ...]] = set()
    for index, raw in enumerate(records):
        if not isinstance(raw, dict):
            raise SectionValidationError(
                "advanced_visual_invalid_record",
                f"advanced_visual row {index + 1} must be an object",
            )
        missing_columns = [column for column in mappings.values() if column not in raw]
        if missing_columns:
            raise SectionValidationError(
                "advanced_visual_missing_columns",
                f"advanced_visual row {index + 1} is missing mapped columns: {', '.join(sorted(set(missing_columns)))}",
            )
        discarded.update(clean_text(key) for key in raw if clean_text(key) not in mappings.values())
        row: dict[str, Any] = {}
        for role, column in mappings.items():
            value = raw[column]
            if role in ADVANCED_VISUAL_NUMERIC_ROLES.get(visual_type, ()):
                row[column] = _advanced_number(value, role=role, row_index=index)
            elif role in ADVANCED_VISUAL_TEXT_ROLES.get(visual_type, ()):
                row[column] = _advanced_text(
                    value, role=role, row_index=index,
                    optional=role in optional_roles,
                )
            else:
                row[column] = clean_text(value)
        if visual_type == "range_band":
            if row[mappings["low"]] > row[mappings["high"]]:
                raise SectionValidationError(
                    "advanced_visual_invalid_range",
                    f"advanced_visual row {index + 1} has low greater than high",
                )
            if "value" in mappings and not (
                row[mappings["low"]] <= row[mappings["value"]] <= row[mappings["high"]]
            ):
                raise SectionValidationError(
                    "advanced_visual_invalid_range_value",
                    f"advanced_visual row {index + 1} value must fall within low and high",
                )
        if visual_type in {"flow", "bracket"}:
            source, target = row[mappings["source"]], row[mappings["target"]]
            if source == target:
                raise SectionValidationError(
                    "advanced_visual_self_link", f"advanced_visual row {index + 1} links a node to itself"
                )
            if "value" in mappings and row[mappings["value"]] < 0:
                raise SectionValidationError(
                    "advanced_visual_negative_flow", f"advanced_visual row {index + 1} flow value cannot be negative"
                )
            unique_key = (source, target)
        elif visual_type == "matrix":
            unique_key = (str(row[mappings["x"]]), str(row[mappings["y"]]))
        else:
            unique_key = (str(row[mappings["label"]]),)
        if unique_key in seen_keys:
            raise SectionValidationError(
                "advanced_visual_duplicate_record",
                f"advanced_visual row {index + 1} duplicates a visual key: {' / '.join(unique_key)}",
            )
        seen_keys.add(unique_key)
        projected.append(row)

    sanitized_visual = {
        key: visual[key]
        for key in sorted(ADVANCED_VISUAL_META_FIELDS)
        if key in visual
    }
    sanitized_visual["type"] = visual_type
    sanitized_visual.update(mappings)
    if "zero_baseline" in sanitized_visual and not isinstance(sanitized_visual["zero_baseline"], bool):
        raise SectionValidationError(
            "advanced_visual_invalid_zero_baseline",
            "advanced_visual zero_baseline must be a boolean",
        )
    if "sort" in sanitized_visual:
        sort = clean_text(sanitized_visual["sort"]).lower()
        if sort not in {"source", "descending"}:
            raise SectionValidationError(
                "advanced_visual_invalid_sort",
                "advanced_visual sort must be 'source' or 'descending'",
            )
        sanitized_visual["sort"] = sort
    for key, limit in (("unit", 24), ("aria_label", 180), ("start_label", 80), ("end_label", 80)):
        if key not in sanitized_visual:
            continue
        value = clean_text(sanitized_visual[key]).strip()
        if len(value) > limit:
            raise SectionValidationError(
                "advanced_visual_metadata_too_long",
                f"advanced_visual {key} exceeds {limit} characters",
            )
        sanitized_visual[key] = value
    if visual_type == "timeline":
        scale = clean_text(visual.get("scale") or "ordinal").lower()
        if scale not in {"ordinal", "time"}:
            raise SectionValidationError(
                "advanced_visual_invalid_timeline_scale",
                "advanced_visual timeline scale must be 'ordinal' or 'time'",
            )
        sanitized_visual["scale"] = scale
        if scale == "time":
            for index, row in enumerate(projected):
                value = str(row[mappings["time"]]).replace("Z", "+00:00")
                try:
                    datetime.fromisoformat(value)
                except ValueError as exc:
                    raise SectionValidationError(
                        "advanced_visual_invalid_time",
                        f"advanced_visual row {index + 1} time must be ISO-8601 when scale='time'",
                    ) from exc
    if visual_type == "matrix":
        x_count = len({row[mappings["x"]] for row in projected})
        y_count = len({row[mappings["y"]] for row in projected})
        if x_count > 12 or y_count > 12:
            raise SectionValidationError(
                "advanced_visual_matrix_too_dense",
                "advanced_visual matrix supports at most 12 rows and 12 columns",
                {"x_values": x_count, "y_values": y_count},
            )
    if visual_type in {"flow", "bracket"}:
        stage_count = _validate_acyclic_links(projected, mappings["source"], mappings["target"])
        stages = sanitized_visual.get("stages")
        if stages is not None:
            if not isinstance(stages, list) or any(
                not clean_text(stage).strip() or len(clean_text(stage).strip()) > 80 for stage in stages
            ):
                raise SectionValidationError(
                    "advanced_visual_invalid_stages",
                    "advanced_visual stages must be a list of non-empty labels no longer than 80 characters",
                )
            if len(stages) != stage_count:
                raise SectionValidationError(
                    "advanced_visual_missing_stages",
                    f"advanced_visual stages supplies {len(stages)} labels but the graph needs exactly {stage_count}",
                )
            sanitized_visual["stages"] = [clean_text(stage).strip() for stage in stages]

    summary = _interactive_payload_summary(projected, "advanced_visual")
    summary.update({
        "visual_type": visual_type,
        "field_mappings": mappings,
        "projected_columns": list(dict.fromkeys(mappings.values())),
        "discarded_column_count": len({column for column in discarded if column}),
        "data_minimized": True,
        "max_records_for_visual": max_records,
    })
    return projected, sanitized_visual, summary


def normalize_section(section_type: str, data: dict[str, Any]) -> dict[str, Any]:
    kind = canonical_kind(section_type)
    data_policy = str(data.get("data_policy") or _default_data_policy(kind))
    if data_policy not in DATA_POLICIES:
        raise SectionValidationError(
            "invalid_data_policy",
            f"Unsupported artifact section data_policy: {data_policy}",
            {"allowed": sorted(DATA_POLICIES)},
        )
    if kind == "advanced_visual" and data_policy != "aggregate_only":
        raise SectionValidationError(
            "advanced_visual_requires_aggregate_only",
            "advanced_visual data_policy is fixed to 'aggregate_only'",
        )
    advanced_prepared: tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]] | None = None
    stable_id_data = data
    if kind == "advanced_visual":
        advanced_prepared = prepare_advanced_visual_data(data)
        records, visual, _ = advanced_prepared
        stable_id_data = {
            key: value for key, value in data.items()
            if key not in {"records", "rows", "visual", "visual_spec"}
        }
        stable_id_data = {**stable_id_data, "records": records, "visual": visual}
    section_id = str(data.get("section_id") or data.get("id") or _stable_section_id(kind, stable_id_data))

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
    elif kind == "advanced_visual":
        assert advanced_prepared is not None
        records, visual, visual_summary = advanced_prepared
        visual_type = visual["type"]
        caption = clean_text(data.get("caption") or "")
        interpretation = clean_text(data.get("interpretation") or data.get("insight") or data.get("summary") or "")
        if not caption:
            raise SectionValidationError(
                "advanced_visual_missing_caption",
                "advanced_visual requires a reader-facing caption",
            )
        if not interpretation:
            raise SectionValidationError(
                "advanced_visual_missing_interpretation",
                "advanced_visual requires an adjacent interpretation sourced from the completed analysis",
            )
        evidence = data.get("evidence", data.get("evidence_refs", []))
        if evidence is not None and not isinstance(evidence, list):
            raise SectionValidationError(
                "invalid_advanced_visual_evidence",
                "advanced_visual evidence/evidence_refs must be a list",
            )
        payload.update(visual_summary)
        payload["evidence_count"] = len(evidence or [])
        payload["has_interpretation"] = True
        claim_source = data.get("claim_source")
        if claim_source is not None:
            if not isinstance(claim_source, dict):
                raise SectionValidationError(
                    "invalid_advanced_visual_claim_source",
                    "advanced_visual claim_source must be an object",
                )
            finding_id = clean_text(claim_source.get("finding_id") or "")
            source = clean_text(claim_source.get("source") or "")
            digest = clean_text(claim_source.get("text_sha256") or "")
            data_digest = clean_text(claim_source.get("data_sha256") or "")
            if (
                not finding_id or not source
                or not re.fullmatch(r"[0-9a-f]{64}", digest)
                or not re.fullmatch(r"[0-9a-f]{64}", data_digest)
            ):
                raise SectionValidationError(
                    "invalid_advanced_visual_claim_source",
                    "advanced_visual claim_source requires finding_id, source, and SHA-256 text/data digests",
                )
            if digest != hashlib.sha256(interpretation.encode("utf-8")).hexdigest():
                raise SectionValidationError(
                    "advanced_visual_claim_changed",
                    "advanced_visual interpretation no longer matches its completed-analysis source digest",
                )
            current_data_digest = hashlib.sha256(json.dumps(
                {"records": records, "visual": visual}, sort_keys=True, default=str,
                separators=(",", ":"),
            ).encode("utf-8")).hexdigest()
            if data_digest != current_data_digest:
                raise SectionValidationError(
                    "advanced_visual_data_changed",
                    "advanced_visual records or visual mapping no longer match the completed-analysis source digest",
                )
            payload["claim_source"] = {
                "finding_id": finding_id,
                "source": source,
                "text_sha256": digest,
                "data_sha256": data_digest,
            }
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
                "evidence": clean_text(item.get("evidence") or item.get("evidence_ref") or ""),
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


def _ledger_item_summary(item: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "finding_id": clean_text(item.get("finding_id") or ""),
        "hypothesis_id": clean_text(item.get("hypothesis_id") or item.get("id") or ""),
        "title": clean_text(item.get("title") or item.get("statement") or item.get("name") or ""),
        "status": clean_text(item.get("status") or item.get("state") or ""),
        "severity": clean_text(item.get("severity") or ""),
        "evidence": clean_text(item.get("evidence") or item.get("evidence_ref") or ""),
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
