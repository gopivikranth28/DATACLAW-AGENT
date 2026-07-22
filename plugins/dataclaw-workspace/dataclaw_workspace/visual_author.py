"""Evidence-bound visual author for storyboard-backed reports.

The evidence ledger is the durable contract.  In creative mode an LLM may
author the report-specific structural composition and inline CSS, while every
rendered section, claim, value, caption, and evidence reference still comes
from the validated storyboard.  Runtime mode retains the older bounded visual
grammar for ledger-free and explicitly constrained reports.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import re
from html.parser import HTMLParser
from typing import Any

from dataclaw_artifacts.validator import ArtifactValidationError, validate_and_prepare_html
from dataclaw.providers.llm.provider import LLMProvider, TextDeltaEvent
from dataclaw.schema import Message


VISUAL_AUTHOR_SCHEMA = 1

# Runtime mode uses these named palettes. Creative mode may additionally supply
# validated inline CSS for the report-specific visual system.
THEME_TOKENS: dict[str, dict[str, str]] = {
    "blue": {"accent": "#2563eb", "accent_2": "#0f766e", "accent_3": "#c2410c", "accent_soft": "#e8f0ff"},
    "ocean": {"accent": "#0369a1", "accent_2": "#0f766e", "accent_3": "#b45309", "accent_soft": "#e0f2fe"},
    "forest": {"accent": "#166534", "accent_2": "#0f766e", "accent_3": "#b45309", "accent_soft": "#dcfce7"},
    "plum": {"accent": "#6d28d9", "accent_2": "#0f766e", "accent_3": "#c2410c", "accent_soft": "#f3e8ff"},
    "slate": {"accent": "#334155", "accent_2": "#0f766e", "accent_3": "#b45309", "accent_soft": "#e2e8f0"},
}

_VALID_MODES = {"off", "runtime", "creative", "required", "provided"}
_VALID_SURFACES = {"strong", "quiet", "evidence", "trust"}
_VALID_PILL_TONES = {"accent", "good", "warn", "danger", "neutral"}
_VALID_INSIGHT_LAYOUTS = {"editorial_list", "card_grid"}
_VALID_INSIGHT_EVIDENCE = {"linked", "chips"}
_VALID_CHART_EVIDENCE = {"compact", "rail"}
_VALID_TRACE_EVIDENCE = {"disclosure", "expanded"}
_FACT_USES = {"pill", "scan_point", "example", "annotation"}
_DISPLAY_FACT_FIELDS = {
    "pills": "pill",
    "scan_points": "scan_point",
    "examples": "example",
    "annotations": "annotation",
}
_DEFAULT_TIMEOUT_SECONDS = 15
_DEFAULT_MAX_OUTPUT_CHARS = 12_000
_CREATIVE_MAX_OUTPUT_CHARS = 400_000
_CREATIVE_MAX_LAYOUT_CHARS = 16_000
_CREATIVE_MAX_CSS_CHARS = 28_000
_CREATIVE_MAX_DOSSIER_CHARS = 180_000
_CREATIVE_MAX_ROWS_PER_ASSET = 60
_CREATIVE_MAX_COLUMNS_PER_ASSET = 18
_CREATIVE_MAX_INLINE_JS_CHARS = 30_000
_CREATIVE_REVIEW_MAX_OUTPUT_CHARS = 20_000
_MAX_DISPLAY_FACTS = {"pill": 4, "scan_point": 5, "example": 4, "annotation": 3}

_AUTHORED_FORBIDDEN_JS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\beval\s*\(", re.I), "eval"),
    (re.compile(r"\bnew\s+Function\s*\(|\bFunction\s*\("), "function_constructor"),
    (re.compile(r"\bimport\b", re.I), "module_import"),
    (re.compile(r"\b(?:localStorage|sessionStorage|indexedDB)\b", re.I), "browser_storage"),
    (re.compile(r"\bdocument\.cookie\b", re.I), "document_cookie"),
    (re.compile(r"\b(?:SharedWorker|Worker)\s*\(", re.I), "worker"),
    (re.compile(r"\bnavigator\.serviceWorker\b", re.I), "service_worker"),
    (re.compile(r"\bdocument\.write(?:ln)?\s*\(", re.I), "document_write"),
    (re.compile(r"\bhistory\.(?:pushState|replaceState)\s*\(", re.I), "history_navigation"),
)


class VisualAuthorRequiredError(ValueError):
    """A required visual-author run failed after producing an audit record."""

    def __init__(self, reason: str, *, storyboard: dict[str, Any], record: dict[str, Any]) -> None:
        super().__init__(f"Runtime visual author failed: {reason}")
        self.reason = reason
        self.storyboard = storyboard
        self.record = record


def visual_theme_tokens(name: Any) -> dict[str, str]:
    """Return a copy of the palette for a validated named visual theme."""
    return dict(THEME_TOKENS.get(_clean(name).lower(), {}))


def visual_author_config(requirements: dict[str, Any] | None, override: dict[str, Any] | None = None) -> dict[str, Any]:
    """Resolve one explicit visual-author configuration.

    ``override`` is useful to callers of ``report_design_report`` that do not
    want to place runtime concerns in the analytical requirements dictionary.
    """
    supplied = override if isinstance(override, dict) else (requirements or {}).get("visual_author")
    if supplied is None:
        # Direct callers remain deterministic unless they request authoring.
        # report_design_report resolves handcrafted reports with an available
        # model to creative mode when an evidence ledger is present.
        return {"mode": "off", "baseline": "deterministic_desktop_editorial"}
    if not isinstance(supplied, dict):
        raise ValueError("visual_author must be a dictionary when supplied")
    config = copy.deepcopy(supplied)
    mode = _clean(config.get("mode") or "runtime").lower().replace("-", "_")
    if mode not in _VALID_MODES:
        raise ValueError("visual_author.mode must be 'off', 'runtime', 'creative', 'required', or 'provided'")
    config["mode"] = mode
    facts = config.get("facts", config.get("source_facts", []))
    if facts is not None and not isinstance(facts, list):
        raise ValueError("visual_author.facts must be a list when supplied")
    config["timeout_seconds"] = _bounded_int(
        config.get("timeout_seconds"),
        default=60 if mode == "creative" else _DEFAULT_TIMEOUT_SECONDS,
        minimum=1,
        maximum=120,
        field="visual_author.timeout_seconds",
    )
    config["max_output_chars"] = _bounded_int(
        config.get("max_output_chars"),
        default=_CREATIVE_MAX_OUTPUT_CHARS if mode == "creative" else _DEFAULT_MAX_OUTPUT_CHARS,
        minimum=512,
        maximum=_CREATIVE_MAX_OUTPUT_CHARS if mode == "creative" else 50_000,
        field="visual_author.max_output_chars",
    )
    config["max_repair_passes"] = _bounded_int(
        config.get("max_repair_passes"),
        default=1 if mode == "creative" else 0,
        minimum=0,
        maximum=1,
        field="visual_author.max_repair_passes",
    )
    allow_story_reorder = config.get("allow_story_reorder", False)
    if not isinstance(allow_story_reorder, bool):
        raise ValueError("visual_author.allow_story_reorder must be a boolean")
    config["allow_story_reorder"] = allow_story_reorder
    return config


def build_visual_author_catalog(storyboard: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Build the sole vocabulary a visual-author model may select from."""
    section_plan = storyboard.get("section_plan")
    if not isinstance(section_plan, list):
        raise ValueError("visual author requires a storyboard section_plan")

    creative = config.get("mode") == "creative"
    sections: list[dict[str, Any]] = []
    insight_targets: dict[str, str] = {}
    insight_catalog: list[dict[str, str]] = []
    for index, planned in enumerate(section_plan):
        if not isinstance(planned, dict):
            continue
        section_type = _clean(planned.get("section_type") or planned.get("kind")).lower()
        section_id = _section_id(planned, index)
        data = planned.get("data") if isinstance(planned.get("data"), dict) else {}
        capability = _section_capability(section_type)
        if capability is None and not creative:
            continue
        if capability is None:
            # Creative composition is intentionally not limited to the older
            # named component grammar. Every renderer-owned section receives a
            # structural slot even when it has no bounded authoring controls.
            capability = {"surfaces": sorted(_VALID_SURFACES)}
        entry: dict[str, Any] = {
            "section_id": section_id,
            "section_type": section_type,
            "title": _clean(data.get("title")),
            "surfaces": capability["surfaces"],
            "layout_group": _clean(planned.get("layout_group")),
            "story_role": _clean(planned.get("story_role") or data.get("story_role")),
            "surface_parent_id": _clean(planned.get("surface_parent_id") or data.get("surface_parent_id")),
            "nested_surface": bool(planned.get("nested_surface") or data.get("nested_surface")),
        }
        if "layouts" in capability:
            entry["layouts"] = capability["layouts"]
        if "evidence_presentations" in capability:
            entry["evidence_presentations"] = capability["evidence_presentations"]
        entry["item_count"] = len(data.get("items", data.get("insights", []))) if isinstance(data.get("items", data.get("insights", [])), list) else 0
        if creative:
            entry["asset_semantics"] = _creative_asset_semantics(section_type, data, planned)
        sections.append(entry)
        if section_type == "insight_grid":
            for insight_index, item in enumerate(data.get("items", [])):
                if isinstance(item, dict):
                    insight_id = _insight_id(item, insight_index)
                    if insight_id in insight_targets:
                        raise ValueError(
                            f"visual-author insight ids must be unique; duplicate {insight_id!r}. "
                            "Use finding_id or visual_author_insight_id to disambiguate repeated insight grids."
                        )
                    insight_targets[insight_id] = section_id
                    insight_catalog.append({
                        "insight_id": insight_id,
                        "section_id": section_id,
                        "title": _clean(item.get("title") or item.get("headline") or item.get("statement")),
                        "status": _clean(item.get("status") or item.get("severity") or item.get("confidence")),
                    })

    section_ids = [entry["section_id"] for entry in sections]
    if creative:
        unsafe_ids = [item for item in section_ids if not re.fullmatch(r"[A-Za-z0-9_.:-]+", item)]
        duplicate_ids = sorted({item for item in section_ids if section_ids.count(item) > 1})
        if unsafe_ids:
            raise ValueError(f"creative section ids must use letters, numbers, '.', ':', '_' or '-': {unsafe_ids}")
        if duplicate_ids:
            raise ValueError(f"creative section ids must be unique: {duplicate_ids}")
    facts = _collect_facts(storyboard, config, set(section_ids), insight_targets)
    evidence_registry = storyboard.get("evidence_registry") if isinstance(storyboard.get("evidence_registry"), dict) else {}
    evidence_targets = [item for item in evidence_registry.get("targets", []) if isinstance(item, dict)]
    evidence_references = [item for item in evidence_registry.get("references", []) if isinstance(item, dict)]
    if creative and not evidence_targets:
        raise ValueError(
            "visual_author.mode='creative' requires a non-empty evidence ledger; "
            "supply finding/evidence ids and registered targets before creative authoring"
        )
    return {
        "schema": VISUAL_AUTHOR_SCHEMA,
        "report": {
            "title": _clean(storyboard.get("title")),
            "goal": _clean(storyboard.get("report_goal")),
            "audience": _clean(storyboard.get("audience")),
        },
        "themes": sorted(THEME_TOKENS),
        "sections": sections,
        "insights": insight_catalog,
        "facts": facts,
        "composition": _build_composition_catalog(section_plan, config),
        "creative": {
            "enabled": creative,
            "section_ids": section_ids,
            "evidence_target_count": len(evidence_targets),
            "evidence_reference_count": len(evidence_references),
        },
    }


