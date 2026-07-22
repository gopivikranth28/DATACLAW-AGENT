"""Evidence-bound creative visual author for storyboard-backed reports.

The evidence ledger is the durable contract. An LLM authors the complete
report-specific document — structure, inline CSS, and bespoke visuals — while
every claim, value, caption, and evidence reference still resolves to the
validated storyboard. Authoring is fail-closed: generation, validation, or the
independent evidence review failing raises rather than degrading to a
non-authored report.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import re
from html.parser import HTMLParser
from typing import Any

from dataclaw_artifacts.validator import (
    AUTHORED_EXTRA_FORBIDDEN_JS,
    ArtifactValidationError,
    validate_and_prepare_html,
)
from dataclaw.providers.llm.provider import LLMProvider, TextDeltaEvent
from dataclaw.schema import Message


VISUAL_AUTHOR_SCHEMA = 1

# Creative authoring bounds. The model writes a report-specific visual system in
# validated inline CSS; these caps keep the dossier and its embedded aggregates
# self-contained and free of raw-data dumps, while staying generous enough that a
# detailed report can present every finding at full length rather than summarize.
_CREATIVE_MAX_OUTPUT_CHARS = 600_000
_CREATIVE_MAX_DOSSIER_CHARS = 300_000
_CREATIVE_MAX_ROWS_PER_ASSET = 200
_CREATIVE_MAX_COLUMNS_PER_ASSET = 24
_CREATIVE_MAX_INLINE_JS_CHARS = 60_000
_CREATIVE_MAX_INLINE_SCRIPTS = 8
_CREATIVE_REVIEW_MAX_OUTPUT_CHARS = 20_000


class VisualAuthorRequiredError(ValueError):
    """A required visual-author run failed after producing an audit record."""

    def __init__(self, reason: str, *, storyboard: dict[str, Any], record: dict[str, Any]) -> None:
        super().__init__(f"Creative report authoring failed: {reason}")
        self.reason = reason
        self.storyboard = storyboard
        self.record = record


def visual_author_config(requirements: dict[str, Any] | None, override: dict[str, Any] | None = None) -> dict[str, Any]:
    """Resolve the creative visual-author configuration.

    Every report is authored by the ledger-backed creative author. There is no
    deterministic, bounded, or provided-spec mode. Callers may still tune the
    timeout, output budget, and single repair pass.
    """
    supplied = override if isinstance(override, dict) else (requirements or {}).get("visual_author")
    if supplied is not None and not isinstance(supplied, dict):
        raise ValueError("visual_author must be a dictionary when supplied")
    config = copy.deepcopy(supplied) if isinstance(supplied, dict) else {}
    mode = _clean(config.get("mode") or "creative").lower().replace("-", "_")
    if mode != "creative":
        raise ValueError(
            "visual_author.mode must be 'creative'; deterministic and bounded modes were removed"
        )
    config["mode"] = "creative"
    config["timeout_seconds"] = _bounded_int(
        config.get("timeout_seconds"),
        default=240,
        minimum=1,
        maximum=900,
        field="visual_author.timeout_seconds",
    )
    config["max_output_chars"] = _bounded_int(
        config.get("max_output_chars"),
        default=_CREATIVE_MAX_OUTPUT_CHARS,
        minimum=512,
        maximum=_CREATIVE_MAX_OUTPUT_CHARS,
        field="visual_author.max_output_chars",
    )
    config["max_repair_passes"] = _bounded_int(
        config.get("max_repair_passes"),
        default=1,
        minimum=0,
        maximum=1,
        field="visual_author.max_repair_passes",
    )
    # Input bound for the one repair pass, which restates the dossier plus the
    # full authored HTML. Default fits a large-context provider; lower it to match
    # a smaller context window. The dossier is trimmed to fit; if the HTML and
    # findings alone exceed it, the repair is skipped and the unresolved evidence
    # review fails the quality gate closed.
    config["max_repair_prompt_chars"] = _bounded_int(
        config.get("max_repair_prompt_chars"),
        default=700_000,
        minimum=50_000,
        maximum=3_000_000,
        field="visual_author.max_repair_prompt_chars",
    )
    return config


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


def _bounded_aggregate_rows(value: Any, fields: Any = None) -> dict[str, Any]:
    """Project bounded aggregate rows for the dossier.

    When ``fields`` is supplied it is an allowlist: only those columns are
    copied, so unmapped (possibly sensitive) columns are never exposed. This is
    the data-minimization contract for bespoke visuals, matching what governed
    advanced visuals already do by projecting only their mapped fields.
    """
    rows = value if isinstance(value, list) else []
    allow = [_clean(field) for field in fields if _clean(field)] if isinstance(fields, list) else []
    projected: list[dict[str, Any]] = []
    columns: list[str] = []
    for row in rows[:_CREATIVE_MAX_ROWS_PER_ASSET]:
        if not isinstance(row, dict):
            continue
        if not columns:
            if allow:
                columns = [key for key in allow if key in row][:_CREATIVE_MAX_COLUMNS_PER_ASSET]
            else:
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
            "confidence": _prompt_text(insight.get("confidence") or insight.get("confidence_level"), 200),
            "importance": _prompt_value(
                insight.get("importance") or insight.get("priority") or insight.get("story_priority") or ""
            ),
            "claim_scope": claim_scope,
            "causal_language_allowed": claim_scope in {"causal", "experimental_causal", "validated_causal"},
            "metrics": _prompt_value(insight.get("metrics") or []),
            "comparison": _prompt_value(
                insight.get("comparison") or insight.get("baseline") or insight.get("delta") or ""
            ),
            "supporting_points": _prompt_value(
                insight.get("bullets") or insight.get("scan_points") or insight.get("supporting_points") or []
            ),
            "representative_examples": _prompt_value(
                insight.get("representative_examples") or insight.get("examples") or []
            ),
            "hypothesis": _prompt_value(
                insight.get("hypothesis")
                or insight.get("hypothesis_statement")
                or insight.get("hypothesis_id")
                or ""
            ),
            "recommendation": _prompt_value(
                insight.get("recommendation")
                or insight.get("next_action")
                or insight.get("action")
                or insight.get("implication")
                or ""
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
            material.get("report_asset_source_id")
            or material.get("visual_author_section_id")
            or material.get("section_id")
            or material.get("slug")
            or material.get("id")
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
            "baseline": _prompt_value(
                material.get("baseline") or material.get("comparison_baseline") or material.get("reference") or ""
            ),
            "time_window": _prompt_value(
                material.get("time_window") or material.get("period") or material.get("timeframe") or ""
            ),
            "aggregation": _prompt_value(
                material.get("aggregation") or material.get("aggregation_method") or material.get("agg") or ""
            ),
            "comparison_group": _prompt_value(material.get("comparison_group") or ""),
            "diagnostic_group": _prompt_value(material.get("diagnostic_group") or ""),
            "importance": _prompt_value(
                material.get("importance") or material.get("story_priority") or material.get("priority") or ""
            ),
            "field_definitions": _prompt_value(
                material.get("field_definitions") or material.get("definitions") or material.get("columns") or []
            ),
            "filters": _prompt_value(material.get("filters") or []),
            "annotations": _prompt_value(material.get("annotations") or material.get("display_facts") or []),
            "visual_direction": _prompt_text(
                material.get("visual_direction")
                or material.get("visual_intent")
                or material.get("design_note"),
                1_500,
            ),
            "visual_medium": _clean(material.get("medium") or material.get("visual_medium")).lower(),
            "visual_mapping": _prompt_value(visual),
            "aggregate_data": _bounded_aggregate_rows(
                rows_value,
                material.get("fields") or material.get("field_bindings"),
            ) if rows_value else {},
            "plotly_summary": _plotly_payload(material.get("figure_json") or material.get("figure")),
            "required_visual": bool(material.get("required_visual", False)),
            "evidence_aliases": evidence_aliases,
        }
        sources.append({
            "alias": alias,
            "source_id": source_id,
            "kind": "asset",
            "required_visual": bool(material.get("required_visual", False)),
        })
        dossier_blocks.append((f"Aggregate or analytical asset {alias}", payload))

    # Surface which trust disclosures the rigor contract requires, so the author
    # writes them into the document (there is no deterministic disclosure section
    # anymore — the report is authored end to end).
    rigor_req = requirements.get("rigor") if isinstance(requirements.get("rigor"), dict) else {}
    analysis_review = requirements.get("analysis_review") if isinstance(requirements.get("analysis_review"), dict) else {}
    predictive = _clean(analysis_review.get("mode")).lower() in {"predictive", "forecast"}
    required_disclosures: list[str] = []
    if rigor_req.get("require_methodology"):
        required_disclosures.append("methodology: grain, denominator, and validation")
    if rigor_req.get("require_data_quality"):
        required_disclosures.append("data-quality and coverage limitations")
    if rigor_req.get("require_uncertainty") or predictive:
        required_disclosures.append("uncertainty: intervals, confidence, or sample size")

    brief = {
        "title": _prompt_text(storyboard.get("title"), 500),
        "goal": _prompt_text(storyboard.get("report_goal"), 1_500),
        "decision": _prompt_text(
            requirements.get("decision")
            or requirements.get("decision_question")
            or requirements.get("question")
            or storyboard.get("report_goal"),
            1_500,
        ),
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
        "required_disclosures": required_disclosures,
        "coverage_instruction": (
            "Present every finding and analytical asset below in full detail with its own "
            "interpretation; do not drop findings for brevity. Place each chart or visual's "
            "interpretation directly beside or below it, never in a separate section."
        ),
    }
    trust_material = {
        key: _prompt_value(requirements.get(key))
        for key in (
            "kicker", "subtitle", "metrics", "filters", "definitions", "glossary", "brand",
            "methodology", "methods", "checks", "validation", "data_quality", "coverage_risks",
            "uncertainty", "uncertainty_notes", "analysis_review", "assumptions", "limitations",
            "hypotheses", "sample", "sample_size", "data_sources", "time_period",
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
        "Mark used source aliases with data-source and supporting evidence aliases with data-evidence. Explicitly record intentionally omitted sources in the coverage script. "
        "A source marked required_visual may not be omitted and its data-source alias must be attached directly to a figure, SVG, or canvas. "
        "When an asset supplies visual_direction, treat it as the intended bespoke visual for that asset and realize it faithfully from the bounded data, honoring visual_medium (svg, canvas, or html) when given. There is no fixed catalog of visual forms — build whatever custom geometry the direction and evidence support.",
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
        maximum=600_000,
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

Write a thorough, detailed report. Present every supplied finding and every analytical asset you do not deliberately omit; do not compress the analysis into a short summary or drop findings for brevity. Length should follow the evidence.

Every chart, figure, or bespoke visual must be accompanied by interpretation prose that states what it shows and why it matters, placed immediately beside or directly below the visual it explains — never collected in a separate section away from the visual. The reader should see the chart and its meaning together.

You own the story architecture. Merge, split, reorder, or omit source blocks when that improves the report. Do not reproduce a generic component-library dashboard. Create report-specific HTML, original CSS, and bespoke SVG or Canvas visuals from the supplied bounded aggregate values. Familiar chart forms (bar, line, scatter, and similar) are allowed and often best; use them freely. Charts do not need to be interactive — a clear static chart with strong interpretation is preferred, and interactivity is added only where it genuinely helps the reader explore, never as a requirement. Use actual supplied values, units, labels, and denominators; never invent geometry or data.

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
        self.visual_source_aliases: set[str] = set()
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
        if tag in self._VISUAL_TAGS:
            # Required analytical visuals need an explicit binding on the
            # figure/SVG/canvas itself. Otherwise a broad source marker on the
            # page shell could falsely make every visual cover every asset.
            self.visual_source_aliases.update(self._aliases(attr.get("data-source", "")))
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
                for pattern, name in AUTHORED_EXTRA_FORBIDDEN_JS:
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
    if parser.script_count > _CREATIVE_MAX_INLINE_SCRIPTS or parser.script_chars > _CREATIVE_MAX_INLINE_JS_CHARS:
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
    required_visual_sources = {
        _clean(item.get("alias")) for item in contract.get("sources", [])
        if isinstance(item, dict) and item.get("required_visual") and _clean(item.get("alias"))
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
    omitted_required_visuals = sorted(required_visual_sources & set(omitted))
    if omitted_required_visuals:
        raise ValueError(f"required visual sources cannot be omitted: {omitted_required_visuals}")
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
    missing_required_visuals = sorted(required_visual_sources - parser.visual_source_aliases)
    if missing_required_visuals:
        raise ValueError(
            "authored HTML did not render required visual sources as figure/SVG/canvas: "
            f"{missing_required_visuals}"
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
        "coverage": {
            "used": sorted(parser.source_aliases),
            "omitted": omitted,
            "visual_sources": sorted(parser.visual_source_aliases),
        },
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


def _bounded_repair_prompt(
    dossier: str,
    findings: list[dict[str, Any]],
    html: str,
    *,
    max_chars: int,
) -> str | None:
    """Build the repair prompt within a bounded input budget.

    The findings and the full authored HTML must be present (the model returns a
    corrected complete document), so the dossier is what gets trimmed to fit. If
    the HTML and findings alone exceed the budget, return None: the report is too
    large to repair on this provider, the caller skips the pass, and the still
    unresolved evidence review fails the quality gate closed.
    """
    findings_block = "\n\n# Required evidence repairs\n\n" + json.dumps(findings, ensure_ascii=False, indent=2)
    instruction = "\n\nRevise the complete document below. Return the complete corrected HTML only.\n\n"
    required = findings_block + instruction + html
    dossier_budget = max_chars - len(required)
    if dossier_budget <= 0:
        return None
    if len(dossier) <= dossier_budget:
        return dossier + required
    trimmed = dossier[:dossier_budget].rstrip() + "\n\n[dossier trimmed to fit the repair context]"
    return trimmed + required


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
        raise VisualAuthorRequiredError(
            f"{type(exc).__name__}: {exc}", storyboard=original, record=record
        ) from exc
    record: dict[str, Any] = {
        "schema": VISUAL_AUTHOR_SCHEMA,
        "mode": "creative",
        "dossier_sha256": contract["dossier_sha256"],
        "source_count": len(contract["sources"]),
        "evidence_target_count": len(contract["evidence"]),
    }
    if llm is None:
        raise VisualAuthorRequiredError(
            "No LLM provider is available for the creative report author.",
            storyboard=original,
            record=record,
        )
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
            repair_prompt = _bounded_repair_prompt(
                dossier,
                evidence_review["findings"],
                html,
                max_chars=cfg["max_repair_prompt_chars"],
            )
            if repair_prompt is not None:
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
        raise VisualAuthorRequiredError(
            f"{type(exc).__name__}: {exc}", storyboard=original, record=record
        ) from exc

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
    """Author the report as a complete creative single-file document.

    Creative authoring is the only mode. Generation, evidence review, or
    validation failure raises ``VisualAuthorRequiredError`` — there is no
    deterministic or bounded fallback, so a report is always an
    evidence-bound, LLM-authored visual document or it is not produced.
    """
    cfg = visual_author_config({}, config)
    original = copy.deepcopy(storyboard)
    return await _author_creative_document(original, cfg=cfg, llm=llm)


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


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _prompt_text(value: Any, max_chars: int) -> str:
    """Normalize and cap supplied metadata included in the authoring prompt."""
    text = re.sub(r"\s+", " ", _clean(value))
    if len(text) <= max_chars:
        return text
    return text[: max(1, max_chars - 1)].rstrip() + "…"