def build_visual_author_prompt(catalog: dict[str, Any]) -> tuple[str, str]:
    """Return the instruction and catalog for the bounded runtime visual editor."""
    system = """You are a report visual editor. Compose a restrained, reader-first visual plan.

Return one JSON object only. You may select only section_id and fact_id values in the supplied catalog. Never write HTML, CSS, JavaScript, markdown, new labels, new copy, or new facts. A fact's supplied text is the only text that may appear in the final report. Use cards only for peer entities or KPIs; keep narrative findings as an editorial list unless a true peer comparison needs a grid. Avoid nested surfaces unless there is a clear evidence or trust relationship.

The JSON shape is:
{
  "schema": 1,
  "theme": "blue",
  "sections": [
    {"section_id": "...", "surface": "quiet|evidence|trust|strong", "layout": "editorial_list|card_grid", "evidence_presentation": "linked|chips|compact|rail|disclosure|expanded", "pills": [{"fact_id": "...", "tone": "accent|good|warn|danger|neutral"}], "scan_points": ["..."], "examples": ["..."], "annotations": ["..."]}
  ],
  "insights": [
    {
      "insight_id": "...",
      "pills": [{"fact_id": "...", "tone": "accent|good|warn|danger|neutral"}],
      "scan_points": ["..."],
      "examples": ["..."]
    }
  ]
  ,"composition": [
    {"zone_id": "...", "order": ["declared-block-id", "..."]}
  ]
}

Omit fields that do not apply. Only return composition entries for zones in the supplied composition catalog, and keep every listed block exactly once. Composition can reorder only declared source blocks inside the same zone; it cannot move a block across an undeclared narrative boundary. Use a fact only in a compatible use listed on that fact. A section-level fact belongs to its supplied section; an insight fact belongs only to its supplied insight. Do not repeat a fact in multiple display roles. Use one strong evidence surface at most unless the catalog clearly supplies two separate comparison acts. A card grid is a comparison treatment, not the default narrative wrapper."""
    return system, json.dumps(catalog, ensure_ascii=False, separators=(",", ":"), default=str)


def _source_evidence_ids(value: Any) -> list[str]:
    refs: list[str] = []
    for item in _as_list(value):
        if isinstance(item, dict):
            ref = _clean(
                item.get("ref")
                or item.get("id")
                or item.get("cell_id")
                or item.get("artifact_id")
                or item.get("finding_id")
                or item.get("hypothesis_id")
                or item.get("path")
            )
        else:
            ref = _clean(item)
        if ref and ref not in refs:
            refs.append(ref)
    return refs


def _prompt_value(value: Any, *, depth: int = 0) -> Any:
    """Bound source material without changing supplied scalar values."""
    if depth > 4:
        return "[nested material omitted]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _prompt_text(value, 2_000)
    if isinstance(value, dict):
        return {
            _prompt_text(key, 100): _prompt_value(child, depth=depth + 1)
            for key, child in list(value.items())[:40]
            if _prompt_text(key, 100)
        }
    if isinstance(value, (list, tuple)):
        return [_prompt_value(child, depth=depth + 1) for child in list(value)[:80]]
    return _prompt_text(value, 500)


def _bounded_aggregate_rows(value: Any) -> dict[str, Any]:
    rows = value if isinstance(value, list) else []
    projected: list[dict[str, Any]] = []
    columns: list[str] = []
    for row in rows[:_CREATIVE_MAX_ROWS_PER_ASSET]:
        if not isinstance(row, dict):
            continue
        if not columns:
            columns = [_clean(key) for key in list(row)[:_CREATIVE_MAX_COLUMNS_PER_ASSET] if _clean(key)]
        projected.append({key: _prompt_value(row.get(key)) for key in columns})
    return {
        "row_count": len(rows),
        "included_row_count": len(projected),
        "truncated": len(rows) > len(projected),
        "columns": columns,
        "rows": projected,
    }


def _plotly_payload(value: Any) -> dict[str, Any]:
    if hasattr(value, "to_plotly_json"):
        try:
            value = value.to_plotly_json()
        except Exception:
            return {}
    if not isinstance(value, dict):
        return {}
    traces: list[dict[str, Any]] = []
    for trace in _as_list(value.get("data"))[:12]:
        if not isinstance(trace, dict):
            continue
        included: dict[str, Any] = {}
        for key in ("type", "name", "orientation", "x", "y", "z", "labels", "values", "ids", "text"):
            child = trace.get(key)
            if isinstance(child, (list, tuple)):
                included[key] = [_prompt_value(item) for item in list(child)[:_CREATIVE_MAX_ROWS_PER_ASSET]]
                if len(child) > _CREATIVE_MAX_ROWS_PER_ASSET:
                    included[f"{key}_truncated"] = True
            elif child is not None:
                included[key] = _prompt_value(child)
        traces.append(included)
    layout = value.get("layout") if isinstance(value.get("layout"), dict) else {}
    return {
        "trace_count": len(_as_list(value.get("data"))),
        "traces": traces,
        "axis_titles": {
            axis: _prompt_value((layout.get(axis) or {}).get("title"))
            for axis in ("xaxis", "yaxis")
            if isinstance(layout.get(axis), dict) and (layout.get(axis) or {}).get("title")
        },
    }


def build_creative_author_dossier(
    storyboard: dict[str, Any],
    config: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Build a prose-first authoring dossier with bounded aggregate values."""
    cfg = config or {}
    registry = storyboard.get("evidence_registry") if isinstance(storyboard.get("evidence_registry"), dict) else {}
    targets = [item for item in registry.get("targets", []) if isinstance(item, dict)]
    if not targets:
        raise ValueError("creative report authoring requires a non-empty evidence ledger")

    evidence_entries: list[dict[str, Any]] = []
    evidence_by_id: dict[str, str] = {}
    for index, target in enumerate(targets):
        target_id = _clean(target.get("id") or target.get("ref"))
        if not target_id:
            continue
        alias = f"ev-{index + 1}"
        evidence_by_id[target_id] = alias
        evidence_entries.append({"alias": alias, "target": _prompt_value(target)})
    if not evidence_entries:
        raise ValueError("creative report authoring requires valid evidence-ledger targets")

    source_context = storyboard.get("source_context") if isinstance(storyboard.get("source_context"), dict) else {}
    insights = [item for item in source_context.get("insights", []) if isinstance(item, dict)]
    analyses = [item for item in source_context.get("analyses", []) if isinstance(item, dict)]
    requirements = source_context.get("requirements") if isinstance(source_context.get("requirements"), dict) else {}
    sources: list[dict[str, Any]] = []
    dossier_blocks: list[tuple[str, dict[str, Any]]] = []

    for index, insight in enumerate(insights):
        alias = f"src-finding-{index + 1}"
        source_id = _clean(insight.get("finding_id") or insight.get("insight_id") or f"finding-{index + 1}")
        refs = _source_evidence_ids(insight.get("evidence") or insight.get("evidence_refs"))
        if source_id in evidence_by_id and source_id not in refs:
            refs.append(source_id)
        evidence_aliases = [evidence_by_id[ref] for ref in refs if ref in evidence_by_id]
        claim_scope = _clean(insight.get("claim_scope") or insight.get("inference_scope") or "descriptive").lower()
        payload = {
            "source_alias": alias,
            "source_id": source_id,
            "kind": "validated_finding",
            "title": _prompt_text(insight.get("title") or insight.get("headline"), 500),
            "validated_statement": _prompt_text(
                insight.get("detail") or insight.get("summary") or insight.get("statement"), 2_000
            ),
            "status": _prompt_text(insight.get("status") or insight.get("confidence"), 200),
            "claim_scope": claim_scope,
            "causal_language_allowed": claim_scope in {"causal", "experimental_causal", "validated_causal"},
            "metrics": _prompt_value(insight.get("metrics") or []),
            "supporting_points": _prompt_value(
                insight.get("bullets") or insight.get("scan_points") or insight.get("supporting_points") or []
            ),
            "representative_examples": _prompt_value(
                insight.get("representative_examples") or insight.get("examples") or []
            ),
            "display_facts": _prompt_value(insight.get("display_facts") or []),
            "caveat": _prompt_value(insight.get("caveat") or insight.get("limitations") or ""),
            "evidence_aliases": evidence_aliases,
        }
        sources.append({"alias": alias, "source_id": source_id, "kind": "finding"})
        dossier_blocks.append((f"Validated finding {alias}", payload))

    for index, analysis in enumerate(analyses):
        alias = f"src-asset-{index + 1}"
        nested = analysis.get("data") if isinstance(analysis.get("data"), dict) else {}
        material = {**analysis, **nested}
        material.pop("data", None)
        source_id = _clean(
            material.get("visual_author_section_id")
            or material.get("section_id")
            or material.get("slug")
            or f"analysis-{index + 1}"
        )
        refs = _source_evidence_ids(material.get("evidence") or material.get("evidence_refs"))
        evidence_aliases = [evidence_by_id[ref] for ref in refs if ref in evidence_by_id]
        rows_value = (
            material.get("records")
            if isinstance(material.get("records"), list)
            else material.get("rows")
            if isinstance(material.get("rows"), list)
            else material.get("items")
            if isinstance(material.get("items"), list) and all(isinstance(row, dict) for row in material.get("items", []))
            else []
        )
        visual = material.get("visual") if isinstance(material.get("visual"), dict) else {}
        payload = {
            "source_alias": alias,
            "source_id": source_id,
            "kind": _clean(material.get("section_type") or material.get("kind") or "analysis_asset"),
            "title": _prompt_text(material.get("title"), 500),
            "caption": _prompt_text(material.get("caption") or material.get("dek"), 1_000),
            "interpretation": _prompt_text(
                material.get("interpretation") or material.get("conclusion") or material.get("summary"), 2_000
            ),
            "caveat": _prompt_value(material.get("caveat") or material.get("limitations") or ""),
            "semantic_role": _prompt_text(material.get("semantic_role"), 200),
            "editorial_role": _prompt_text(material.get("editorial_role"), 200),
            "story_arc": _prompt_text(material.get("story_arc") or material.get("arc"), 300),
            "grain": _prompt_value(material.get("grain") or material.get("data_grain") or ""),
            "units": _prompt_value(material.get("units") or material.get("unit") or ""),
            "denominator": _prompt_value(material.get("denominator") or material.get("population") or ""),
            "field_definitions": _prompt_value(
                material.get("field_definitions") or material.get("definitions") or material.get("columns") or []
            ),
            "filters": _prompt_value(material.get("filters") or []),
            "annotations": _prompt_value(material.get("annotations") or material.get("display_facts") or []),
            "visual_mapping": _prompt_value(visual),
            "aggregate_data": _bounded_aggregate_rows(rows_value) if rows_value else {},
            "plotly_summary": _plotly_payload(material.get("figure_json") or material.get("figure")),
            "evidence_aliases": evidence_aliases,
        }
        sources.append({"alias": alias, "source_id": source_id, "kind": "asset"})
        dossier_blocks.append((f"Aggregate or analytical asset {alias}", payload))

    brief = {
        "title": _prompt_text(storyboard.get("title"), 500),
        "goal": _prompt_text(storyboard.get("report_goal"), 1_500),
        "audience": _prompt_text(storyboard.get("audience"), 500),
        "design_direction": _prompt_value(
            requirements.get("design_brief")
            or requirements.get("visual_direction")
            or requirements.get("style")
            or requirements.get("tone")
            or "Create a distinctive editorial analytical report suited to the subject matter."
        ),
        "story_arcs": _prompt_value(requirements.get("story_arcs") or []),
        "editorial_archetype": _prompt_value(requirements.get("editorial_archetype") or ""),
    }
    trust_material = {
        key: _prompt_value(requirements.get(key))
        for key in (
            "kicker", "subtitle", "metrics", "filters", "definitions", "glossary", "brand",
            "methodology", "methods", "checks", "data_quality", "coverage_risks",
            "uncertainty", "uncertainty_notes", "analysis_review", "assumptions", "limitations",
        )
        if requirements.get(key) not in (None, "", [], {})
    }
    contract = {
        "author_contract_schema": 1,
        "sources": sources,
        "evidence": [
            {
                "alias": entry["alias"],
                "id": _clean((entry["target"] or {}).get("id") or (entry["target"] or {}).get("ref")),
                "kind": _clean((entry["target"] or {}).get("kind") or (entry["target"] or {}).get("type")),
            }
            for entry in evidence_entries
        ],
    }
    parts = [
        "# Author brief\n\n" + json.dumps(brief, indent=2, ensure_ascii=False, default=str),
        "# Authoring freedom and evidence boundary\n\n"
        "Write original prose and choose the complete story architecture. You may merge, split, reorder, or omit source material. "
        "Preserve meaning, qualifications, units, and denominators. Descriptive or associational evidence must not become causal. "
        "Use only the bounded aggregate values below for quantitative visuals; they are report aggregates or samples, not raw full datasets. "
        "Mark used source aliases with data-source and supporting evidence aliases with data-evidence. Explicitly record intentionally omitted sources in the coverage script.",
    ]
    parts.extend(
        f"# {heading}\n\n```json\n{json.dumps(payload, indent=2, ensure_ascii=False, default=str)}\n```"
        for heading, payload in dossier_blocks
    )
    parts.append("# Methodology, limitations, and review material\n\n" + json.dumps(trust_material, indent=2, ensure_ascii=False, default=str))
    ledger_document = {
        "evidence_registry_schema": registry.get("evidence_registry_schema", 1),
        "targets": evidence_entries,
        "references": _prompt_value(registry.get("references") or []),
    }
    parts.append("# Evidence ledger\n\n```json\n" + json.dumps(ledger_document, indent=2, ensure_ascii=False, default=str) + "\n```")
    dossier = "\n\n".join(parts)
    max_chars = _bounded_int(
        cfg.get("max_dossier_chars"),
        default=_CREATIVE_MAX_DOSSIER_CHARS,
        minimum=10_000,
        maximum=300_000,
        field="visual_author.max_dossier_chars",
    )
    if len(dossier) > max_chars:
        raise ValueError(
            f"creative authoring dossier exceeds visual_author.max_dossier_chars ({max_chars}); "
            "reduce or further aggregate the supplied report assets"
        )
    contract["dossier_sha256"] = hashlib.sha256(dossier.encode("utf-8")).hexdigest()
    return dossier, contract


def build_creative_author_prompt(dossier: str) -> tuple[str, str]:
    """Return the high-freedom full-document author instruction and dossier."""
    system = """You are the writer, information designer, and front-end author of a bespoke analytical report.

Return one complete single-file HTML document and nothing else. Write original report prose, headings, transitions, captions, interpretation notes, and calls to attention, but keep every substantive statement entailed by the supplied findings, aggregates, methods, and caveats. Do not introduce a causal explanation unless a cited finding explicitly permits causal language.

You own the story architecture. Merge, split, reorder, or omit source blocks when that improves the report. Do not reproduce a generic component-library dashboard. Create report-specific HTML, original CSS, and bespoke SVG or Canvas visuals from the supplied bounded aggregate values. Familiar chart forms are allowed when they communicate best. Use actual supplied values, units, labels, and denominators; never invent geometry or data.

For every used source, put its src-* alias in a data-source attribute on the relevant section, claim, or figure. Put supporting ev-* aliases in data-evidence on every substantive analytical claim and quantitative visual. Multiple aliases are space-separated. Decorative visuals may use data-decoration="true". Before </body>, include exactly one inert coverage block:
<script type="application/json" data-dc-author-coverage>{"omitted":[{"source":"src-...","reason":"brief reason"}]}</script>
Used sources are inferred from data-source attributes, so do not list them in the coverage JSON. Every supplied source must either be used or explicitly omitted.

Artifact rules: no external scripts, stylesheets, fonts, images, remote assets, network calls, live data fetching, iframes, forms, storage, cookies, workers, eval, dynamic imports, navigation code, or inline event-handler attributes. Inline JavaScript is optional; when useful, keep it small, deterministic, DOM-local, and place data-dc-author-script on each executable script. Prefer textContent and DOM construction. Do not include libraries. Include a restrictive CSP meta tag. Use accessible landmarks, one h1, coherent heading order, keyboard controls, reduced-motion behavior, figure captions, and interpretation notes near visuals.

Define --dc-ink, --dc-muted, and --dc-surface as six-digit hex colors in :root so contrast can be checked. Do not include DataClaw evidence-registry, report-contract, regeneration-recipe, or section-metadata scripts; the host injects those after validation."""
    return system, dossier


class _AuthoredDocumentParser(HTMLParser):
    """Collect safety and evidence signals from untrusted authored HTML."""

    _TEXT_BLOCKS = {"p", "li", "blockquote", "figcaption"}
    _VISUAL_TAGS = {"figure", "svg", "canvas"}
    _VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
    _RESERVED_ATTRS = {
        "data-dc-evidence-registry",
        "data-dc-report-contract",
        "data-dc-regeneration-recipe",
        "data-dc-section-meta",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[str] = []
        self.styles = 0
        self.h1_count = 0
        self.title_count = 0
        self.evidence_aliases: set[str] = set()
        self.source_aliases: set[str] = set()
        self.visuals_without_evidence: list[str] = []
        self.script_count = 0
        self.script_chars = 0
        self.coverage_payloads: list[str] = []
        self._stack: list[dict[str, Any]] = []
        self._script: dict[str, Any] | None = None
        self._text_blocks: list[dict[str, Any]] = []
        self.claims: list[dict[str, Any]] = []

    @staticmethod
    def _aliases(value: str) -> set[str]:
        return {item for item in re.split(r"[\s,]+", value.strip()) if item}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attr = {name.lower(): value or "" for name, value in attrs}
        self.tags.append(tag)
        if any(name in self._RESERVED_ATTRS for name in attr):
            raise ValueError("authored HTML cannot supply reserved DataClaw metadata")
        unsupported_dc = [
            name for name in attr
            if name.startswith("data-dc-")
            and name not in {"data-dc-author-coverage", "data-dc-author-script"}
        ]
        if unsupported_dc:
            raise ValueError(f"authored HTML cannot supply host-owned DataClaw attributes: {unsupported_dc}")
        if tag == "meta" and attr.get("http-equiv", "").lower() == "refresh":
            raise ValueError("authored HTML cannot use meta refresh")
        if tag == "form" or attr.get("action") or attr.get("formaction"):
            raise ValueError("authored HTML cannot submit forms")
        for name in ("href", "src", "xlink:href", "poster", "srcset"):
            value = attr.get(name, "").strip()
            if not value:
                continue
            remote = bool(re.match(r"(?:https?:)?//", value, re.I))
            if remote and tag == "a" and name == "href":
                continue
            if remote or value.startswith("/"):
                raise ValueError(f"authored HTML cannot use external or root-relative {name}")
            if name in {"href", "xlink:href"} and re.match(r"(?:javascript|file|data):", value, re.I):
                raise ValueError(f"authored HTML cannot use active {name} URLs")
        inherited_evidence = set(self._stack[-1]["evidence"]) if self._stack else set()
        inherited_source = set(self._stack[-1]["source"]) if self._stack else set()
        inherited_decoration = bool(self._stack[-1]["decoration"]) if self._stack else False
        evidence = inherited_evidence | self._aliases(attr.get("data-evidence", ""))
        source = inherited_source | self._aliases(attr.get("data-source", ""))
        decoration = inherited_decoration or attr.get("data-decoration", "").lower() == "true"
        self.evidence_aliases.update(self._aliases(attr.get("data-evidence", "")))
        self.source_aliases.update(self._aliases(attr.get("data-source", "")))
        if tag in self._VISUAL_TAGS and not evidence and not decoration:
            self.visuals_without_evidence.append(tag)
        entry = {"tag": tag, "evidence": evidence, "source": source, "decoration": decoration}
        if tag not in self._VOID_TAGS:
            self._stack.append(entry)
        if tag in self._TEXT_BLOCKS:
            block = {"tag": tag, "evidence": sorted(evidence), "source": sorted(source), "parts": []}
            self._text_blocks.append(block)
        if tag == "style":
            self.styles += 1
        elif tag == "h1":
            self.h1_count += 1
        elif tag == "title":
            self.title_count += 1
        elif tag == "script":
            if attr.get("src"):
                raise ValueError("authored HTML cannot use external scripts")
            is_coverage = "data-dc-author-coverage" in attr
            script_type = attr.get("type", "").lower()
            if is_coverage:
                if script_type != "application/json":
                    raise ValueError("author coverage must be inert application/json")
            elif script_type not in {"", "text/javascript", "application/javascript", "module"}:
                raise ValueError("authored HTML contains an unsupported script type")
            elif "data-dc-author-script" not in attr:
                raise ValueError("executable authored scripts require data-dc-author-script")
            self._script = {"coverage": is_coverage, "parts": []}

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in self._VOID_TAGS:
            self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        if self._script is not None:
            self._script["parts"].append(data)
        for block in self._text_blocks:
            block["parts"].append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "script" and self._script is not None:
            payload = "".join(self._script["parts"])
            if self._script["coverage"]:
                self.coverage_payloads.append(payload)
            else:
                self.script_count += 1
                self.script_chars += len(payload)
                for pattern, name in _AUTHORED_FORBIDDEN_JS:
                    if pattern.search(payload):
                        raise ValueError(f"authored JavaScript contains forbidden {name}")
            self._script = None
        if tag in self._TEXT_BLOCKS and self._text_blocks:
            block = self._text_blocks.pop()
            text = re.sub(r"\s+", " ", "".join(block.pop("parts"))).strip()
            if text:
                block["text"] = text[:2_000]
                self.claims.append(block)
        if self._stack:
            if self._stack[-1]["tag"] != tag:
                raise ValueError("authored HTML has unbalanced elements")
            self._stack.pop()

    def close(self) -> None:
        super().close()
        if self._stack:
            raise ValueError("authored HTML has unclosed elements")


def _parse_authored_html(value: str) -> str:
    text = value.strip()
    fenced = re.fullmatch(r"```(?:html)?\s*(.*?)\s*```", text, re.IGNORECASE | re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    start = re.search(r"<!doctype\s+html\b|<html\b", text, re.IGNORECASE)
    end = re.search(r"</html\s*>", text, re.IGNORECASE)
    if not start or not end:
        raise ValueError("creative author must return one complete HTML document")
    trailing = text[end.end():].strip()
    if trailing:
        raise ValueError("creative author returned content after </html>")
    return text[start.start():end.end()]


def validate_authored_document(html: str, contract: dict[str, Any]) -> dict[str, Any]:
    """Validate full authored HTML against safety, source, and ledger aliases."""
    if not isinstance(contract, dict) or contract.get("author_contract_schema") != 1:
        raise ValueError("authored document requires a valid author contract")
    if len(html) > _CREATIVE_MAX_OUTPUT_CHARS:
        raise ValueError(f"authored HTML exceeds {_CREATIVE_MAX_OUTPUT_CHARS} characters")
    if not re.search(r"<!doctype\s+html\b", html, re.IGNORECASE):
        raise ValueError("authored HTML requires <!doctype html>")
    parser = _AuthoredDocumentParser()
    try:
        parser.feed(html)
        parser.close()
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"authored HTML could not be parsed: {exc}") from exc
    required_tags = {"html", "head", "body"}
    if not required_tags.issubset(set(parser.tags)) or parser.title_count != 1 or parser.h1_count != 1:
        raise ValueError("authored HTML requires html/head/body, exactly one title, and exactly one h1")
    if not parser.styles:
        raise ValueError("authored HTML requires original inline CSS")
    if parser.script_count > 3 or parser.script_chars > _CREATIVE_MAX_INLINE_JS_CHARS:
        raise ValueError("authored inline JavaScript exceeds the safe script budget")
    if len(parser.coverage_payloads) != 1:
        raise ValueError("authored HTML requires exactly one data-dc-author-coverage script")
    try:
        coverage = json.loads(parser.coverage_payloads[0])
    except json.JSONDecodeError as exc:
        raise ValueError("authored evidence coverage is not valid JSON") from exc
    if not isinstance(coverage, dict):
        raise ValueError("authored evidence coverage must be an object")
    known_sources = {
        _clean(item.get("alias")) for item in contract.get("sources", [])
        if isinstance(item, dict) and _clean(item.get("alias"))
    }
    known_evidence = {
        _clean(item.get("alias")) for item in contract.get("evidence", [])
        if isinstance(item, dict) and _clean(item.get("alias"))
    }
    unknown_sources = sorted(parser.source_aliases - known_sources)
    unknown_evidence = sorted(parser.evidence_aliases - known_evidence)
    if unknown_sources:
        raise ValueError(f"authored HTML references unknown source aliases: {unknown_sources}")
    if unknown_evidence:
        raise ValueError(f"authored HTML references unknown evidence aliases: {unknown_evidence}")
    omitted: dict[str, str] = {}
    for item in _as_list(coverage.get("omitted")):
        if not isinstance(item, dict):
            raise ValueError("coverage.omitted entries must be objects")
        source = _clean(item.get("source"))
        reason = _clean(item.get("reason"))
        if source not in known_sources or len(reason) < 5:
            raise ValueError("each omitted source needs a known alias and a brief reason")
        omitted[source] = reason
    overlap = parser.source_aliases & set(omitted)
    if overlap:
        raise ValueError(f"sources cannot be both used and omitted: {sorted(overlap)}")
    uncovered = sorted(known_sources - parser.source_aliases - set(omitted))
    if uncovered:
        raise ValueError(f"authored HTML must use or explicitly omit every source: {uncovered}")
    if known_evidence and not parser.evidence_aliases:
        raise ValueError("authored HTML does not cite the supplied evidence ledger")
    if parser.visuals_without_evidence:
        raise ValueError(
            "every quantitative figure/SVG/canvas needs data-evidence or data-decoration=true "
            f"(unbound={parser.visuals_without_evidence[:10]})"
        )
    try:
        validate_and_prepare_html(html, session_id="default")
    except ArtifactValidationError as exc:
        raise ValueError(f"authored artifact safety failed: {exc.code}: {exc}") from exc
    styles = "\n".join(re.findall(r"<style\b[^>]*>(.*?)</style>", html, re.IGNORECASE | re.DOTALL))
    forbidden_css = {
        "stylesheet imports": r"@import\b|@namespace\b",
        "executable CSS": r"expression\s*\(|javascript\s*:|behavior\s*:|-moz-binding\s*:",
        "generated claim text": r"\bcontent\s*:",
    }
    for name, pattern in forbidden_css.items():
        if re.search(pattern, styles, re.IGNORECASE):
            raise ValueError(f"authored CSS contains forbidden {name}")
    return {
        "coverage": {"used": sorted(parser.source_aliases), "omitted": omitted},
        "evidence_aliases": sorted(parser.evidence_aliases),
        "claim_candidates": parser.claims[:250],
        "script_count": parser.script_count,
    }


def _review_document_excerpt(html: str) -> str:
    excerpt = re.sub(r"<style\b[^>]*>.*?</style>", "<style>[CSS omitted]</style>", html, flags=re.I | re.S)
    excerpt = re.sub(
        r"<script\b(?![^>]*data-dc-author-coverage)[^>]*>.*?</script>",
        "<script>[JavaScript omitted]</script>",
        excerpt,
        flags=re.I | re.S,
    )
    return excerpt[:140_000]


async def _stream_text(
    llm: LLMProvider,
    *,
    system: str,
    prompt: str,
    timeout_seconds: int,
    max_output_chars: int,
    reasoning_effort: str,
    text_verbosity: str,
) -> str:
    chunks: list[str] = []
    size = 0
    async with asyncio.timeout(timeout_seconds):
        async for event in llm.stream_turn(
            [Message.user(prompt)],
            system=system,
            tools=[],
            reasoning_effort=reasoning_effort,
            text_verbosity=text_verbosity,
        ):
            if isinstance(event, TextDeltaEvent):
                chunks.append(event.text)
                size += len(event.text)
                if size > max_output_chars:
                    raise ValueError(f"model output exceeded {max_output_chars} characters")
    return "".join(chunks)


async def _review_authored_evidence(
    llm: LLMProvider,
    *,
    dossier: str,
    html: str,
    validation: dict[str, Any],
    contract: dict[str, Any],
    timeout_seconds: int,
) -> dict[str, Any]:
    system = """You are an independent evidence editor reviewing an authored analytical report. Return one JSON object only: {"status":"pass|attention_required","findings":[{"anchor":"element id or description","evidence_aliases":["ev-1"],"issue":"specific unsupported, overstated, causal, numeric, caveat, or visual-fidelity problem","recommendation":"specific correction"}]}.

Check authored wording and quantitative visuals against the supplied dossier. Flag unsupported claims, descriptive-to-causal escalation, changed units/denominators, invented values/categories, materially misleading visual encodings, uncited substantive claims, and omitted caveats that change the conclusion. Do not demand verbatim source prose or a particular layout. Original synthesis and editorial language are allowed when entailed. Return pass with an empty findings list when no material evidence problem is visible."""
    prompt = (
        dossier
        + "\n\n# Authored evidence markers\n\n"
        + json.dumps(validation.get("claim_candidates", []), ensure_ascii=False, indent=2)
        + "\n\n# Authored document excerpt\n\n"
        + _review_document_excerpt(html)
    )
    response = await _stream_text(
        llm,
        system=system,
        prompt=prompt,
        timeout_seconds=timeout_seconds,
        max_output_chars=_CREATIVE_REVIEW_MAX_OUTPUT_CHARS,
        reasoning_effort="medium",
        text_verbosity="low",
    )
    candidate = _parse_json_object(response)
    status = _clean(candidate.get("status")).lower()
    findings = candidate.get("findings")
    if status not in {"pass", "attention_required"} or not isinstance(findings, list):
        raise ValueError("evidence reviewer returned an invalid status/findings contract")
    normalized: list[dict[str, Any]] = []
    known_evidence = {
        _clean(item.get("alias")) for item in contract.get("evidence", [])
        if isinstance(item, dict) and _clean(item.get("alias"))
    }
    for finding in findings[:30]:
        if not isinstance(finding, dict):
            continue
        issue = _prompt_text(finding.get("issue"), 1_000)
        if not issue:
            continue
        aliases = [_clean(item) for item in _as_list(finding.get("evidence_aliases")) if _clean(item)][:12]
        if any(alias not in known_evidence for alias in aliases):
            raise ValueError("evidence reviewer referenced an unknown evidence alias")
        normalized.append({
            "anchor": _prompt_text(finding.get("anchor"), 300),
            "evidence_aliases": aliases,
            "issue": issue,
            "recommendation": _prompt_text(finding.get("recommendation"), 1_000),
        })
    if status == "pass" and normalized:
        status = "attention_required"
    if status == "attention_required" and not normalized:
        raise ValueError("evidence reviewer requested attention without findings")
    return {"schema": 1, "status": status, "findings": normalized}


async def _author_creative_document(
    storyboard: dict[str, Any],
    *,
    cfg: dict[str, Any],
    llm: LLMProvider | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    original = copy.deepcopy(storyboard)
    try:
        dossier, contract = build_creative_author_dossier(original, cfg)
    except Exception as exc:
        record = {"schema": VISUAL_AUTHOR_SCHEMA, "mode": "creative"}
        return _fallback_or_raise(original, record, "creative", f"{type(exc).__name__}: {exc}")
    record: dict[str, Any] = {
        "schema": VISUAL_AUTHOR_SCHEMA,
        "mode": "creative",
        "dossier_sha256": contract["dossier_sha256"],
        "source_count": len(contract["sources"]),
        "evidence_target_count": len(contract["evidence"]),
    }
    if llm is None:
        return _fallback_or_raise(original, record, "creative", "No LLM provider is available for the creative report author.")
    system, prompt = build_creative_author_prompt(dossier)
    record["prompt_sha256"] = hashlib.sha256((system + "\n" + prompt).encode("utf-8")).hexdigest()
    try:
        response = await _stream_text(
            llm,
            system=system,
            prompt=prompt,
            timeout_seconds=cfg["timeout_seconds"],
            max_output_chars=cfg["max_output_chars"],
            reasoning_effort="medium",
            text_verbosity="high",
        )
        html = _parse_authored_html(response)
        validation = validate_authored_document(html, contract)
        evidence_review = await _review_authored_evidence(
            llm,
            dossier=dossier,
            html=html,
            validation=validation,
            contract=contract,
            timeout_seconds=cfg["timeout_seconds"],
        )
        repair_count = 0
        if evidence_review["status"] == "attention_required" and cfg.get("max_repair_passes", 0):
            repair_prompt = (
                dossier
                + "\n\n# Required evidence repairs\n\n"
                + json.dumps(evidence_review["findings"], ensure_ascii=False, indent=2)
                + "\n\nRevise the complete document below. Return the complete corrected HTML only.\n\n"
                + html
            )
            repaired_response = await _stream_text(
                llm,
                system=system,
                prompt=repair_prompt,
                timeout_seconds=cfg["timeout_seconds"],
                max_output_chars=cfg["max_output_chars"],
                reasoning_effort="medium",
                text_verbosity="high",
            )
            html = _parse_authored_html(repaired_response)
            validation = validate_authored_document(html, contract)
            evidence_review = await _review_authored_evidence(
                llm,
                dossier=dossier,
                html=html,
                validation=validation,
                contract=contract,
                timeout_seconds=cfg["timeout_seconds"],
            )
            repair_count = 1
    except Exception as exc:
        return _fallback_or_raise(original, record, "creative", f"{type(exc).__name__}: {exc}")

    applied = copy.deepcopy(original)
    applied["authored_document"] = {
        "schema": 1,
        "html": html,
        "contract": contract,
        "coverage": validation["coverage"],
        "evidence_review": evidence_review,
        "dossier": dossier,
        "dossier_sha256": contract["dossier_sha256"],
    }
    record.update({
        "status": "applied",
        "applied": True,
        "source": "llm_full_document",
        "document_sha256": hashlib.sha256(html.encode("utf-8")).hexdigest(),
        "coverage": validation["coverage"],
        "evidence_review": evidence_review,
        "repair_count": repair_count,
        "script_count": validation["script_count"],
    })
    applied["visual_author"] = record
    return applied, record


async def author_report_visuals(
    storyboard: dict[str, Any],
    *,
    config: dict[str, Any] | None = None,
    llm: LLMProvider | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run full-document creative authoring or the bounded runtime editor.

    Creative and runtime authoring fall back to the unmodified storyboard when
    generation, evidence review, or validation fails. ``required`` retains the
    bounded editor's fail-closed audit behavior.
    """
    cfg = visual_author_config({}, config)
    mode = cfg["mode"]
    original = copy.deepcopy(storyboard)
    if mode == "off":
        record = {
            "schema": VISUAL_AUTHOR_SCHEMA,
            "mode": mode,
            "status": "disabled",
            "applied": False,
        }
        baseline = _clean(cfg.get("baseline"))
        if baseline:
            record["baseline"] = baseline
            record["source"] = "renderer"
        original["visual_author"] = record
        return original, record

    if mode == "creative":
        return await _author_creative_document(original, cfg=cfg, llm=llm)

    catalog = build_visual_author_catalog(original, cfg)
    catalog_hash = _stable_sha256(catalog)
    record: dict[str, Any] = {
        "schema": VISUAL_AUTHOR_SCHEMA,
        "mode": mode,
        "catalog_sha256": catalog_hash,
        "fact_count": len(catalog["facts"]),
        "section_count": len(catalog["sections"]),
    }

    if mode == "provided":
        candidate = cfg.get("spec")
        if not isinstance(candidate, dict):
            raise ValueError("visual_author.spec must be a dictionary in provided mode")
        try:
            spec = validate_visual_spec(candidate, catalog)
        except ValueError as exc:
            raise ValueError(f"visual_author.spec is invalid: {exc}") from exc
        applied = apply_visual_spec(original, spec, catalog)
        record.update({
            "status": "applied",
            "applied": True,
            "source": "provided",
            "spec": spec,
            "plan_review": review_visual_plan(spec, catalog),
        })
        applied["visual_author"] = record
        return applied, record

    if llm is None:
        return _fallback_or_raise(original, record, mode, "No LLM provider is available for the runtime visual author.")

    system, prompt = build_visual_author_prompt(catalog)
    record["prompt_sha256"] = hashlib.sha256((system + "\n" + prompt).encode("utf-8")).hexdigest()
    try:
        chunks: list[str] = []
        async with asyncio.timeout(cfg["timeout_seconds"]):
            async for event in llm.stream_turn(
                [Message.user(prompt)],
                system=system,
                tools=[],
                reasoning_effort="low",
                text_verbosity="low",
            ):
                if isinstance(event, TextDeltaEvent):
                    chunks.append(event.text)
                    if sum(len(chunk) for chunk in chunks) > cfg["max_output_chars"]:
                        raise ValueError(
                            f"model output exceeded visual_author.max_output_chars ({cfg['max_output_chars']})"
                        )
        candidate = _parse_json_object("".join(chunks))
        spec = validate_visual_spec(candidate, catalog)
    except Exception as exc:  # A malformed generation must not alter the report.
        return _fallback_or_raise(original, record, mode, f"{type(exc).__name__}: {exc}")

    applied = apply_visual_spec(original, spec, catalog)
    record.update({
        "status": "applied",
        "applied": True,
        "source": "runtime",
        "spec": spec,
        "plan_review": review_visual_plan(spec, catalog),
    })
    applied["visual_author"] = record
    return applied, record


class _CreativeLayoutParser(HTMLParser):
    """Validate structural authoring HTML without accepting visible copy."""

    _ALLOWED_TAGS = {"div", "section", "article", "aside"}
    _ALLOWED_ATTRS = {"class", "role", "data-layout", "data-zone", "data-role"}
    _VALUE_RE = re.compile(r"^[A-Za-z0-9 _-]{1,160}$")

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.stack: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag not in self._ALLOWED_TAGS:
            raise ValueError(f"creative.layout_html cannot use <{tag}>")
        for name, value in attrs:
            name = name.lower()
            if name not in self._ALLOWED_ATTRS:
                raise ValueError(f"creative.layout_html cannot use attribute {name!r}")
            if not value or not self._VALUE_RE.fullmatch(value):
                raise ValueError(f"creative.layout_html has an invalid {name!r} value")
        self.stack.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        raise ValueError("creative.layout_html cannot use self-closing elements")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if not self.stack or self.stack.pop() != tag:
            raise ValueError("creative.layout_html has unbalanced structural elements")

    def handle_data(self, data: str) -> None:
        if data.strip():
            raise ValueError("creative.layout_html may contain section placeholders, not visible text")

    def handle_entityref(self, name: str) -> None:
        raise ValueError("creative.layout_html may not add entity text")

    def handle_charref(self, name: str) -> None:
        raise ValueError("creative.layout_html may not add character text")

    def handle_comment(self, data: str) -> None:
        raise ValueError("creative.layout_html may not add comments")

    def handle_decl(self, decl: str) -> None:
        raise ValueError("creative.layout_html may not add declarations")

    def handle_pi(self, data: str) -> None:
        raise ValueError("creative.layout_html may not add processing instructions")

    def close(self) -> None:
        super().close()
        if self.stack:
            raise ValueError("creative.layout_html has unclosed structural elements")


def _validate_creative_layout(value: Any, catalog: dict[str, Any]) -> dict[str, str]:
    creative_catalog = catalog.get("creative") if isinstance(catalog.get("creative"), dict) else {}
    if not creative_catalog.get("enabled"):
        if value not in (None, {}):
            raise ValueError("creative authoring is not enabled for this visual-author run")
        return {}
    if not isinstance(value, dict):
        raise ValueError("creative must be an object in visual_author.mode='creative'")
    layout_html = value.get("layout_html")
    css = value.get("css")
    if not isinstance(layout_html, str) or not layout_html.strip():
        raise ValueError("creative.layout_html must be a non-empty string")
    if not isinstance(css, str) or not css.strip():
        raise ValueError("creative.css must be a non-empty string")
    if len(layout_html) > _CREATIVE_MAX_LAYOUT_CHARS:
        raise ValueError(f"creative.layout_html exceeds {_CREATIVE_MAX_LAYOUT_CHARS} characters")
    if len(css) > _CREATIVE_MAX_CSS_CHARS:
        raise ValueError(f"creative.css exceeds {_CREATIVE_MAX_CSS_CHARS} characters")

    expected = [str(item) for item in creative_catalog.get("section_ids", [])]
    placeholders = re.findall(r"\{\{section:([A-Za-z0-9_.:-]+)\}\}", layout_html)
    if len(placeholders) != len(expected) or set(placeholders) != set(expected):
        missing = sorted(set(expected) - set(placeholders))
        unknown = sorted(set(placeholders) - set(expected))
        duplicate = sorted({item for item in placeholders if placeholders.count(item) > 1})
        raise ValueError(
            "creative.layout_html must place every supplied section exactly once "
            f"(missing={missing}, unknown={unknown}, duplicate={duplicate})"
        )
    structural_html = re.sub(r"\{\{section:[A-Za-z0-9_.:-]+\}\}", "", layout_html)
    parser = _CreativeLayoutParser()
    try:
        parser.feed(structural_html)
        parser.close()
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"creative.layout_html is invalid: {exc}") from exc

    css_without_comments = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    forbidden_css = {
        "remote or embedded assets": r"url\s*\(|image-set\s*\(|https?\s*:|data\s*:|//",
        "external stylesheet directives": r"@import\b|@font-face\b|@namespace\b",
        "generated visible copy": r"\bcontent\s*:",
        "legacy executable CSS": r"expression\s*\(|javascript\s*:|behavior\s*:|-moz-binding\s*:",
        "style-element escape": r"</?style\b|</?script\b|<",
        "escaped-token bypass": r"\\",
    }
    for description, pattern in forbidden_css.items():
        if re.search(pattern, css_without_comments, re.IGNORECASE):
            raise ValueError(f"creative.css contains forbidden {description}")
    if css_without_comments.count("{") != css_without_comments.count("}"):
        raise ValueError("creative.css has unbalanced blocks")
    return {"layout_html": layout_html.strip(), "css": css.strip()}


def validate_applied_creative_layout(storyboard: dict[str, Any]) -> dict[str, str]:
    """Revalidate persisted creative layout/CSS before every render."""
    value = storyboard.get("creative_layout")
    if not isinstance(value, dict):
        return {}
    catalog = build_visual_author_catalog(
        storyboard,
        {"mode": "creative", "allow_story_reorder": False},
    )
    return _validate_creative_layout(value, catalog)


def validate_visual_spec(candidate: Any, catalog: dict[str, Any]) -> dict[str, Any]:
    """Validate an untrusted model response against the generated catalog."""
    if not isinstance(candidate, dict):
        raise ValueError("visual spec must be a JSON object")
    if candidate.get("schema") != VISUAL_AUTHOR_SCHEMA:
        raise ValueError(f"visual spec schema must be {VISUAL_AUTHOR_SCHEMA}")

    known_sections = {entry["section_id"]: entry for entry in catalog.get("sections", []) if isinstance(entry, dict)}
    known_facts = {entry["fact_id"]: entry for entry in catalog.get("facts", []) if isinstance(entry, dict)}
    theme = _clean(candidate.get("theme") or "")
    if theme and theme not in THEME_TOKENS:
        raise ValueError(f"unknown theme {theme!r}")

    sections_out: list[dict[str, Any]] = []
    seen_sections: set[str] = set()
    claimed_facts: set[str] = set()
    for item in _required_list(candidate.get("sections", []), "sections"):
        if not isinstance(item, dict):
            raise ValueError("each visual section must be an object")
        section_id = _clean(item.get("section_id"))
        capability = known_sections.get(section_id)
        if capability is None:
            raise ValueError(f"unknown section_id {section_id!r}")
        if section_id in seen_sections:
            raise ValueError(f"section_id {section_id!r} appears more than once")
        seen_sections.add(section_id)
        normalized: dict[str, Any] = {"section_id": section_id}
        surface = _clean(item.get("surface")).lower()
        if surface:
            if surface not in capability["surfaces"]:
                raise ValueError(f"surface {surface!r} is not allowed for {section_id!r}")
            normalized["surface"] = surface
        layout = _clean(item.get("layout")).lower().replace("-", "_")
        if layout:
            if layout not in capability.get("layouts", []):
                raise ValueError(f"layout {layout!r} is not allowed for {section_id!r}")
            normalized["layout"] = layout
        evidence = _clean(item.get("evidence_presentation")).lower().replace("-", "_")
        if evidence:
            if evidence not in capability.get("evidence_presentations", []):
                raise ValueError(f"evidence_presentation {evidence!r} is not allowed for {section_id!r}")
            normalized["evidence_presentation"] = evidence
        for field, fact_use in _DISPLAY_FACT_FIELDS.items():
            selections = _validate_fact_selections(
                item.get(field, []),
                field=field,
                fact_use=fact_use,
                known_facts=known_facts,
                claimed_facts=claimed_facts,
                section_id=section_id,
                insight_id="",
            )
            if selections:
                normalized[field] = selections
        if len(normalized) == 1:
            raise ValueError(f"section {section_id!r} has no visual choice")
        sections_out.append(normalized)

    insights_out: list[dict[str, Any]] = []
    seen_insights: set[str] = set()
    valid_insights = {
        _clean(entry.get("insight_id")): _clean(entry.get("section_id"))
        for entry in catalog.get("insights", [])
        if isinstance(entry, dict) and _clean(entry.get("insight_id"))
    }
    for item in _required_list(candidate.get("insights", []), "insights"):
        if not isinstance(item, dict):
            raise ValueError("each visual insight must be an object")
        insight_id = _clean(item.get("insight_id"))
        if not insight_id or insight_id not in valid_insights:
            raise ValueError(f"unknown insight_id {insight_id!r}")
        if insight_id in seen_insights:
            raise ValueError(f"insight_id {insight_id!r} appears more than once")
        seen_insights.add(insight_id)
        normalized = {"insight_id": insight_id}
        for field, fact_use in _DISPLAY_FACT_FIELDS.items():
            selections = _validate_fact_selections(
                item.get(field, []),
                field=field,
                fact_use=fact_use,
                known_facts=known_facts,
                claimed_facts=claimed_facts,
                section_id=valid_insights[insight_id],
                insight_id=insight_id,
            )
            if selections:
                normalized[field] = selections
        if len(normalized) == 1:
            raise ValueError(f"insight {insight_id!r} has no selected facts")
        insights_out.append(normalized)

    composition_out = _validate_composition(candidate.get("composition", []), catalog)
    creative_out = _validate_creative_layout(candidate.get("creative"), catalog)

    return {
        "schema": VISUAL_AUTHOR_SCHEMA,
        **({"theme": theme} if theme else {}),
        "sections": sections_out,
        "insights": insights_out,
        **({"composition": composition_out} if composition_out else {}),
        **({"creative": creative_out} if creative_out else {}),
    }


def apply_visual_spec(storyboard: dict[str, Any], spec: dict[str, Any], catalog: dict[str, Any]) -> dict[str, Any]:
    """Materialize a validated visual spec without introducing new copy."""
    applied = copy.deepcopy(storyboard)
    section_plan = applied.get("section_plan", [])
    _apply_composition(section_plan, spec.get("composition", []), catalog)
    by_section = {
        _section_id(planned, index): planned
        for index, planned in enumerate(section_plan)
        if isinstance(planned, dict)
    }
    facts = {entry["fact_id"]: entry for entry in catalog.get("facts", []) if isinstance(entry, dict)}
    for choice in spec.get("sections", []):
        planned = by_section[choice["section_id"]]
        data = planned.setdefault("data", {})
        if not isinstance(data, dict):
            data = {}
            planned["data"] = data
        if choice.get("surface"):
            data["surface_variant"] = choice["surface"]
            if choice["surface"] == "strong" and _clean(planned.get("section_type")).lower() in {
                "chart", "chart_interpretation", "advanced_visual", "filterable_chart", "chart_table_explorer",
            }:
                data["emphasis"] = "hero"
        if choice.get("layout"):
            data["layout_variant"] = choice["layout"]
        if choice.get("evidence_presentation"):
            data["evidence_presentation"] = choice["evidence_presentation"]
            if _clean(planned.get("section_type")).lower() == "evidence_trace":
                data["presentation"] = choice["evidence_presentation"]

        _apply_display_fact_choices(data, choice, facts=facts)

    by_insight: dict[str, dict[str, Any]] = {}
    for planned in section_plan:
        if not isinstance(planned, dict) or _clean(planned.get("section_type")).lower() != "insight_grid":
            continue
        data = planned.get("data") if isinstance(planned.get("data"), dict) else {}
        for index, item in enumerate(data.get("items", [])):
            if isinstance(item, dict):
                by_insight[_insight_id(item, index)] = item
    for choice in spec.get("insights", []):
        item = by_insight.get(choice["insight_id"])
        if item is not None:
            _apply_display_fact_choices(item, choice, facts=facts, legacy_insight_slots=True)

    if spec.get("theme"):
        applied["visual_theme"] = {"name": spec["theme"], "tokens": visual_theme_tokens(spec["theme"])}
    if isinstance(spec.get("creative"), dict):
        applied["creative_layout"] = copy.deepcopy(spec["creative"])
    return applied


def _section_capability(section_type: str) -> dict[str, list[str]] | None:
    if section_type == "header":
        return {"surfaces": ["strong"]}
    if section_type == "insight_grid":
        return {
            "surfaces": ["quiet"],
            "layouts": sorted(_VALID_INSIGHT_LAYOUTS),
            "evidence_presentations": sorted(_VALID_INSIGHT_EVIDENCE),
        }
    if section_type in {"chart", "chart_interpretation", "advanced_visual", "filterable_chart", "chart_table_explorer", "interactive_table", "table", "selector_panel"}:
        return {"surfaces": ["strong", "evidence"], "evidence_presentations": sorted(_VALID_CHART_EVIDENCE)}
    if section_type == "evidence_trace":
        return {"surfaces": ["trust"], "evidence_presentations": sorted(_VALID_TRACE_EVIDENCE)}
    if section_type in {"methodology_block", "hypothesis_ledger", "evidence_rail", "ledger_timeline"}:
        return {"surfaces": ["trust"]}
    if section_type in {"metric_row", "narrative_band", "findings", "entity_card_grid", "comparison", "checklist", "explanation", "text", "callout"}:
        return {"surfaces": ["quiet"]}
    return None


def _creative_asset_semantics(
    section_type: str,
    data: dict[str, Any],
    planned: dict[str, Any],
) -> dict[str, Any]:
    """Expose report-shaping metadata without exposing aggregate row values."""
    context: dict[str, Any] = {
        "semantic_role": _clean(data.get("semantic_role") or planned.get("semantic_role")),
        "editorial_role": _clean(data.get("editorial_role") or planned.get("editorial_role")),
        "caption": _prompt_text(data.get("caption") or data.get("dek"), 700),
        "interpretation": _prompt_text(data.get("interpretation"), 900),
        "caveat": _prompt_text(data.get("caveat") or data.get("limitations"), 600),
    }
    records = data.get("records") if isinstance(data.get("records"), list) else data.get("rows")
    if isinstance(records, list):
        context["aggregate_record_count"] = len(records)
        columns: list[str] = []
        supplied_columns = data.get("columns")
        if isinstance(supplied_columns, list):
            for value in supplied_columns[:24]:
                if isinstance(value, dict):
                    value = value.get("key") or value.get("field") or value.get("name") or value.get("label")
                cleaned = _prompt_text(value, 80)
                if cleaned:
                    columns.append(cleaned)
        elif records and isinstance(records[0], dict):
            columns = [_prompt_text(value, 80) for value in list(records[0])[:24]]
        if columns:
            context["aggregate_columns"] = columns

    visual = data.get("visual") if isinstance(data.get("visual"), dict) else {}
    if visual:
        context["visual_type"] = _clean(visual.get("type") or visual.get("visual_type"))
        mappings = {
            _clean(role): _prompt_text(field, 80)
            for role, field in list(visual.items())[:24]
            if role not in {"type", "visual_type", "options", "style"}
            and isinstance(field, (str, int, float))
            and _clean(role)
            and _prompt_text(field, 80)
        }
        if mappings:
            context["field_mappings"] = mappings

    figure = data.get("figure_json") if isinstance(data.get("figure_json"), dict) else data.get("figure")
    if isinstance(figure, dict):
        traces = figure.get("data") if isinstance(figure.get("data"), list) else []
        trace_types = sorted({
            _clean(trace.get("type") or "scatter")
            for trace in traces
            if isinstance(trace, dict)
        })
        context["chart_trace_count"] = len(traces)
        if trace_types:
            context["chart_trace_types"] = trace_types

    evidence_ids: list[str] = []
    for value in _as_list(data.get("evidence") or data.get("evidence_refs")):
        if isinstance(value, dict):
            ref = _clean(value.get("ref") or value.get("id") or value.get("cell_id") or value.get("artifact_id"))
        else:
            ref = _clean(value)
        if ref and ref not in evidence_ids:
            evidence_ids.append(ref)
    if evidence_ids:
        context["evidence_ids"] = evidence_ids[:20]
    return {key: value for key, value in context.items() if value not in ("", [], {}, None)}


def _validate_fact_selections(
    value: Any,
    *,
    field: str,
    fact_use: str,
    known_facts: dict[str, dict[str, Any]],
    claimed_facts: set[str],
    section_id: str,
    insight_id: str,
) -> list[Any]:
    selections = _required_list(value, field)
    if len(selections) > _MAX_DISPLAY_FACTS[fact_use]:
        raise ValueError(f"{field} may select at most {_MAX_DISPLAY_FACTS[fact_use]} source facts")
    selected: list[Any] = []
    local_facts: set[str] = set()
    for value in selections:
        tone = ""
        if field == "pills":
            if not isinstance(value, dict):
                raise ValueError("pill selections must be objects with fact_id and tone")
            fact_id = _clean(value.get("fact_id"))
            tone = _clean(value.get("tone") or "accent").lower()
            if tone not in _VALID_PILL_TONES:
                raise ValueError(f"invalid pill tone {tone!r}")
        else:
            if not isinstance(value, str):
                raise ValueError(f"{field} selections must be fact_id strings")
            fact_id = _clean(value)
        fact = known_facts.get(fact_id)
        if fact is None:
            raise ValueError(f"unknown fact_id {fact_id!r}")
        if _clean(fact.get("section_id")) != section_id:
            raise ValueError(f"fact_id {fact_id!r} does not belong to section {section_id!r}")
        if _clean(fact.get("insight_id")) != insight_id:
            owner = _clean(fact.get("insight_id")) or "the section"
            expected = insight_id or "the section"
            raise ValueError(f"fact_id {fact_id!r} belongs to {owner!r}, not {expected!r}")
        if fact_use not in set(fact.get("uses", [])):
            raise ValueError(f"fact_id {fact_id!r} cannot be used as a {fact_use}")
        if fact_id in local_facts:
            raise ValueError(f"fact_id {fact_id!r} is repeated in {field}")
        if fact_id in claimed_facts:
            raise ValueError(f"fact_id {fact_id!r} is repeated across the visual plan")
        local_facts.add(fact_id)
        claimed_facts.add(fact_id)
        selected.append({"fact_id": fact_id, "tone": tone} if field == "pills" else fact_id)
    return selected


def _apply_display_fact_choices(
    data: dict[str, Any],
    choice: dict[str, Any],
    *,
    facts: dict[str, dict[str, Any]],
    legacy_insight_slots: bool = False,
) -> None:
    """Write model-selected source facts into renderer-owned display slots."""
    for field, fact_use in _DISPLAY_FACT_FIELDS.items():
        selected = choice.get(field)
        if not selected:
            continue
        target = f"visual_{field}"
        if field == "pills":
            data[target] = [
                {"label": facts[selection["fact_id"]]["text"], "tone": selection["tone"]}
                for selection in selected
            ]
        else:
            data[target] = [facts[fact_id]["text"] for fact_id in selected]
        if legacy_insight_slots:
            legacy_key = {
                "pills": "display_pills",
                "scan_points": "scan_points",
                "examples": "representative_examples",
                "annotations": "annotations",
            }[field]
            data[legacy_key] = copy.deepcopy(data[target])


def review_visual_plan(spec: dict[str, Any], catalog: dict[str, Any]) -> dict[str, Any]:
    """Return an advisory surface/card-budget review for one validated plan.

    This is intentionally not a rigid card quota. The hard validator prevents
    fabricated/repeated facts; this review exposes composition pressure for a
    human or later visual evaluator to decide in context.
    """
    section_catalog = {
        _clean(entry.get("section_id")): entry
        for entry in catalog.get("sections", [])
        if isinstance(entry, dict)
    }
    findings: list[dict[str, Any]] = []
    strong = [
        _clean(choice.get("section_id"))
        for choice in spec.get("sections", [])
        if isinstance(choice, dict) and _clean(choice.get("surface")) == "strong"
    ]
    if len(strong) > 1:
        findings.append({
            "id": "multiple_strong_surfaces",
            "severity": "info",
            "claim": "The visual plan gives more than one section the strongest evidence treatment.",
            "recommendation": "Keep the strongest treatment for the primary evidence act unless the sections are a deliberate direct comparison.",
            "sections": strong,
        })
    for choice in spec.get("sections", []):
        if not isinstance(choice, dict) or choice.get("layout") != "card_grid":
            continue
        section_id = _clean(choice.get("section_id"))
        count = int(section_catalog.get(section_id, {}).get("item_count") or 0)
        if count < 2:
            findings.append({
                "id": "card_grid_without_peer_comparison",
                "severity": "info",
                "claim": "A card-grid layout was selected without multiple peer items to compare.",
                "recommendation": "Use a flat editorial treatment for a single narrative finding.",
                "sections": [section_id],
            })
    choices = {
        _clean(choice.get("section_id")): choice
        for choice in spec.get("sections", [])
        if isinstance(choice, dict)
    }
    default_surface = {
        "header": "strong",
        "insight_grid": "quiet",
        "evidence_trace": "trust",
        "methodology_block": "trust",
        "hypothesis_ledger": "trust",
        "evidence_rail": "trust",
        "ledger_timeline": "trust",
        "chart": "evidence",
        "chart_interpretation": "evidence",
        "advanced_visual": "evidence",
        "filterable_chart": "evidence",
        "chart_table_explorer": "evidence",
        "interactive_table": "evidence",
        "table": "evidence",
        "selector_panel": "evidence",
    }
    narrative_kinds = {"narrative_band", "insight_grid", "findings", "callout", "text", "explanation"}
    narrative_run: list[str] = []
    for entry in catalog.get("sections", []):
        if not isinstance(entry, dict):
            continue
        section_id = _clean(entry.get("section_id"))
        section_type = _clean(entry.get("section_type"))
        surface = _clean(choices.get(section_id, {}).get("surface") or default_surface.get(section_type, "quiet"))
        if section_type in narrative_kinds and surface == "quiet":
            narrative_run.append(section_id)
            continue
        if len(narrative_run) >= 3:
            findings.append({
                "id": "repeated_narrative_framing",
                "severity": "info",
                "claim": "Three or more consecutive narrative sections use the same framed quiet-surface treatment.",
                "recommendation": "Let one section carry the frame and flatten or combine adjacent narrative material unless each has a distinct editorial job.",
                "sections": list(narrative_run),
            })
        narrative_run = []
    if len(narrative_run) >= 3:
        findings.append({
            "id": "repeated_narrative_framing",
            "severity": "info",
            "claim": "Three or more consecutive narrative sections use the same framed quiet-surface treatment.",
            "recommendation": "Let one section carry the frame and flatten or combine adjacent narrative material unless each has a distinct editorial job.",
            "sections": list(narrative_run),
        })
    known_ids = set(section_catalog)
    children_by_parent: dict[str, list[str]] = {}
    for entry in catalog.get("sections", []):
        if not isinstance(entry, dict):
            continue
        section_id = _clean(entry.get("section_id"))
        parent = _clean(entry.get("surface_parent_id"))
        nested = bool(entry.get("nested_surface"))
        if nested and not parent:
            findings.append({
                "id": "nested_surface_without_relationship",
                "severity": "info",
                "claim": "A source section declares nested surface treatment without identifying its parent evidence or trust surface.",
                "recommendation": "Declare surface_parent_id or flatten the inner frame so the reader can understand the hierarchy.",
                "sections": [section_id],
            })
        if parent:
            if parent not in known_ids or parent == section_id:
                findings.append({
                    "id": "nested_surface_without_relationship",
                    "severity": "info",
                    "claim": "A nested surface points to a missing or self-referential parent.",
                    "recommendation": "Use a valid parent section ID or flatten the inner frame.",
                    "sections": [section_id],
                })
            else:
                children_by_parent.setdefault(parent, []).append(section_id)
    for parent, children in children_by_parent.items():
        if len(children) > 2:
            findings.append({
                "id": "repeated_nested_surface_children",
                "severity": "info",
                "claim": "One parent surface contains more than two separately framed child treatments.",
                "recommendation": "Use a single evidence rail, list, or grouped container unless the children are a true comparison set.",
                "sections": [parent, *children],
            })
    selected_facts = sum(
        len(choice.get(field, []))
        for collection in (spec.get("sections", []), spec.get("insights", []))
        for choice in collection
        if isinstance(choice, dict)
        for field in _DISPLAY_FACT_FIELDS
        if isinstance(choice.get(field), list)
    )
    return {
        "status": "attention_recommended" if findings else "pass",
        "strong_surface_count": len(strong),
        "selected_fact_count": selected_facts,
        "composition_zone_count": len(spec.get("composition", [])) if isinstance(spec.get("composition"), list) else 0,
        "findings": findings,
        "guidance": "Card and surface budgets are composition guidance, not fixed quotas; avoid nested or repeated framing for purely narrative material.",
    }


def _build_composition_catalog(section_plan: list[Any], config: dict[str, Any]) -> list[dict[str, Any]]:
    """Expose only author-declared reorderable source blocks to the model.

    Reordering is opt-in and zone-bounded. A source recipe may label consecutive
    sections with ``visual_author_story_zone`` and ``visual_author_story_block``;
    the model can choose the order of those blocks, but cannot split a block or
    move content across a zone. This is a real composition decision with a
    deterministic, auditable safety boundary.
    """
    if not config.get("allow_story_reorder"):
        return []
    by_zone: dict[str, list[tuple[int, str, str]]] = {}
    for index, planned in enumerate(section_plan):
        if not isinstance(planned, dict):
            continue
        data = planned.get("data") if isinstance(planned.get("data"), dict) else {}
        zone = _clean(planned.get("visual_author_story_zone") or data.get("visual_author_story_zone"))
        block = _clean(planned.get("visual_author_story_block") or data.get("visual_author_story_block"))
        if bool(zone) != bool(block):
            raise ValueError("visual author story reordering requires both visual_author_story_zone and visual_author_story_block")
        if zone:
            by_zone.setdefault(zone, []).append((index, block, _section_id(planned, index)))

    zones: list[dict[str, Any]] = []
    for zone_id, entries in by_zone.items():
        indexes = [entry[0] for entry in entries]
        if indexes != list(range(min(indexes), max(indexes) + 1)):
            raise ValueError(f"visual author story zone {zone_id!r} must be one contiguous section range")
        blocks: list[dict[str, Any]] = []
        seen_blocks: set[str] = set()
        current_block = ""
        current_ids: list[str] = []
        for _, block_id, section_id in entries:
            if block_id != current_block:
                if current_block:
                    blocks.append({"block_id": current_block, "section_ids": current_ids})
                    seen_blocks.add(current_block)
                if block_id in seen_blocks:
                    raise ValueError(f"visual author story block {block_id!r} is not contiguous in zone {zone_id!r}")
                current_block = block_id
                current_ids = []
            current_ids.append(section_id)
        if current_block:
            blocks.append({"block_id": current_block, "section_ids": current_ids})
        if len(blocks) >= 2:
            zones.append({"zone_id": zone_id, "blocks": blocks})
    return zones


def _validate_composition(value: Any, catalog: dict[str, Any]) -> list[dict[str, Any]]:
    entries = _required_list(value, "composition")
    available = {
        _clean(zone.get("zone_id")): zone
        for zone in catalog.get("composition", [])
        if isinstance(zone, dict) and _clean(zone.get("zone_id"))
    }
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("each composition entry must be an object")
        zone_id = _clean(entry.get("zone_id"))
        zone = available.get(zone_id)
        if zone is None:
            raise ValueError(f"unknown composition zone {zone_id!r}")
        if zone_id in seen:
            raise ValueError(f"composition zone {zone_id!r} appears more than once")
        order = _required_list(entry.get("order"), "composition.order")
        if not all(isinstance(block_id, str) for block_id in order):
            raise ValueError("composition.order must contain block ID strings")
        expected = [_clean(block.get("block_id")) for block in zone.get("blocks", []) if isinstance(block, dict)]
        cleaned_order = [_clean(block_id) for block_id in order]
        if len(cleaned_order) != len(expected) or set(cleaned_order) != set(expected):
            raise ValueError(f"composition.order for {zone_id!r} must contain every declared block exactly once")
        seen.add(zone_id)
        normalized.append({"zone_id": zone_id, "order": cleaned_order})
    return normalized


def _apply_composition(section_plan: Any, choices: Any, catalog: dict[str, Any]) -> None:
    if not isinstance(section_plan, list) or not isinstance(choices, list) or not choices:
        return
    zones = {
        _clean(zone.get("zone_id")): zone
        for zone in catalog.get("composition", [])
        if isinstance(zone, dict)
    }
    by_section = {
        _section_id(planned, index): planned
        for index, planned in enumerate(section_plan)
        if isinstance(planned, dict)
    }
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        zone = zones.get(_clean(choice.get("zone_id")))
        if not isinstance(zone, dict):
            continue
        blocks = {
            _clean(block.get("block_id")): [section_id for section_id in block.get("section_ids", []) if isinstance(section_id, str)]
            for block in zone.get("blocks", [])
            if isinstance(block, dict)
        }
        original_ids = [section_id for block_ids in blocks.values() for section_id in block_ids]
        positions = [
            index for index, planned in enumerate(section_plan)
            if isinstance(planned, dict) and _section_id(planned, index) in set(original_ids)
        ]
        if not positions:
            continue
        replacement = [by_section[section_id] for block_id in choice.get("order", []) for section_id in blocks.get(_clean(block_id), [])]
        start, end = min(positions), max(positions)
        if len(replacement) == (end - start + 1):
            section_plan[start:end + 1] = replacement


def _collect_facts(
    storyboard: dict[str, Any],
    config: dict[str, Any],
    section_ids: set[str],
    insight_targets: dict[str, str],
) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(
        raw: Any,
        *,
        default_section: str = "",
        default_insight: str = "",
        default_uses: list[str] | None = None,
        generated_id: str = "",
        explicit: bool = False,
    ) -> None:
        if isinstance(raw, dict):
            fact_id = _clean(raw.get("fact_id") or raw.get("id") or generated_id)
            text = _clean(raw.get("text") or raw.get("label") or raw.get("value") or raw.get("title"))
            insight_id = _clean(raw.get("insight_id") or raw.get("finding_id") or default_insight)
            section_id = _clean(raw.get("section_id") or raw.get("layout_role") or default_section)
            uses = raw.get("uses") or raw.get("use") or default_uses or []
        else:
            fact_id = generated_id
            text = _clean(raw)
            insight_id = default_insight
            section_id = default_section
            uses = default_uses or []
        if explicit and (not isinstance(raw, dict) or not _clean(raw.get("fact_id") or raw.get("id"))):
            raise ValueError("typed visual-author facts must provide a stable fact_id")
        if not fact_id or not text:
            return
        if insight_id:
            if insight_id not in insight_targets:
                raise ValueError(f"visual-author fact {fact_id!r} must reference a known insight_id")
            if not section_id:
                section_id = insight_targets[insight_id]
            if section_id != insight_targets[insight_id]:
                raise ValueError(f"visual-author fact {fact_id!r} does not belong to the section for {insight_id!r}")
        if not section_id or section_id not in section_ids:
            raise ValueError(f"visual-author fact {fact_id!r} must reference a known section_id")
        if fact_id in seen:
            if explicit:
                raise ValueError(f"visual-author fact ids must be unique; duplicate {fact_id!r}")
            fact_id = _unique_fact_id(f"{section_id}-{default_insight or 'section'}-{fact_id}", seen)
        normalized_uses = _normalise_uses(uses)
        if not normalized_uses:
            raise ValueError(f"visual-author fact {fact_id!r} must allow at least one display use")
        seen.add(fact_id)
        entry = {"fact_id": fact_id, "section_id": section_id, "text": text, "uses": normalized_uses}
        if insight_id:
            entry["insight_id"] = insight_id
        facts.append(entry)

    for index, raw in enumerate(config.get("facts", config.get("source_facts", [])) or []):
        add(raw, generated_id=f"author-fact-{index + 1}", explicit=True)

    for section_index, planned in enumerate(storyboard.get("section_plan", [])):
        if not isinstance(planned, dict):
            continue
        data = planned.get("data") if isinstance(planned.get("data"), dict) else {}
        section_id = _section_id(planned, section_index)
        section_facts = data.get("display_facts") if data.get("display_facts") is not None else data.get("visual_facts", [])
        for fact_index, raw in enumerate(section_facts or []):
            add(
                raw,
                default_section=section_id,
                generated_id=f"section-{section_index + 1}-fact-{fact_index + 1}",
                explicit=data.get("display_facts") is not None,
            )
        if _clean(planned.get("section_type")).lower() != "insight_grid":
            for pill_index, raw in enumerate(_as_list(data.get("pills") or data.get("display_pills"))):
                add(raw, default_section=section_id, default_uses=["pill"], generated_id=f"section-{section_index + 1}-pill-{pill_index + 1}")
            for point_index, raw in enumerate(_as_list(data.get("bullets") or data.get("scan_points"))):
                add(raw, default_section=section_id, default_uses=["scan_point"], generated_id=f"section-{section_index + 1}-scan-{point_index + 1}")
            for example_index, raw in enumerate(_as_list(data.get("representative_examples") or data.get("examples"))):
                add(raw, default_section=section_id, default_uses=["example"], generated_id=f"section-{section_index + 1}-example-{example_index + 1}")
            continue
        for insight_index, item in enumerate(data.get("items", [])):
            if not isinstance(item, dict):
                continue
            insight_id = _insight_id(item, insight_index)
            insight_facts = item.get("display_facts") if item.get("display_facts") is not None else item.get("visual_facts", [])
            for fact_index, raw in enumerate(insight_facts or []):
                add(
                    raw,
                    default_section=section_id,
                    default_insight=insight_id,
                    generated_id=f"insight-{section_index + 1}-{insight_index + 1}-fact-{fact_index + 1}",
                    explicit=item.get("display_facts") is not None,
                )
            for pill_index, raw in enumerate(_as_list(item.get("pills") or item.get("display_pills"))):
                add(raw, default_section=section_id, default_insight=insight_id, default_uses=["pill"], generated_id=f"{insight_id}-pill-{pill_index + 1}")
            for point_index, raw in enumerate(_as_list(item.get("bullets") or item.get("scan_points"))):
                add(raw, default_section=section_id, default_insight=insight_id, default_uses=["scan_point"], generated_id=f"{insight_id}-scan-{point_index + 1}")
            for example_index, raw in enumerate(_as_list(item.get("representative_examples") or item.get("examples"))):
                add(raw, default_section=section_id, default_insight=insight_id, default_uses=["example"], generated_id=f"{insight_id}-example-{example_index + 1}")
    return facts


def _normalise_uses(value: Any) -> list[str]:
    values = value if isinstance(value, list) else [value]
    out: list[str] = []
    for entry in values:
        use = _clean(entry).lower().replace("-", "_")
        if use not in _FACT_USES:
            raise ValueError(f"unknown visual-author fact use {use!r}")
        if use not in out:
            out.append(use)
    return out


def _fallback_or_raise(
    storyboard: dict[str, Any],
    record: dict[str, Any],
    mode: str,
    reason: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    record.update({"status": "fallback", "applied": False, "reason": reason})
    storyboard["visual_author"] = record
    if mode == "required":
        record["status"] = "failed"
        raise VisualAuthorRequiredError(reason, storyboard=storyboard, record=record)
    return storyboard, record


def _parse_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", stripped, re.IGNORECASE | re.DOTALL)
    if fenced:
        stripped = fenced.group(1).strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise ValueError("model did not return one valid JSON object") from exc
    if not isinstance(parsed, dict):
        raise ValueError("model response must be a JSON object")
    return parsed


def _section_id(planned: dict[str, Any], index: int) -> str:
    data = planned.get("data") if isinstance(planned.get("data"), dict) else {}
    return _clean(
        planned.get("visual_author_section_id")
        or data.get("visual_author_section_id")
        or planned.get("layout_role")
        or data.get("section_id")
        or f"section-{index + 1}"
    )


def _insight_id(item: dict[str, Any], index: int) -> str:
    return _clean(item.get("visual_author_insight_id") or item.get("finding_id") or f"insight-{index + 1}")


def _required_list(value: Any, field: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    return value


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int, field: str) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer") from exc
    if not minimum <= parsed <= maximum:
        raise ValueError(f"{field} must be between {minimum} and {maximum}")
    return parsed


def _unique_fact_id(base: str, seen: set[str]) -> str:
    candidate = _clean(base)
    suffix = 2
    while candidate in seen:
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _prompt_text(value: Any, max_chars: int) -> str:
    """Normalize and cap supplied metadata included in the authoring prompt."""
    text = re.sub(r"\s+", " ", _clean(value))
    if len(text) <= max_chars:
        return text
    return text[: max(1, max_chars - 1)].rstrip() + "…"


def _stable_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
