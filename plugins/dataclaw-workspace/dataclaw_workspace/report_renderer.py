"""Report renderer for DataClaw workspace reports."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any

from dataclaw_artifacts.sections import (
    ADVANCED_VISUAL_FIELDS,
    clean_text,
    prepare_advanced_visual_data,
)
from dataclaw_artifacts.wrapper import STORED_ARTIFACT_CSP

from dataclaw_workspace.report_rubric import (
    live_criterion_ids,
    rubric_criteria,
    rubric_thresholds,
    rubric_version,
)
from dataclaw_workspace.visual_author import validate_authored_document

REPORT_SHELL_SCRIPT_ATTR = 'data-dc-report-shell-script'
REPORT_CONTRACT_ATTR = "data-dc-report-contract"
REGENERATION_RECIPE_ATTR = "data-dc-regeneration-recipe"
PLOTLY_RUNTIME_RE = re.compile(
    r"<script\b(?=[^>]*\bdata-dc-runtime=(['\"])plotly\1)[^>]*>.*?</script>",
    re.IGNORECASE | re.DOTALL,
)


__all__ = [
    "CHART_SECTION_KINDS",
    "VISUAL_SECTION_KINDS",
    "analyze_report_quality",
    "build_evidence_registry",
    "critique_report_storyboard",
    "design_report_storyboard",
    "render_report_from_storyboard",
    "ensure_regeneration_recipe",
    "review_storyboard_design",
    "review_storyboard_authoring",
    "review_storyboard_analysis",
]

CHART_SECTION_KINDS = {"chart", "chart_interpretation", "filterable_chart", "chart_table_explorer"}
ADVANCED_VISUAL_SECTION_KINDS = {"advanced_visual"}
VISUAL_SECTION_KINDS = CHART_SECTION_KINDS | ADVANCED_VISUAL_SECTION_KINDS
STANDARD_CHART_TYPE_ALIASES = {
    "bar": "bar",
    "column": "bar",
    "hbar": "hbar",
    "horizontal_bar": "hbar",
    "line": "line",
    "scatter": "scatter",
    "heatmap": "heatmap",
}
INTERACTIVE_SECTION_KINDS = {"filterable_chart", "interactive_table", "selector_panel", "chart_table_explorer"}
DESKTOP_COMPOSITIONS = {
    "opening",
    "headline_metrics",
    "reader_readout",
    "editorial_findings",
    "guided_visual",
    "interactive_explorer",
    "comparison",
    "trust_close",
    "story_arc",
    "supporting",
}
STORY_SECTION_KINDS = {
    "findings",
    "insight_grid",
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
# The rubric is the single source of truth for gate thresholds; this constant is
# kept as the public name for the payload cap (docs reference it by name).
REPORT_QUALITY_MAX_BYTES = rubric_thresholds()["max_payload_bytes"]


def analyze_report_quality(
    doc: str,
    *,
    stale_skills: list[dict[str, Any]] | None = None,
    max_bytes: int = REPORT_QUALITY_MAX_BYTES,
    runtime_smoke: dict[str, Any] | None = None,
    visual_author: dict[str, Any] | None = None,
    authoring_review: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Inspect the typed section metadata embedded in a workspace report.

    Criteria severities, gate thresholds, and live/deferred status come from the
    report rubric (report_rubric.yaml); every result cites the rubric version it
    was judged by. Only ``status: live`` criteria are evaluated — the signal
    checks themselves live here, keyed by criterion id.
    """
    sections = _extract_section_meta(doc)
    warnings: list[dict[str, Any]] = []
    criteria = rubric_criteria()
    thresholds = rubric_thresholds()

    def warn(code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        criterion = criteria.get(code)
        if criterion is None:
            raise KeyError(f"gate check {code!r} has no criterion in the report rubric")
        if criterion["status"] != "live":
            return
        entry: dict[str, Any] = {
            "code": code,
            "severity": criterion["severity"],
            "message": message,
            "details": details or {},
        }
        if criterion.get("replaces"):
            entry["replaces"] = criterion["replaces"]
        warnings.append(entry)

    if not sections:
        warn(
            "unstructured_report",
            "Report contains no typed section metadata; publish structured storyboard output or migrate the report before publishing.",
            details={"required_marker": "data-dc-section-meta"},
        )

    total_size = len(doc.encode("utf-8"))
    payload_size = len(PLOTLY_RUNTIME_RE.sub("", doc).encode("utf-8"))
    if payload_size > max_bytes:
        warn(
            "oversized_report",
            f"Report payload HTML is {payload_size} bytes; reduce embedded raw HTML/data before publishing.",
            details={"bytes": payload_size, "total_bytes": total_size, "max_bytes": max_bytes},
        )

    if stale_skills:
        warn(
            "stale_installed_skills",
            "Installed library skills are stale versus bundled skill-library instructions.",
            details={"skills": stale_skills},
        )

    if isinstance(authoring_review, dict) and authoring_review.get("findings"):
        warn(
            "display_fact_coverage",
            "The report's visual display semantics are missing typed, source-owned facts or still rely on legacy decorative fields.",
            details={
                "requested": bool(authoring_review.get("requested")),
                "target_count": int(authoring_review.get("target_count") or 0),
                "covered_target_count": int(authoring_review.get("covered_target_count") or 0),
                "findings": authoring_review.get("findings"),
            },
        )

    report_contract = _extract_report_contract(doc)
    rigor = report_contract.get("rigor") if isinstance(report_contract.get("rigor"), dict) else {}
    recipe = _extract_regeneration_recipe(doc)
    if bool(rigor.get("recipe_required", False)) and not _valid_regeneration_recipe(recipe):
        warn(
            "missing_recipe",
            "Report has no valid embedded regeneration recipe bound to its source context and section plan.",
            details={"required_script": REGENERATION_RECIPE_ATTR},
        )
    if bool(rigor.get("methodology_required", False)):
        methodology = _methodology_completeness(sections)
        if methodology["missing"]:
            warn(
                "missing_methodology",
                "The declared rigor contract requires methodology for grain, denominator, and validation, but the rendered report does not show all three.",
                details=methodology,
            )
    if bool(rigor.get("data_quality_required", False)) and not _has_semantic_role(sections, {"data_quality", "coverage"}):
        warn(
            "missing_data_quality",
            "The declared rigor contract requires a visible data-quality or coverage disclosure.",
            details={"accepted_roles": ["data_quality", "coverage"]},
        )
    if bool(rigor.get("uncertainty_required", False)) and not _has_semantic_role(sections, {"uncertainty", "interval", "confidence"}):
        warn(
            "missing_uncertainty",
            "The declared or predictive rigor contract requires visible uncertainty information in the rendered report.",
            details={"accepted_roles": ["uncertainty", "interval", "confidence"]},
        )
    if bool(rigor.get("component_semantics_required", False)):
        component_failures = _component_semantic_failures(sections)
        if component_failures:
            warn(
                "plaintext_where_component_warranted",
                "A declared semantic role is rendered with a component that does not preserve that role for scanning or verification.",
                details={"sections": component_failures},
            )

    kinds = [clean_text(section.get("kind") or "") for section in sections]
    story_count = sum(1 for kind in kinds if kind in STORY_SECTION_KINDS and kind != "chart")
    primary_insight_count = 0
    for section in sections:
        kind = clean_text(section.get("kind") or "")
        payload = section.get("payload") if isinstance(section.get("payload"), dict) else {}
        if kind in {"findings", "insight_grid"} and isinstance(payload.get("items"), list) and payload.get("items"):
            primary_insight_count += 1
        elif kind == "advanced_visual" and payload.get("has_interpretation") and isinstance(payload.get("claim_source"), dict):
            primary_insight_count += 1

    # The report should present every finding with an interpretation; it is not
    # penalized for how many charts it uses, for plain charts, or for a lack of
    # interactivity. Only a report with no story/insight layer at all is flagged.
    if len(kinds) >= thresholds["insight_required_min_sections"] and story_count == 0:
        warn(
            "missing_insight_sections",
            "Report has multiple sections but no findings, insight grid, narrative band, methodology, evidence, or explorer layer.",
            details={"section_count": len(kinds)},
        )
    if len(kinds) >= thresholds["insight_required_min_sections"] and primary_insight_count == 0:
        warn(
            "missing_primary_insights",
            "Report has multiple sections but no completed finding, insight grid, or source-bound advanced interpretation.",
            details={"section_count": len(kinds)},
        )

    for section in sections:
        kind = clean_text(section.get("kind") or "")
        payload = section.get("payload") if isinstance(section.get("payload"), dict) else {}
        if kind in {"table", "interactive_table"} and not clean_text(section.get("caption") or payload.get("caption") or ""):
            warn(
                "missing_table_caption",
                "Table section is missing a caption that explains grain, filters, or interpretation.",
                details={"section_id": section.get("section_id"), "kind": kind},
            )
        if kind in {"findings", "insight_grid", "hypothesis_ledger", "evidence_trace", "evidence_rail"}:
            items = payload.get("items", [])
            if isinstance(items, list) and items and not any(_item_has_evidence_id(item) for item in items if isinstance(item, dict)):
                warn(
                    "unsourced_claim",
                    "Insight/evidence section has items but no finding_id, hypothesis_id, or evidence reference in metadata.",
                    details={"section_id": section.get("section_id"), "kind": kind},
                )
        if kind in {"chart_interpretation", "advanced_visual"} and payload.get("has_interpretation") and not payload.get("evidence_count"):
            warn(
                "chart_interpretation_missing_evidence",
                "Chart interpretation has a narrative conclusion but no evidence refs.",
                details={"section_id": section.get("section_id")},
            )

        has_chart_conclusion = bool(clean_text(
            payload.get("conclusion") or payload.get("interpretation") or payload.get("insight") or payload.get("summary") or ""
        )) or bool(payload.get("has_interpretation"))
        if kind in {"chart", "chart_interpretation", "filterable_chart", "advanced_visual"} and not has_chart_conclusion:
            warn(
                "chart_missing_conclusion",
                "Chart section has no stated interpretation or conclusion.",
                details={"section_id": section.get("section_id"), "kind": kind},
            )
        # A titled narrative or callout already establishes why it appears in
        # the story. Requiring a generated dek there produces filler such as
        # "Context and evidence for …" rather than useful reader guidance.
        if kind not in {"header", "metric_row", "narrative_band", "callout", "text", "explanation"} and not clean_text(section.get("caption") or payload.get("caption") or payload.get("dek") or ""):
            warn(
                "missing_section_dek",
                "Section is missing a short dek/caption that explains why it is in the story.",
                details={"section_id": section.get("section_id"), "kind": kind},
            )
        if kind in {"findings", "insight_grid"}:
            items = payload.get("items", payload.get("findings", []))
            if isinstance(items, list) and any(not isinstance(item, dict) for item in items):
                warn(
                    "bare_bullet_findings",
                    "Findings should use typed insight-card items, not bare bullet strings.",
                    details={"section_id": section.get("section_id"), "kind": kind},
                )
            if isinstance(items, list) and any(
                isinstance(item, dict)
                and _evidence_refs_from_value(item.get("evidence") or item.get("evidence_refs"))
                and not clean_text(item.get("evidence_anchor") or "")
                for item in items
            ):
                warn(
                    "unpaired_insights",
                    "Insight carries evidence refs but is not paired to an evidence section anchor.",
                    details={"section_id": section.get("section_id"), "kind": kind},
                )

    registry_document = _extract_evidence_registry_document(doc)
    registry = _extract_evidence_registry(doc)
    if (
        isinstance(visual_author, dict)
        and clean_text(visual_author.get("mode") or "") == "creative"
        and clean_text(visual_author.get("status") or "") == "applied"
        and not [item for item in registry_document.get("targets", []) if isinstance(item, dict)]
    ):
        warn(
            "creative_evidence_ledger_missing",
            "Creatively authored report HTML has no embedded evidence-ledger targets.",
            details={"visual_author_mode": "creative"},
        )
    if (
        isinstance(visual_author, dict)
        and clean_text(visual_author.get("mode") or "") == "creative"
        and clean_text(visual_author.get("status") or "") == "applied"
    ):
        coverage = _extract_report_metadata(doc, "data-dc-author-coverage")
        if (
            coverage.get("coverage_schema") != 1
            or not isinstance(coverage.get("used"), list)
            or not isinstance(coverage.get("omitted"), list)
        ):
            warn(
                "authored_evidence_coverage_missing",
                "The authored report has no valid host-attached source coverage manifest.",
                details={"visual_author_mode": "creative"},
            )
        evidence_review = visual_author.get("evidence_review") if isinstance(visual_author.get("evidence_review"), dict) else {}
        if clean_text(evidence_review.get("status") or "") != "pass":
            warn(
                "authored_evidence_review_failed",
                "The independent evidence review did not pass the authored prose and visuals.",
                details={"evidence_review": evidence_review},
            )
    registry_references = registry_document.get("references", []) if isinstance(registry_document.get("references", []), list) else []
    unresolved_refs = _unresolved_evidence_refs(sections, registry, registry_references)
    if unresolved_refs:
        warn(
            "evidence_unresolved",
            "One or more evidence references do not resolve to a registered target present in the report bundle.",
            details={"references": unresolved_refs[:20], "count": len(unresolved_refs)},
        )

    if len(sections) >= 2 and "narrative_band" not in kinds:
        warn(
            "missing_narrative_answer",
            "Report has multiple sections but no narrative band answering the primary question up front.",
            details={"section_count": len(sections)},
        )

    theme_failures = _chart_theme_failures(sections)
    if theme_failures:
        warn(
            "chart_theme_defeated",
            "Stored chart styling can defeat the report's token-driven theme and dark-mode re-render.",
            details={"sections": theme_failures},
        )

    # External/remote-asset detection is owned by the artifact validator
    # (dataclaw_artifacts.validate_and_prepare_html), which runs fail-closed
    # before this gate in the design and publish paths. The gate no longer
    # re-checks it with a weaker regex.

    static_smoke_failures = _runtime_smoke_failures(doc, sections)
    smoke_result = runtime_smoke or {
        "status": "static",
        "checks": static_smoke_failures,
    }
    smoke_failures = static_smoke_failures
    if runtime_smoke and runtime_smoke.get("status") == "failed":
        smoke_failures = [
            *static_smoke_failures,
            *[entry for entry in runtime_smoke.get("checks", []) if isinstance(entry, dict)],
        ]
    if runtime_smoke and runtime_smoke.get("status") == "skipped":
        smoke_failures = [
            *static_smoke_failures,
            {"check": "browser_smoke", "detail": clean_text(runtime_smoke.get("reason") or "browser smoke was skipped")},
        ]
    if smoke_failures:
        warn(
            "runtime_smoke_failed",
            "Structural runtime smoke checks found report wiring that cannot initialize correctly.",
            details={"checks": smoke_failures},
        )

    semantic_visual = runtime_smoke.get("semantic_visual") if isinstance(runtime_smoke, dict) and isinstance(runtime_smoke.get("semantic_visual"), dict) else {}
    if semantic_visual.get("status") == "attention_required":
        warn(
            "visual_semantic_review",
            "The automated rendered-page semantic review found hierarchy, framing, or evidence-context issues.",
            details={"findings": semantic_visual.get("findings", [])},
        )

    contrast_failures = _contrast_failures(doc)
    if contrast_failures:
        warn(
            "contrast_below_aa",
            "Report color tokens do not meet the configured WCAG-AA text contrast checks.",
            details={"pairs": contrast_failures},
        )

    status = "pass"
    if any(w["severity"] == "fail" for w in warnings):
        status = "fail"
    elif warnings:
        status = "warn"

    return {
        "status": status,
        "rubric_version": rubric_version(),
        "section_count": len(sections),
        "story_count": story_count,
        "runtime_smoke": smoke_result,
        "visual_semantic_review": semantic_visual,
        "warnings": warnings,
    }


def _extract_section_meta(doc: str) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    for match in re.finditer(r"<script[^>]*data-dc-section-meta[^>]*>(.*?)</script>", doc, re.IGNORECASE | re.DOTALL):
        try:
            parsed = json.loads(match.group(1))
        except Exception:
            continue
        if isinstance(parsed, dict):
            sections.append(parsed)
    return sections


def _evidence_registry_script(registry: dict[str, Any] | None) -> str:
    if not registry:
        return ""
    payload = _json_for_script(registry)
    return f'<script type="application/json" data-dc-evidence-registry>{payload}</script>'


def _report_contract_script(contract: dict[str, Any] | None) -> str:
    if not contract:
        return ""
    return f'<script type="application/json" {REPORT_CONTRACT_ATTR}>{_json_for_script(contract)}</script>'


def _regeneration_recipe_script(recipe: dict[str, Any] | None) -> str:
    if not recipe:
        return ""
    return f'<script type="application/json" {REGENERATION_RECIPE_ATTR}>{_json_for_script(recipe)}</script>'


def _extract_report_metadata(doc: str, attribute: str) -> dict[str, Any]:
    match = re.search(
        rf"<script[^>]*{re.escape(attribute)}[^>]*>(.*?)</script>",
        doc,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return {}
    try:
        value = json.loads(match.group(1))
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _extract_report_contract(doc: str) -> dict[str, Any]:
    return _extract_report_metadata(doc, REPORT_CONTRACT_ATTR)


def _extract_regeneration_recipe(doc: str) -> dict[str, Any]:
    return _extract_report_metadata(doc, REGENERATION_RECIPE_ATTR)


def _valid_regeneration_recipe(recipe: dict[str, Any]) -> bool:
    return (
        recipe.get("recipe_schema") == 1
        and bool(clean_text(recipe.get("renderer") or ""))
        and bool(clean_text(recipe.get("source_context_sha256") or ""))
        and bool(clean_text(recipe.get("section_plan_sha256") or ""))
    )


def _has_semantic_role(sections: list[dict[str, Any]], roles: set[str]) -> bool:
    for section in sections:
        payload = section.get("payload") if isinstance(section.get("payload"), dict) else {}
        role = clean_text(payload.get("semantic_role") or "").lower().replace("-", "_")
        if role in roles:
            return True
    return False


def _methodology_completeness(sections: list[dict[str, Any]]) -> dict[str, Any]:
    labels: list[str] = []
    for section in sections:
        if clean_text(section.get("kind") or "") != "methodology_block":
            continue
        payload = section.get("payload") if isinstance(section.get("payload"), dict) else {}
        labels.extend(clean_text(value).lower() for value in payload.get("method_titles", []) if clean_text(value))
        labels.extend(clean_text(value).lower() for value in payload.get("check_titles", []) if clean_text(value))
    required_terms = {
        "grain": ("grain", "unit", "level"),
        "denominator": ("denominator", "population", "universe", "base", "cohort"),
        "validation": ("validation", "validate", "check", "test", "verification"),
    }
    missing = [
        name for name, terms in required_terms.items()
        if not any(any(term in label for term in terms) for label in labels)
    ]
    return {"method_titles": labels, "missing": missing}


def _component_semantic_failures(sections: list[dict[str, Any]]) -> list[dict[str, str]]:
    expected = {
        "methodology": {"methodology_block"},
        "data_quality": {"callout", "methodology_block"},
        "coverage": {"callout", "methodology_block"},
        "uncertainty": {"callout", "methodology_block", "narrative_band"},
        "provenance": {"evidence_trace", "evidence_rail"},
        "timeline": {"ledger_timeline"},
        "status": {"checklist"},
        "taxonomy": {"entity_card_grid", "selector_panel"},
        "entities": {"entity_card_grid", "selector_panel"},
    }
    failures: list[dict[str, str]] = []
    for section in sections:
        payload = section.get("payload") if isinstance(section.get("payload"), dict) else {}
        role = clean_text(payload.get("semantic_role") or "").lower().replace("-", "_")
        kind = clean_text(section.get("kind") or "")
        if role and role in expected and kind not in expected[role]:
            failures.append({
                "section_id": clean_text(section.get("section_id") or ""),
                "semantic_role": role,
                "kind": kind,
                "expected": ", ".join(sorted(expected[role])),
            })
    return failures


def _stable_json_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _rigor_contract(requirements: dict[str, Any], analysis_contract: dict[str, Any]) -> dict[str, bool]:
    """Normalize only source-declared rigor requirements.

    Final reports vary from a short operational readout to a predictive model.
    The renderer therefore never guesses that an arbitrary report needs a
    denominator or interval. Callers declare those expectations in
    ``requirements.rigor``; predictive contracts opt into uncertainty by
    default because they already represent a quantitative inference claim.
    """
    raw = requirements.get("rigor") if isinstance(requirements.get("rigor"), dict) else {}
    mode = clean_text(analysis_contract.get("mode") or "").lower().replace("-", "_")
    predictive = mode in {"predictive", "forecast", "simulation", "model"}
    return {
        "methodology_required": bool(raw.get("require_methodology", False)),
        "data_quality_required": bool(raw.get("require_data_quality", False)),
        "uncertainty_required": bool(raw.get("require_uncertainty", False)) or predictive,
        "recipe_required": bool(raw.get("require_recipe", True)),
        "component_semantics_required": bool(raw.get("require_component_semantics", False)),
    }


def _report_contract_for_storyboard(storyboard: dict[str, Any]) -> dict[str, Any]:
    source_context = storyboard.get("source_context") if isinstance(storyboard.get("source_context"), dict) else {}
    requirements = source_context.get("requirements") if isinstance(source_context.get("requirements"), dict) else {}
    analysis_contract = storyboard.get("analysis_contract") if isinstance(storyboard.get("analysis_contract"), dict) else {}
    return {
        "report_contract_schema": 1,
        "rigor": _rigor_contract(requirements, analysis_contract),
        "source_context_sha256": _stable_json_sha256({
            "insights": source_context.get("insights", []),
            "analyses": source_context.get("analyses", []),
            "requirements": requirements,
        }),
    }


def ensure_regeneration_recipe(storyboard: dict[str, Any]) -> dict[str, Any]:
    """Attach a source-bound recipe; authored HTML need not be deterministic."""
    source_context = storyboard.get("source_context") if isinstance(storyboard.get("source_context"), dict) else {}
    source_inputs = {
        "insights": source_context.get("insights", []),
        "analyses": source_context.get("analyses", []),
        "requirements": source_context.get("requirements", {}),
        "analysis_contract": storyboard.get("analysis_contract", {}),
    }
    recipe = {
        "recipe_schema": 1,
        "renderer": "dataclaw_workspace.report_renderer.render_report_from_storyboard",
        "source_context_sha256": _stable_json_sha256(source_inputs),
        "section_plan_sha256": _stable_json_sha256(storyboard.get("section_plan", [])),
        "instructions": "Regenerate from this storyboard's source_context and section_plan; do not edit the rendered HTML as the source of truth.",
    }
    authored = storyboard.get("authored_document") if isinstance(storyboard.get("authored_document"), dict) else {}
    if authored:
        recipe.update({
            "authoring_mode": "llm_full_document",
            "dossier_sha256": clean_text(authored.get("dossier_sha256") or ""),
            "authored_document_sha256": hashlib.sha256(
                clean_text(authored.get("html") or "").encode("utf-8")
            ).hexdigest(),
            "instructions": (
                "Re-author from the source_context and persisted author dossier. Exact report HTML is not required "
                "to reproduce; preserve the evidence ledger, source coverage, and reviewed analytical meaning."
            ),
        })
    storyboard["regeneration_recipe"] = recipe
    return recipe


def _extract_evidence_registry(doc: str) -> dict[str, dict[str, Any]]:
    parsed = _extract_evidence_registry_document(doc)
    targets = parsed.get("targets", []) if isinstance(parsed, dict) else []
    if not isinstance(targets, list):
        return {}
    registry: dict[str, dict[str, Any]] = {}
    for target in targets:
        if not isinstance(target, dict):
            continue
        ref = clean_text(target.get("id") or target.get("ref") or "")
        if ref:
            registry[ref] = target
    return registry


def _extract_evidence_registry_document(doc: str) -> dict[str, Any]:
    match = re.search(
        r"<script[^>]*data-dc-evidence-registry[^>]*>(.*?)</script>",
        doc,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return {}
    try:
        parsed = json.loads(match.group(1))
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _evidence_refs_from_value(value: Any) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    for entry in _as_list(value):
        if isinstance(entry, dict):
            kind = clean_text(entry.get("kind") or entry.get("type") or "unknown")
            ref = clean_text(
                entry.get("ref")
                or entry.get("cell_id")
                or entry.get("artifact_id")
                or entry.get("finding_id")
                or entry.get("hypothesis_id")
                or entry.get("path")
                or ""
            )
        else:
            kind = "unknown"
            ref = clean_text(entry)
        if ref:
            refs.append({"kind": kind, "ref": ref})
    return refs


def _source_evidence_refs(source: Any) -> list[dict[str, str]]:
    """Collect ordinary and display-fact provenance from one source object.

    Display facts are reader-facing claims selected by the runtime visual author,
    so their evidence must be checked by the same registry as chart and insight
    evidence. ``visual_facts`` is retained only as a legacy alias.
    """
    if not isinstance(source, dict):
        return []
    references: list[dict[str, str]] = []
    for key in ("evidence", "evidence_refs"):
        references.extend(_evidence_refs_from_value(source.get(key)))
    facts = source.get("display_facts") if source.get("display_facts") is not None else source.get("visual_facts", [])
    for fact in _as_list(facts):
        if not isinstance(fact, dict):
            continue
        evidence = fact.get("evidence", fact.get("evidence_refs", fact.get("source_refs")))
        references.extend(_evidence_refs_from_value(evidence))
    return references


def _unresolved_evidence_refs(
    sections: list[dict[str, Any]],
    registry: dict[str, dict[str, Any]],
    registered_references: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    unresolved: list[dict[str, str]] = []
    references = registered_references or []
    if not references:
        for section in sections:
            payload = section.get("payload") if isinstance(section.get("payload"), dict) else {}
            section_id = clean_text(section.get("section_id") or "")
            sources = [payload, *_as_list(payload.get("items")), *_as_list(payload.get("findings")), *_as_list(payload.get("hypotheses"))]
            for source in sources:
                references.extend({"section_id": section_id, **reference} for reference in _source_evidence_refs(source))
    for reference in references:
        target = registry.get(reference["ref"])
        target_kind = clean_text(target.get("kind") or target.get("type") or "") if target else ""
        is_external = bool(target and clean_text(target.get("external_url") or target.get("url") or ""))
        is_present = bool(target and target.get("present", True))
        kind_matches = not target_kind or target_kind == reference["kind"] or reference["kind"] == "unknown"
        if not target or not is_present or (not is_external and not kind_matches):
            unresolved.append(dict(reference))
    return unresolved


def build_evidence_registry(storyboard: dict[str, Any]) -> dict[str, Any]:
    """Normalize explicit evidence targets and registered in-report finding targets.

    Only supplied targets and identifiers already present in the report are
    registered. The function never invents a provenance id merely to satisfy a
    quality check.
    """
    supplied = storyboard.get("evidence_registry", {})
    raw_targets = supplied.get("targets", []) if isinstance(supplied, dict) else supplied
    targets: dict[str, dict[str, Any]] = {}
    references: list[dict[str, str]] = []
    for raw in _as_list(raw_targets):
        if not isinstance(raw, dict):
            continue
        ref = clean_text(raw.get("id") or raw.get("ref") or "")
        kind = clean_text(raw.get("kind") or raw.get("type") or "")
        if not ref or not kind:
            continue
        target = dict(raw)
        target["id"] = ref
        target["kind"] = kind
        target.setdefault("present", True)
        targets[ref] = target

    section_plan = storyboard.get("section_plan", [])
    if isinstance(section_plan, list):
        for planned in section_plan:
            data = planned.get("data") if isinstance(planned, dict) and isinstance(planned.get("data"), dict) else {}
            section_id = clean_text(data.get("section_id") or planned.get("layout_role") or "")
            for source in [data, *_as_list(data.get("items")), *_as_list(data.get("findings")), *_as_list(data.get("hypotheses"))]:
                references.extend({"section_id": section_id, **reference} for reference in _source_evidence_refs(source))
            item_groups = [data.get("items"), data.get("findings"), data.get("hypotheses")]
            for group in item_groups:
                for item in _as_list(group):
                    if not isinstance(item, dict):
                        continue
                    for key in ("finding_id", "hypothesis_id"):
                        ref = clean_text(item.get(key) or "")
                        if ref and ref not in targets:
                            targets[ref] = {
                                "id": ref,
                                "kind": "finding",
                                "present": True,
                                "source": "report_section",
                            }

    return {
        "evidence_registry_schema": 1,
        "targets": list(targets.values()),
        "references": references,
    }


def critique_report_storyboard(
    storyboard: dict[str, Any],
    *,
    max_passes: int = 5,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Apply bounded, non-fabricating improvements and review a storyboard.

    The repair pass may safely add presentational context, but it must never
    manufacture analytical evidence.  The review record is deliberately
    separate: it makes missing validation, uncertainty, sensitivity, and
    decision-path work visible to the caller as durable findings instead of
    silently leaving those gaps for a later chat turn to rediscover.
    """
    working = copy.deepcopy(storyboard)
    section_plan = working.get("section_plan")
    if not isinstance(section_plan, list):
        raise ValueError("storyboard requires a section_plan for critique")

    applied: list[dict[str, Any]] = []
    passes = 0
    converged = False
    for pass_number in range(1, max(1, max_passes) + 1):
        changed = False
        passes = pass_number
        for index, planned in enumerate(section_plan):
            if not isinstance(planned, dict):
                continue
            section_type = clean_text(planned.get("section_type") or planned.get("kind") or "")
            data = planned.get("data") if isinstance(planned.get("data"), dict) else {}
            if not data:
                continue
            if section_type in {"table", "interactive_table"} and not clean_text(data.get("caption") or ""):
                columns = data.get("columns", [])
                labels = ", ".join(clean_text(column.get("label") or column.get("key") or "") if isinstance(column, dict) else clean_text(column) for column in _as_list(columns)[:4])
                data["caption"] = f"Extracted values by {labels or 'available fields'}; verify grain and filters before interpretation."
                planned["data"] = data
                applied.append({"pass": pass_number, "section": index, "action": "add_table_caption"})
                changed = True
            if section_type in {"findings", "insight_grid"}:
                items = data.get("items", data.get("findings", []))
                if isinstance(items, list):
                    for item in items:
                        if isinstance(item, dict) and not _item_has_evidence_id(item) and not clean_text(item.get("caveat") or ""):
                            item["status"] = item.get("status") or "unverified"
                            item["caveat"] = "Evidence reference was not supplied in the source material."
                            applied.append({"pass": pass_number, "section": index, "action": "flag_missing_evidence"})
                            changed = True
        if not changed:
            converged = True
            break

    design_review = review_storyboard_design(working)
    working["design_review"] = design_review
    registry = build_evidence_registry(working)
    working["evidence_registry"] = registry
    analytical_review = review_storyboard_analysis(working, registry=registry)
    working["analytical_review"] = analytical_review
    critique = {
        "critique_schema": 1,
        "max_passes": max(1, max_passes),
        "passes": passes,
        "converged": converged,
        "applied": applied,
        "design_review": design_review,
        "analytical_review": analytical_review,
        "guardrail": "No evidence identifiers, citations, numbers, or claims were invented during critique.",
    }
    working["critique"] = critique
    return working, critique


_PREDICTIVE_REVIEW_TERMS = (
    "forecast",
    "prediction",
    "predictive",
    "predict ",
    "projected",
    "projection",
    "probability",
    "likelihood",
    "odds",
)
_BASELINE_REVIEW_TERMS = (
    "baseline",
    "ablation",
    "out-of-sample",
    "holdout",
    "cross-validation",
    "cross validation",
    "log-loss",
    "log loss",
    "brier",
    "backtest",
)
_UNCERTAINTY_REVIEW_TERMS = (
    "uncertainty",
    "credible interval",
    "confidence interval",
    "bootstrap",
    "standard error",
    "prediction interval",
    "confidence band",
)
_SENSITIVITY_REVIEW_TERMS = (
    "sensitivity",
    "scenario",
    "robustness",
    "robust to",
    "alternate pairing",
    "alternative pairing",
)
_ASSUMPTION_REVIEW_TERMS = (
    "assumption",
    "assumed",
    "inferred",
    "estimate",
    "estimated",
    "placeholder",
)
_PATH_DEPENDENT_REVIEW_TERMS = (
    "bracket",
    "tree",
    "decision path",
    "customer journey",
    "workflow",
    "funnel",
    "route",
    "pathway",
    "incident chain",
    "staged launch",
    "elimination",
    "progression",
)
_DECISION_PATH_REVIEW_TERMS = _PATH_DEPENDENT_REVIEW_TERMS
_DISCRETE_OUTCOME_REVIEW_TERMS = (
    "outcome",
    "state",
    "branch",
    "stage",
    "handoff",
    "scenario",
    "failure mode",
)
_OUTCOME_DISTRIBUTION_REVIEW_TERMS = (
    "heatmap",
    "outcome distribution",
    "score distribution",
    "state distribution",
    "scenario distribution",
)


def review_storyboard_analysis(
    storyboard: dict[str, Any],
    *,
    registry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Recompute the analytical-completeness review for a storyboard.

    This public entry point is used by both the design critique and the publish
    gate so a stored, stale review record cannot be treated as an approval.
    """
    return _review_storyboard_analysis(storyboard, registry or build_evidence_registry(storyboard))


def _review_storyboard_analysis(storyboard: dict[str, Any], registry: dict[str, Any]) -> dict[str, Any]:
    """Return durable, conservative analytical-review findings for a report.

    This is intentionally a completeness review, not a model evaluator.  It
    relies on an optional ``requirements.analysis_review`` contract plus the
    supplied storyboard text.  The latter lets legacy callers get useful
    warnings, while the contract lets new callers state exactly which analysis
    checks were completed without asking the renderer to infer or recompute
    scientific results.
    """
    contract = storyboard.get("analysis_contract")
    contract = dict(contract) if isinstance(contract, dict) else {}
    text = _storyboard_review_text(storyboard)
    delivered_text = _storyboard_review_text(storyboard, include_context=False)
    mode = clean_text(contract.get("mode") or "").lower()
    is_predictive = mode in {"forecast", "forecasting", "predictive", "prediction", "simulation"}
    if not is_predictive:
        is_predictive = _contains_any(text, _PREDICTIVE_REVIEW_TERMS)

    findings: list[dict[str, Any]] = []

    def add(
        finding_id: str,
        *,
        category: str,
        severity: str,
        claim: str,
        recommendation: str,
        evidence: list[dict[str, str]] | None = None,
    ) -> None:
        findings.append({
            "id": finding_id,
            "category": category,
            "severity": severity,
            "claim": claim,
            "recommendation": recommendation,
            "evidence": evidence or [],
        })

    targets = registry.get("targets", []) if isinstance(registry.get("targets"), list) else []
    target_map = {
        clean_text(target.get("id") or target.get("ref") or ""): target
        for target in targets
        if isinstance(target, dict) and clean_text(target.get("id") or target.get("ref") or "")
    }

    if is_predictive:
        if not _baseline_review_complete(contract.get("baseline"), target_map):
            add(
                "missing_baseline_comparison",
                category="model_validation",
                severity="required",
                claim="This predictive report has no completed, resolvable baseline comparison with a method and result.",
                recommendation="Compare the production approach with a simple baseline on a shared holdout, report the primary metric plus the delta, and cite a registered evidence target for that output.",
            )
        if not _review_item_complete(contract.get("uncertainty")) and not _contains_any(delivered_text, _UNCERTAINTY_REVIEW_TERMS):
            add(
                "missing_uncertainty_quantification",
                category="uncertainty",
                severity="warning",
                claim="This predictive report presents point estimates without a declared uncertainty method.",
                recommendation="Add intervals or uncertainty bands derived from a stated method (for example bootstrap, posterior draws, or an appropriate analytical interval).",
            )

    assumptions_declared = _review_item_complete(contract.get("sensitivity"))
    has_assumption = bool(_as_list(contract.get("assumptions"))) or _contains_any(delivered_text, _ASSUMPTION_REVIEW_TERMS)
    if has_assumption and not assumptions_declared and not _contains_any(delivered_text, _SENSITIVITY_REVIEW_TERMS):
        add(
            "missing_assumption_sensitivity",
            category="assumption_sensitivity",
            severity="warning",
            claim="The report includes an inferred or assumed input without a declared sensitivity analysis.",
            recommendation="Run the material plausible alternatives and show whether the decision or ranking changes; otherwise label the assumption as unresolved.",
        )

    architecture = storyboard.get("editorial_architecture")
    architecture = architecture if isinstance(architecture, dict) else {}
    source_context = storyboard.get("source_context")
    source_context = source_context if isinstance(source_context, dict) else {}
    source_requirements = source_context.get("requirements")
    source_requirements = source_requirements if isinstance(source_requirements, dict) else {}
    requested_archetype = clean_text(
        source_requirements.get("editorial_archetype") or source_requirements.get("report_archetype") or ""
    ).lower().replace("-", "_").replace(" ", "_")
    path_dependent_requested = requested_archetype in {
        "path_dependent_forecast", "scenario_path_forecast", "decision_path_forecast",
    }
    is_path_dependent = (
        clean_text(architecture.get("archetype") or "").lower() == "path_dependent_forecast"
        or path_dependent_requested
    )
    if is_path_dependent and is_predictive:
        if not _review_item_complete(contract.get("decision_path")) and not _has_review_visual(
            storyboard,
            roles={"decision_path", "bracket"},
            terms=_DECISION_PATH_REVIEW_TERMS,
        ):
            add(
                "missing_decision_path_visual",
                category="presentation",
                severity="warning",
                claim="This path-dependent forecast has no declared visual of the route that leads to its outcome.",
                recommendation="Add the supplied journey, route, tree, bracket, or pathway with its relevant stage probabilities or transitions so readers can follow how the forecast is formed.",
            )
        if _contains_any(text, _DISCRETE_OUTCOME_REVIEW_TERMS) and not _review_item_complete(contract.get("outcome_distribution")) and not _has_review_visual(
            storyboard,
            roles={"outcome_distribution", "outcome_states"},
            terms=_OUTCOME_DISTRIBUTION_REVIEW_TERMS,
        ):
            add(
                "missing_outcome_distribution",
                category="presentation",
                severity="info",
                claim="The forecast discusses discrete outcome states without a declared outcome-distribution view.",
                recommendation="Show the most likely states, branches, or a compact distribution for the decision-relevant stages.",
            )
    elif (
        is_predictive
        and _contains_any(text, _PATH_DEPENDENT_REVIEW_TERMS)
        and not _review_item_complete(contract.get("decision_path"))
    ):
        add(
            "possible_path_dependent_forecast",
            category="presentation",
            severity="info",
            claim="The report language may describe a staged or path-dependent process, but no explicit decision-path analysis contract or editorial archetype was supplied.",
            recommendation="If the reader must follow transitions between states, declare analysis_review.decision_path and use editorial_archetype='path_dependent_forecast'. Otherwise no path-specific visual is required.",
        )

    references = registry.get("references", []) if isinstance(registry.get("references"), list) else []
    unresolved = _unresolved_evidence_refs([], target_map, references)
    if unresolved:
        add(
            "unresolved_evidence_anchors",
            category="evidence",
            severity="warning",
            claim="One or more supplied evidence references are not registered as present report targets.",
            recommendation="Register each local evidence target with a stable id and kind, or replace it with a stable external reference; do not invent an anchor.",
            evidence=unresolved[:20],
        )

    runtime = clean_text(contract.get("export_runtime") or contract.get("runtime") or "").lower()
    if runtime in {"cdn", "remote", "external"}:
        add(
            "external_runtime_dependency",
            category="export",
            severity="required",
            claim="The report declares a remote runtime even though DataClaw artifacts must remain self-contained.",
            recommendation="Keep Plotly in the local/artifact runtime and reduce the report payload or export size without adding a CDN dependency.",
        )

    return {
        "review_schema": 1,
        "mode": mode or ("predictive" if is_predictive else "general"),
        "status": "attention_required" if findings else "pass",
        "findings": findings,
        "guardrail": "Findings identify missing declared work; they do not assert that an uninspected analysis is wrong.",
    }


def _review_item_complete(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, str):
        return clean_text(value).lower() in {"complete", "completed", "done", "pass", "passed", "validated", "included"}
    if isinstance(value, dict):
        status = clean_text(value.get("status") or "").lower()
        if status in {"complete", "completed", "done", "pass", "passed", "validated", "included"}:
            return True
        return any(bool(value.get(key)) for key in ("method", "evidence", "result", "path", "summary"))
    return bool(value) if isinstance(value, (list, tuple, set)) else False


def _baseline_review_complete(value: Any, target_map: dict[str, dict[str, Any]]) -> bool:
    """Require concrete, registered proof for the publish-blocking baseline check.

    A mention of "baseline" in prose or a bare ``status: complete`` is only a
    declaration.  The contract must identify a completed comparison, explain
    its method and result, and point to a target already registered in the
    report inputs.  This remains a completeness check, not an attempt to
    independently re-run or certify the model.
    """
    if not isinstance(value, dict):
        return False
    status = clean_text(value.get("status") or "").lower()
    if status not in {"complete", "completed", "done", "pass", "passed", "validated", "included"}:
        return False
    if not clean_text(value.get("method") or "") or not clean_text(value.get("result") or value.get("summary") or ""):
        return False
    evidence = value.get("evidence", value.get("evidence_refs"))
    references = _evidence_refs_from_value(evidence)
    return (
        bool(references)
        and all(reference["kind"] != "unknown" for reference in references)
        and not _unresolved_evidence_refs([], target_map, references)
    )


def _storyboard_review_text(storyboard: dict[str, Any], *, include_context: bool = True) -> str:
    """Collect prose fields only; numerical arrays and figure payloads are excluded."""
    prose_keys = {
        "title", "report_goal", "subtitle", "detail", "summary", "interpretation",
        "conclusion", "caption", "dek", "kicker", "text", "note", "description",
        "label", "name", "assumption", "method", "status",
    }
    chunks: list[str] = []

    def walk(value: Any, key: str = "") -> None:
        if isinstance(value, dict):
            for child_key, child in value.items():
                walk(child, str(child_key))
        elif isinstance(value, list):
            for child in value:
                walk(child, key)
        elif isinstance(value, str) and key in prose_keys:
            text = clean_text(value)
            if text:
                chunks.append(text)

    source = {
        "section_plan": storyboard.get("section_plan", []),
        "analysis_contract": storyboard.get("analysis_contract", {}),
    }
    if include_context:
        source = {
            "title": storyboard.get("title"),
            "report_goal": storyboard.get("report_goal"),
            **source,
        }
    walk(source)
    return " ".join(chunks).lower()


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _has_review_visual(
    storyboard: dict[str, Any], *, roles: set[str], terms: tuple[str, ...],
) -> bool:
    """Detect an actually supplied visual, never a passing prose mention.

    Predictive review uses this as a lightweight completeness check. A report
    may discuss a journey or a bracket in its answer without supplying the
    visual needed to make that route inspectable, so titles and captions only
    count when attached to a visual section.
    """
    section_plan = storyboard.get("section_plan")
    if not isinstance(section_plan, list):
        return False
    for item in section_plan:
        if not isinstance(item, dict):
            continue
        section_type = clean_text(item.get("section_type") or "")
        if section_type not in VISUAL_SECTION_KINDS:
            continue
        data = item.get("data") if isinstance(item.get("data"), dict) else {}
        role = clean_text(
            data.get("story_role") or data.get("path_role") or data.get("forecast_role") or ""
        ).lower().replace("-", "_")
        if role in roles:
            return True
        visual_text = " ".join(
            clean_text(data.get(key) or "")
            for key in ("title", "caption", "dek", "interpretation", "conclusion")
        ).lower()
        if _contains_any(visual_text, terms):
            return True
    return False


def _chart_theme_failures(sections: list[dict[str, Any]]) -> list[dict[str, str]]:
    failures: list[dict[str, str]] = []
    for section in sections:
        payload = section.get("payload") if isinstance(section.get("payload"), dict) else {}
        figure = payload.get("figure")
        if not isinstance(figure, dict):
            continue
        layout = figure.get("layout") if isinstance(figure.get("layout"), dict) else {}
        styled_keys = [key for key in ("template", "paper_bgcolor", "plot_bgcolor", "colorway") if layout.get(key)]
        font = layout.get("font") if isinstance(layout.get("font"), dict) else {}
        if font.get("color"):
            styled_keys.append("font.color")
        if styled_keys:
            failures.append({
                "section_id": clean_text(section.get("section_id") or ""),
                "keys": ", ".join(styled_keys),
            })
    return failures


def _runtime_smoke_failures(doc: str, sections: list[dict[str, Any]]) -> list[dict[str, str]]:
    failures: list[dict[str, str]] = []
    authored_document = bool(re.search(r"<html\b[^>]*data-dc-authored-document=", doc, re.IGNORECASE))
    if REPORT_SHELL_SCRIPT_ATTR not in doc and not authored_document:
        failures.append({"check": "report_shell_script", "detail": "missing report runtime script"})

    if any(clean_text(section.get("kind") or "") in CHART_SECTION_KINDS for section in sections) and not PLOTLY_RUNTIME_RE.search(doc):
        failures.append({"check": "plotly_runtime", "detail": "chart sections require an embedded Plotly runtime"})

    target_ids = set(re.findall(r"\bid=[\"']([^\"']+)[\"']", doc, re.IGNORECASE))
    target_ids.update(re.findall(r"\bdata-dc-section-id=[\"']([^\"']+)[\"']", doc, re.IGNORECASE))
    for anchor in re.findall(r"<a\b[^>]*\bhref=[\"']#([^\"']+)[\"']", doc, re.IGNORECASE):
        if anchor not in target_ids:
            failures.append({"check": "anchor_target", "detail": f"missing target #{anchor}"})

    for section in sections:
        kind = clean_text(section.get("kind") or "")
        section_id = clean_text(section.get("section_id") or "")
        if kind in CHART_SECTION_KINDS and "r-chart-target" not in doc:
            failures.append({"check": "chart_target", "detail": f"{section_id or kind} has no chart mount"})
        if kind in ADVANCED_VISUAL_SECTION_KINDS and "r-advanced-visual-target" not in doc:
            failures.append({"check": "advanced_visual_target", "detail": f"{section_id or kind} has no advanced visual mount"})
        if kind in INTERACTIVE_SECTION_KINDS and "data-dc-control-bar" not in doc:
            failures.append({"check": "interactive_controls", "detail": f"{section_id or kind} has no control mount"})
    return failures


def _contrast_failures(doc: str) -> list[dict[str, Any]]:
    """Check the shell's primary light/dark foreground pairs without a browser."""
    styles = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", doc, re.IGNORECASE | re.DOTALL))
    if not styles:
        return [{"pair": "shell", "detail": "no inline report token stylesheet"}]

    scopes = [styles]
    dark_match = re.search(r":root\[data-theme=[\"']dark[\"']\]\s*\{(.*?)\}", styles, re.DOTALL)
    if dark_match:
        scopes.append(dark_match.group(1))
    failures: list[dict[str, Any]] = []
    for index, scope in enumerate(scopes):
        ink = _css_hex_token(scope, "dc-ink") or _css_hex_token(styles, "dc-ink")
        surface = _css_hex_token(scope, "dc-surface") or _css_hex_token(styles, "dc-surface")
        muted = _css_hex_token(scope, "dc-muted") or _css_hex_token(styles, "dc-muted")
        if not ink or not surface or not muted:
            failures.append({"pair": "tokens", "detail": "missing dc-ink, dc-muted, or dc-surface color token"})
            continue
        for label, foreground, required in (("ink/surface", ink, 4.5), ("muted/surface", muted, 4.5)):
            ratio = _contrast_ratio(foreground, surface)
            if ratio < required:
                failures.append({"theme": "dark" if index else "light", "pair": label, "ratio": round(ratio, 2), "required": required})
    return failures


def _css_hex_token(css: str, token: str) -> str:
    match = re.search(rf"--{re.escape(token)}\s*:\s*(#[0-9a-fA-F]{{6}})", css)
    return match.group(1) if match else ""


def _contrast_ratio(first: str, second: str) -> float:
    def luminance(value: str) -> float:
        channels = [int(value[index:index + 2], 16) / 255 for index in (1, 3, 5)]
        adjusted = [channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4 for channel in channels]
        return 0.2126 * adjusted[0] + 0.7152 * adjusted[1] + 0.0722 * adjusted[2]

    high, low = sorted((luminance(first), luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _item_has_evidence_id(item: dict[str, Any]) -> bool:
    return any(clean_text(item.get(key) or "") for key in ("finding_id", "hypothesis_id", "evidence", "ref", "cell_id", "artifact_id"))


def _presentation_options(requirements: dict[str, Any]) -> dict[str, str]:
    """Return the small, domain-neutral presentation contract for a report.

    These choices control only how supplied findings and evidence are read. They
    cannot create new claims, categories, or supporting facts.
    """
    supplied = requirements.get("presentation")
    supplied = supplied if isinstance(supplied, dict) else {}
    mode = clean_text(
        supplied.get("mode")
        or requirements.get("presentation_mode")
        or "handcrafted"
    ).lower().replace("-", "_")
    if mode not in {"standard", "handcrafted"}:
        raise ValueError("presentation.mode must be 'standard' or 'handcrafted'")
    insight_layout = clean_text(
        supplied.get("insight_layout")
        or requirements.get("insight_layout")
        or "auto"
    ).lower().replace("-", "_")
    if insight_layout not in {"auto", "editorial_list", "card_grid"}:
        raise ValueError("presentation.insight_layout must be 'auto', 'editorial_list', or 'card_grid'")
    insight_evidence = clean_text(
        supplied.get("insight_evidence")
        or requirements.get("insight_evidence")
        or "none"
    ).lower().replace("-", "_")
    if insight_evidence not in {"none", "linked", "chips"}:
        raise ValueError("presentation.insight_evidence must be 'none', 'linked', or 'chips'")
    provenance = clean_text(
        supplied.get("provenance")
        or requirements.get("provenance_presentation")
        # Backwards-compatible spelling for callers that deliberately asked
        # for a reader-visible trace before the provenance/presentation split.
        or supplied.get("evidence_trace")
        or requirements.get("evidence_trace_presentation")
        or "audit"
    ).lower().replace("-", "_")
    if provenance not in {"audit", "disclosure", "expanded"}:
        raise ValueError("presentation.provenance must be 'audit', 'disclosure', or 'expanded'")
    data_notes = clean_text(
        supplied.get("data_notes")
        or requirements.get("data_notes")
        or "source_only"
    ).lower().replace("-", "_")
    if data_notes not in {"source_only", "automatic"}:
        raise ValueError("presentation.data_notes must be 'source_only' or 'automatic'")
    return {
        "mode": mode,
        "insight_layout": insight_layout,
        "insight_evidence": insight_evidence,
        "provenance": provenance,
        "data_notes": data_notes,
    }


_SELECTION_LINK_KEYS = (
    "archetype", "category", "segment", "persona", "cluster", "cohort",
    "type", "team", "entity", "player", "customer", "scenario",
)


def design_report_storyboard(
    *,
    report_goal: str,
    insights: list[dict[str, Any]],
    analyses: list[dict[str, Any]] | None = None,
    audience: str = "",
    title: str = "Analysis Report",
    requirements: dict[str, Any] | None = None,
    max_design_passes: int = 5,
) -> dict[str, Any]:
    """Create a cohesive report plan from completed insights and analysis assets.

    The initial plan preserves every supplied insight and analysis object. A
    bounded design-refinement pass then improves adjacency, local data notes,
    and chart interpretation using only supplied material; it never invents a
    conclusion, caveat, or analytical result.
    """
    requirements = copy.deepcopy(requirements or {})
    presentation = _presentation_options(requirements)
    analysis_contract = requirements.get("analysis_review", {})
    if not isinstance(analysis_contract, dict):
        raise ValueError("requirements.analysis_review must be a dictionary when supplied")
    analysis_contract = dict(analysis_contract)
    if "assumptions" not in analysis_contract and isinstance(requirements.get("assumptions"), list):
        analysis_contract["assumptions"] = requirements["assumptions"]
    analyses = analyses or []
    clean_goal = clean_text(report_goal or title)
    clean_audience = clean_text(audience or requirements.get("audience") or "decision-maker")
    normalized_insights = [copy.deepcopy(item) for item in insights if isinstance(item, dict)]
    normalized_analyses = [copy.deepcopy(item) for item in analyses if isinstance(item, dict)]
    if not normalized_insights:
        raise ValueError(
            "report_design_report requires at least one completed insight."
        )
    # Promote simple aggregate shapes into governed visual forms before
    # minimization.  This lets supplied semantics choose a richer default
    # without requiring every caller to hand-author a visual mapping.
    _promote_inferred_advanced_visuals(normalized_analyses)

    # Validate and minimize advanced payloads before they can enter either the
    # section plan or source_context. Unmapped columns never reach the HTML or
    # its regeneration sidecar.
    for index, analysis in enumerate(normalized_analyses):
        explicit = clean_text(analysis.get("section_type") or analysis.get("kind") or "")
        if explicit not in ADVANCED_VISUAL_SECTION_KINDS:
            continue
        source_data = analysis.get("data") if isinstance(analysis.get("data"), dict) else analysis
        projected, visual, _ = prepare_advanced_visual_data(source_data)
        sanitized = {
            key: copy.deepcopy(value)
            for key, value in analysis.items()
            if key not in {"data", "records", "rows", "visual", "visual_spec"}
        }
        sanitized.update({
            key: copy.deepcopy(value)
            for key, value in source_data.items()
            if key not in {"records", "rows", "visual", "visual_spec"}
        })
        sanitized["records"] = projected
        sanitized["visual"] = visual
        sanitized["section_type"] = "advanced_visual"
        normalized_analyses[index] = sanitized
    # The storyboard is an evidence-and-requirements contract, not a deterministic
    # page. The creative author writes the final document from the dossier; this
    # section_plan carries only what the evidence registry, source-binding
    # validation, the analytical/authoring reviews, and required-visual coverage
    # read: one analytical section per supplied asset, plus one insight grid of
    # the completed findings.
    planned_analyses: list[dict[str, Any]] = []
    for index, analysis in enumerate(normalized_analyses):
        planned = _storyboard_section_from_analysis(analysis, index)
        if not planned:
            continue
        planned["data"]["section_id"] = f"sec-analysis-{index + 1}"
        planned_analyses.append(planned)

    # Bind every completed insight to its evidence and to any advanced visual
    # that carries its claim, then keep them all: the evidence ledger and the
    # author dossier must see every finding, not a truncated subset.
    source_bound_insights = [_storyboard_insight_item(item, i) for i, item in enumerate(normalized_insights)]
    _pair_insights_with_evidence(source_bound_insights, planned_analyses)
    _bind_handcrafted_claim_sources(source_bound_insights, planned_analyses)

    section_plan: list[dict[str, Any]] = [{
        "section_type": "insight_grid",
        "layout_role": "primary_insights",
        "rationale": "Completed findings with caveats, evidence, and next actions.",
        "data": {
            "title": requirements.get("insights_title", "Primary insights"),
            "section_id": "sec-primary-insights",
            "semantic_key": "primary_insights",
            "caption": "Findings promoted from completed analysis, with caveats and next actions where available.",
            "items": source_bound_insights,
        },
    }]
    for planned in planned_analyses:
        planned["data"].setdefault("semantic_key", planned.get("layout_role"))
        section_plan.append({
            "section_type": planned["section_type"],
            "layout_role": planned["layout_role"],
            "rationale": planned["rationale"],
            "data": planned["data"],
        })

    storyboard = {
        "storyboard_schema": 2,
        "title": title,
        "report_goal": clean_goal,
        "audience": clean_audience,
        "presentation": presentation,
        "source_context": {
            "insights": copy.deepcopy(normalized_insights),
            "analyses": copy.deepcopy(normalized_analyses),
            "requirements": copy.deepcopy(requirements),
        },
        "analysis_contract": analysis_contract,
        "evidence_registry": requirements.get("evidence_registry", requirements.get("evidence_targets", [])),
        "quality_plan": {
            "gate": "run before publish",
            "rubric_version": rubric_version(),
            "checks": live_criterion_ids(),
        },
        "section_plan": section_plan,
    }
    return storyboard


_EDITORIAL_DESIGN_STAGES = (
    "restore_editorial_sequence",
    "complete_visual_hierarchy",
    "anchor_visuals_to_local_context",
    "recheck_evidence_and_explorer_pacing",
    "audit_page_architecture",
)


def review_storyboard_design(storyboard: dict[str, Any]) -> dict[str, Any]:
    """Story, pacing, and layout belong to the creative author.

    The editorial-architecture review was retired: design and story-arc choices
    are no longer gated. This stub keeps the design_review field present for
    callers that record it; it never reports a blocking finding.
    """
    return {"design_review_schema": 2, "status": "author_owned", "findings": []}


def review_storyboard_authoring(storyboard: dict[str, Any]) -> dict[str, Any]:
    """Check that runtime display choices have durable, source-owned inputs.

    A renderer may safely *place* facts, but it cannot infer which phrases in a
    prose finding should become pills, examples, or scan points.  This review
    makes that authoring gap visible before a visual author or a human editor
    is asked to compose the page.  It is domain-neutral: it only examines fact
    ownership and display semantics, never subject-matter words.
    """
    requirements = storyboard.get("source_context", {}).get("requirements", {})
    requirements = requirements if isinstance(requirements, dict) else {}
    presentation = requirements.get("presentation", {})
    presentation = presentation if isinstance(presentation, dict) else {}
    visual_config = storyboard.get("visual_author_config")
    if not isinstance(visual_config, dict):
        visual_config = requirements.get("visual_author") if isinstance(requirements.get("visual_author"), dict) else {}
    mode = clean_text(visual_config.get("mode") or "off").lower().replace("-", "_")
    # Full-document creative authoring is reviewed against its evidence dossier;
    # typed display facts remain the contract for bounded visual-plan modes.
    requested = bool(presentation.get("require_display_facts")) or mode in {"runtime", "required", "provided"}
    declared: set[tuple[str, str]] = set()
    explicit_fact_count = 0
    legacy_fact_count = 0
    findings: list[dict[str, Any]] = []

    def section_id(planned: dict[str, Any], index: int) -> str:
        data = planned.get("data") if isinstance(planned.get("data"), dict) else {}
        return clean_text(
            planned.get("visual_author_section_id")
            or data.get("visual_author_section_id")
            or planned.get("layout_role")
            or data.get("section_id")
            or f"section-{index + 1}"
        )

    def add_facts(raw: Any, *, owner: str) -> int:
        nonlocal explicit_fact_count
        if not isinstance(raw, list):
            return 0
        count = 0
        for fact in raw:
            if not isinstance(fact, dict):
                continue
            fact_id = clean_text(fact.get("fact_id") or fact.get("id"))
            text = clean_text(fact.get("text") or fact.get("label") or fact.get("value"))
            uses = fact.get("uses", fact.get("use"))
            if fact_id and text and uses:
                declared.add((owner, fact_id))
                explicit_fact_count += 1
                count += 1
        return count

    for fact in visual_config.get("facts", visual_config.get("source_facts", [])) or []:
        if not isinstance(fact, dict):
            continue
        owner = clean_text(fact.get("insight_id") or fact.get("finding_id") or fact.get("section_id") or fact.get("layout_role"))
        add_facts([fact], owner=owner)

    target_count = 0
    covered_target_count = 0
    for section_index, planned in enumerate(storyboard.get("section_plan", [])):
        if not isinstance(planned, dict):
            continue
        data = planned.get("data") if isinstance(planned.get("data"), dict) else {}
        owner = section_id(planned, section_index)
        add_facts(data.get("display_facts", data.get("visual_facts")), owner=owner)
        section_has_legacy = any(data.get(key) for key in (
            "pills", "display_pills", "visual_pills", "bullets", "scan_points", "visual_scan_points",
            "examples", "representative_examples", "visual_examples", "annotations", "visual_annotations",
        ))
        if section_has_legacy:
            legacy_fact_count += 1
            if requested and not any(item_owner == owner for item_owner, _ in declared):
                findings.append({
                    "id": "legacy_section_display_semantics",
                    "severity": "warning",
                    "section": owner,
                    "claim": "Section display copy is supplied through legacy pills, bullets, examples, or annotations without typed display facts.",
                    "recommendation": "Move the reader-facing source text into display_facts with stable fact IDs and allowed uses.",
                })

        if clean_text(planned.get("section_type") or "") != "insight_grid":
            continue
        items = data.get("items", data.get("insights", []))
        if not isinstance(items, list):
            continue
        for insight_index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            insight_owner = clean_text(item.get("visual_author_insight_id") or item.get("finding_id") or f"insight-{insight_index + 1}")
            local_explicit = add_facts(item.get("display_facts", item.get("visual_facts")), owner=insight_owner)
            legacy = any(item.get(key) for key in (
                "pills", "display_pills", "visual_pills", "bullets", "scan_points", "visual_scan_points",
                "examples", "representative_examples", "visual_examples", "annotations", "visual_annotations",
            ))
            if legacy:
                legacy_fact_count += 1
            is_completed = bool(clean_text(item.get("title") or item.get("headline") or item.get("statement") or item.get("detail") or item.get("summary")))
            if not requested or not is_completed:
                continue
            target_count += 1
            has_explicit = local_explicit > 0 or any(item_owner == insight_owner for item_owner, _ in declared)
            if has_explicit:
                covered_target_count += 1
                continue
            findings.append({
                "id": "legacy_insight_display_semantics" if legacy else "missing_insight_display_facts",
                "severity": "warning",
                "section": owner,
                "insight_id": insight_owner,
                "claim": (
                    "Insight uses untyped display copy that a runtime visual author cannot safely audit."
                    if legacy else "Insight has no typed source fact available for a pill, scan point, example, or annotation."
                ),
                "recommendation": "Add display_facts to the insight or provide visual_author.facts owned by this insight; use exact source text and explicit allowed uses.",
            })

    return {
        "status": "attention_recommended" if findings else "pass",
        "requested": requested,
        "mode": mode,
        "target_count": target_count,
        "covered_target_count": covered_target_count,
        "explicit_fact_count": explicit_fact_count,
        "legacy_display_owner_count": legacy_fact_count,
        "findings": findings,
        "guidance": "Display facts are source-owned editorial inputs. The visual author may select and place them, but may not infer them from prose.",
    }


def _render_authored_document(storyboard: dict[str, Any], *, title: str | None = None) -> str:
    """Revalidate and attach host-owned audit metadata to LLM-authored HTML."""
    authored = storyboard.get("authored_document")
    if not isinstance(authored, dict):
        raise ValueError("authored document payload is missing")
    html = authored.get("html")
    contract = authored.get("contract")
    if not isinstance(html, str) or not isinstance(contract, dict):
        raise ValueError("authored document requires HTML and an author contract")
    validation = validate_authored_document(html, contract)
    if authored.get("dossier_sha256") != contract.get("dossier_sha256"):
        raise ValueError("authored document dossier identity no longer matches its contract")

    # Never trust model-supplied host metadata, even if a persisted storyboard
    # was manually edited after the original authoring pass.
    reserved_patterns = (
        r"<script[^>]*data-dc-author-coverage[^>]*>.*?</script>",
        r"<script[^>]*data-dc-author-evidence-map[^>]*>.*?</script>",
        r"<script[^>]*data-dc-evidence-review[^>]*>.*?</script>",
        r"<script[^>]*data-dc-evidence-registry[^>]*>.*?</script>",
        rf"<script[^>]*{re.escape(REPORT_CONTRACT_ATTR)}[^>]*>.*?</script>",
        rf"<script[^>]*{re.escape(REGENERATION_RECIPE_ATTR)}[^>]*>.*?</script>",
        r"<script[^>]*data-dc-section-meta[^>]*>.*?</script>",
    )
    for pattern in reserved_patterns:
        html = re.sub(pattern, "", html, flags=re.IGNORECASE | re.DOTALL)

    registry = build_evidence_registry(storyboard)
    report_contract = _report_contract_for_storyboard(storyboard)
    recipe = ensure_regeneration_recipe(storyboard)
    evidence_map = {
        item["alias"]: {"id": item.get("id"), "kind": item.get("kind")}
        for item in contract.get("evidence", [])
        if isinstance(item, dict) and clean_text(item.get("alias") or "")
    }
    canonical_coverage = {
        "coverage_schema": 1,
        "used": validation["coverage"]["used"],
        "omitted": [
            {"source": source, "reason": reason}
            for source, reason in sorted(validation["coverage"]["omitted"].items())
        ],
    }
    authored_meta = {
        "section_schema": 3,
        "kind": "narrative_band",
        "section_id": "authored-document",
        "title": clean_text(title or storyboard.get("title") or "Analysis Report"),
        "caption": clean_text(storyboard.get("report_goal") or ""),
        "payload": {
            "semantic_role": "authored_document",
            "source_count": len(contract.get("sources", [])),
            "evidence_target_count": len(contract.get("evidence", [])),
            "authored": True,
        },
    }
    # Bind the independent evidence-review verdict into the hash-covered HTML so
    # the publish boundary can trust it without re-reading the mutable storyboard
    # visual_author record.
    authored_evidence_review = authored.get("evidence_review") if isinstance(authored.get("evidence_review"), dict) else {}
    evidence_review_marker = {"schema": 1, "status": clean_text(authored_evidence_review.get("status") or "unknown")}
    host_scripts = "\n".join((
        f'<script type="application/json" data-dc-author-coverage>{_json_for_script(canonical_coverage)}</script>',
        f'<script type="application/json" data-dc-author-evidence-map>{_json_for_script(evidence_map)}</script>',
        f'<script type="application/json" data-dc-evidence-review>{_json_for_script(evidence_review_marker)}</script>',
        _evidence_registry_script(registry),
        _report_contract_script(report_contract),
        _regeneration_recipe_script(recipe),
        f'<script type="application/json" data-dc-section-meta>{_json_for_script(authored_meta)}</script>',
    ))
    html = re.sub(
        r"<meta\b(?=[^>]*http-equiv=[\"']Content-Security-Policy[\"'])[^>]*>",
        "",
        html,
        flags=re.IGNORECASE,
    )
    csp = f'<meta http-equiv="Content-Security-Policy" content="{STORED_ARTIFACT_CSP}">'
    html = re.sub(r"</head\s*>", csp + "\n</head>", html, count=1, flags=re.IGNORECASE)
    if not re.search(r"<html\b[^>]*data-dc-authored-document=", html, re.IGNORECASE):
        html = re.sub(
            r"<html\b([^>]*)>",
            r'<html\1 data-dc-authored-document="true">',
            html,
            count=1,
            flags=re.IGNORECASE,
        )
    html = re.sub(r"</body\s*>", host_scripts + "\n</body>", html, count=1, flags=re.IGNORECASE)
    authored["coverage"] = validation["coverage"]
    storyboard["authored_document"] = authored
    return html


def render_report_from_storyboard(storyboard: dict[str, Any], *, title: str | None = None) -> str:
    """Render the authored report document.

    Every report is a creative authored document, so the storyboard must carry an
    ``authored_document`` produced by the visual author. Evidence rigor — the
    advanced-visual claim-source binding — is still enforced, but story, pacing,
    and layout belong to the author: there is no editorial story-arc gate.
    """
    section_plan = storyboard.get("section_plan", [])
    if not isinstance(section_plan, list) or not section_plan:
        raise ValueError("storyboard requires non-empty list 'section_plan'")
    _validate_handcrafted_source_bindings(storyboard)
    if not isinstance(storyboard.get("authored_document"), dict):
        raise ValueError(
            "storyboard is missing an authored_document; creative authoring must run before rendering"
        )
    return _render_authored_document(storyboard, title=title)


def _evidence_ref_keys(source: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for field in ("finding_id", "hypothesis_id"):
        value = clean_text(source.get(field) or "")
        if value:
            keys.add(value)
    for entry in _as_list(source.get("evidence") or source.get("evidence_refs")):
        if isinstance(entry, dict):
            for field in ("cell_id", "ref", "artifact_id", "finding_id", "hypothesis_id", "path"):
                value = clean_text(entry.get(field) or "")
                if value:
                    keys.add(value)
        else:
            value = clean_text(entry)
            if value:
                keys.add(value)
    return keys


def _pair_insights_with_evidence(insights: list[dict[str, Any]], planned_analyses: list[dict[str, Any]]) -> None:
    """Anchor each insight to its supporting section without reader-facing backlinks."""
    analysis_refs = []
    for planned in planned_analyses:
        data = planned.get("data", {})
        refs = _evidence_ref_keys(data)
        source = data.get("data") if isinstance(data.get("data"), dict) else None
        if source:
            refs |= _evidence_ref_keys(source)
        analysis_refs.append(refs)
    for insight in insights:
        refs = _evidence_ref_keys(insight)
        if not refs:
            continue
        for planned, planned_refs in zip(planned_analyses, analysis_refs):
            if refs & planned_refs:
                anchor = clean_text(planned["data"].get("section_id") or "")
                if not anchor:
                    continue
                insight["evidence_anchor"] = anchor
                break


def _bind_handcrafted_claim_sources(
    insights: list[dict[str, Any]], planned_analyses: list[dict[str, Any]],
) -> None:
    """Bind each rendered advanced interpretation to a supplied finding.

    The interpretation text remains byte-for-byte sourced from the completed
    analysis. The binding records which supplied finding it supports and a
    digest of the exact source text, so refinement cannot silently create or
    replace a claim.
    """
    insight_sources: list[tuple[str, set[str], dict[str, Any]]] = []
    for index, insight in enumerate(insights):
        source_id = clean_text(insight.get("finding_id") or insight.get("insight_id") or f"insight-{index + 1}")
        insight_sources.append((source_id, _evidence_ref_keys(insight), insight))
    for planned in planned_analyses:
        if clean_text(planned.get("section_type") or "") != "advanced_visual":
            continue
        data = planned.get("data") if isinstance(planned.get("data"), dict) else {}
        interpretation = clean_text(data.get("interpretation") or data.get("insight") or data.get("summary") or "")
        if not interpretation:
            raise ValueError("handcrafted advanced visuals require a supplied interpretation")
        explicit_id = clean_text(data.get("finding_id") or data.get("claim_source_id") or "")
        analysis_refs = _evidence_ref_keys(data)
        candidates = [
            source for source in insight_sources
            if (explicit_id and source[0] == explicit_id)
            or (analysis_refs and source[1] and bool(analysis_refs & source[1]))
        ]
        if not candidates and len(insight_sources) == 1:
            candidates = insight_sources
        if len(candidates) != 1:
            raise ValueError(
                "handcrafted advanced visual interpretations must bind to exactly one supplied finding "
                "using finding_id/claim_source_id or shared evidence refs"
            )
        source_id, _, source_insight = candidates[0]
        source_insight["evidence_anchor"] = clean_text(data.get("section_id") or "")
        source_insight["advanced_visual_anchor"] = clean_text(data.get("section_id") or "")
        data["claim_source"] = {
            "finding_id": source_id,
            "source": "completed_analysis.interpretation",
            "text_sha256": hashlib.sha256(interpretation.encode("utf-8")).hexdigest(),
            "data_sha256": _stable_json_sha256({
                "records": data.get("records", data.get("rows", [])),
                "visual": data.get("visual", data.get("visual_spec", {})),
            }),
        }
        planned["data"] = data


def _validate_handcrafted_source_bindings(storyboard: dict[str, Any]) -> None:
    source_context = storyboard.get("source_context") if isinstance(storyboard.get("source_context"), dict) else {}
    insights = [item for item in source_context.get("insights", []) if isinstance(item, dict)]
    analyses = [item for item in source_context.get("analyses", []) if isinstance(item, dict)]
    insight_sources = [
        (
            clean_text(item.get("finding_id") or item.get("insight_id") or f"insight-{index + 1}"),
            _evidence_ref_keys(item),
        )
        for index, item in enumerate(insights)
    ]
    insight_ids = {source_id for source_id, _ in insight_sources}
    source_claims: set[tuple[str, str, str]] = set()
    for analysis in analyses:
        explicit = clean_text(analysis.get("section_type") or analysis.get("kind") or "")
        if explicit != "advanced_visual":
            continue
        source_data = analysis.get("data") if isinstance(analysis.get("data"), dict) else analysis
        records, visual, _ = prepare_advanced_visual_data(source_data)
        interpretation = clean_text(
            source_data.get("interpretation") or source_data.get("insight") or source_data.get("summary") or ""
        )
        explicit_id = clean_text(source_data.get("finding_id") or source_data.get("claim_source_id") or "")
        refs = _evidence_ref_keys(source_data)
        candidate_ids = {
            source_id for source_id, insight_refs in insight_sources
            if (explicit_id and explicit_id == source_id)
            or (refs and insight_refs and bool(refs & insight_refs))
        }
        if not candidate_ids and len(insight_sources) == 1:
            candidate_ids = {insight_sources[0][0]}
        for source_id in candidate_ids:
            source_claims.add((
                source_id,
                hashlib.sha256(interpretation.encode("utf-8")).hexdigest(),
                _stable_json_sha256({"records": records, "visual": visual}),
            ))
    for planned in storyboard.get("section_plan", []):
        if not isinstance(planned, dict) or clean_text(planned.get("section_type") or "") != "advanced_visual":
            continue
        data = planned.get("data") if isinstance(planned.get("data"), dict) else {}
        binding = data.get("claim_source") if isinstance(data.get("claim_source"), dict) else {}
        finding_id = clean_text(binding.get("finding_id") or "")
        claim = (
            finding_id,
            clean_text(binding.get("text_sha256") or ""),
            clean_text(binding.get("data_sha256") or ""),
        )
        if finding_id not in insight_ids or claim not in source_claims:
            raise ValueError(
                "handcrafted claim/data binding does not match the storyboard's supplied completed insights and analyses"
            )


def _storyboard_insight_item(item: dict[str, Any], index: int) -> dict[str, Any]:
    copied = dict(item)
    copied.setdefault("title", _item_title(item, f"Insight {index + 1}"))
    if _item_detail(item):
        copied.setdefault("detail", _item_detail(item))
    copied.setdefault("status", item.get("status") or item.get("severity") or item.get("confidence") or "reviewed")
    return copied


def _disclosure_text(value: Any) -> str:
    """Render supplied disclosure material without inventing a risk statement."""
    if isinstance(value, str):
        return clean_text(value)
    if isinstance(value, dict):
        detail = clean_text(value.get("detail") or value.get("summary") or value.get("result") or value.get("text") or "")
        method = clean_text(value.get("method") or "")
        return ": ".join(part for part in (method, detail) if part)
    if isinstance(value, list):
        parts = [_disclosure_text(item) for item in value]
        return " ".join(part for part in parts if part)
    return ""


def _record_field(records: list[dict[str, Any]], *candidates: Any) -> str:
    """Resolve a supplied field name without creating or transforming values."""
    available: dict[str, str] = {}
    for row in records:
        for key in row:
            normalized = re.sub(r"[^a-z0-9]+", "_", clean_text(key).lower()).strip("_")
            if normalized and normalized not in available:
                available[normalized] = clean_text(key)
    for candidate in candidates:
        normalized = re.sub(r"[^a-z0-9]+", "_", clean_text(candidate).lower()).strip("_")
        if normalized in available:
            return available[normalized]
    return ""


def _inferred_advanced_visual(data: dict[str, Any]) -> dict[str, Any] | None:
    """Infer a governed visual mapping from clear aggregate semantics.

    This is intentionally conservative.  It recognizes relationships, not
    report domains, and returns only mappings to existing columns.  Ambiguous
    payloads remain tables, explorers, figures, or explicit components.
    """
    records = data.get("records", data.get("rows"))
    if not isinstance(records, list) or not records or not all(isinstance(row, dict) for row in records):
        return None
    if not clean_text(data.get("interpretation") or data.get("insight") or data.get("summary") or ""):
        return None
    if not clean_text(data.get("caption") or ""):
        return None

    rows = [row for row in records if isinstance(row, dict)]
    intent = clean_text(
        data.get("visual_intent")
        or data.get("semantic_role")
        or data.get("semantic_intent")
        or data.get("relationship")
        or ""
    ).lower().replace("-", "_")
    chart = data.get("chart") if isinstance(data.get("chart"), dict) else {}

    label = _record_field(
        rows,
        data.get("label"), chart.get("label"), chart.get("x"),
        "label", "name", "category", "entity", "team", "player", "segment", "cohort", "scenario", "item",
    )
    value = _record_field(
        rows,
        data.get("value"), chart.get("value"), chart.get("y"),
        "value", "score", "rate", "percentage", "percent", "probability", "count", "total", "amount",
    )
    start = _record_field(rows, data.get("start"), "start", "before", "previous", "baseline", "initial")
    end = _record_field(rows, data.get("end"), "end", "after", "current", "final")
    low = _record_field(rows, data.get("low"), "low", "lower", "minimum", "min", "q1", "p10")
    high = _record_field(rows, data.get("high"), "high", "upper", "maximum", "max", "q3", "p90")
    x = _record_field(rows, data.get("x"), chart.get("x"), "x", "column", "dimension_x", "category_x")
    y = _record_field(rows, data.get("y"), chart.get("y"), "y", "row", "dimension_y", "category_y")
    source = _record_field(rows, data.get("source"), "source", "origin", "from")
    target = _record_field(rows, data.get("target"), "target", "destination", "to")
    time_field = _record_field(rows, data.get("time"), "time", "date", "timestamp", "period", "year")
    detail = _record_field(rows, data.get("detail"), "detail", "description", "note")

    visual: dict[str, Any] | None = None
    if intent in {"flow", "path", "transition", "funnel", "network", "journey"} and source and target:
        visual = {"type": "flow", "source": source, "target": target}
        if value and value not in {source, target}:
            visual["value"] = value
    elif intent in {"bracket", "tournament", "elimination"} and source and target:
        visual = {"type": "bracket", "source": source, "target": target}
        if value and value not in {source, target}:
            visual["value"] = value
    elif label and start and end:
        visual = {"type": "slopegraph", "label": label, "start": start, "end": end}
    elif label and low and high:
        visual = {"type": "range_band", "label": label, "low": low, "high": high}
        if value and value not in {low, high}:
            visual["value"] = value
    elif intent in {"matrix", "heatmap", "cross_tab", "crosstab"} and x and y and value:
        visual = {"type": "matrix", "x": x, "y": y, "value": value}
    elif intent in {"timeline", "sequence", "milestone", "history"} and label and time_field:
        visual = {"type": "timeline", "label": label, "time": time_field}
        if detail:
            visual["detail"] = detail
    elif (
        label and value
        and not any(data.get(key) for key in ("filters", "controls", "columns"))
        and not any(chart.get(key) for key in ("color", "group", "series", "facet", "size"))
    ):
        chart_type = clean_text(chart.get("type") or "").lower()
        if not chart or chart_type in {"bar", "column", "horizontal_bar", ""} or intent in {
            "ranking", "ranked", "leaderboard", "magnitude", "comparison",
        }:
            visual = {
                "type": "lollipop" if len(rows) <= 12 else "dot_plot",
                "label": label,
                "value": value,
                "sort": "descending" if intent in {"ranking", "ranked", "leaderboard"} else "source",
            }
    if visual is None:
        return None

    for key in ("unit", "start_label", "end_label", "legend_title", "scale", "zero_baseline", "stages"):
        if key in data:
            visual[key] = copy.deepcopy(data[key])
    return visual


def _fold_visual_into_direction(data: dict[str, Any], visual: dict[str, Any]) -> None:
    """Turn an unsupported visual mapping into free-text bespoke visual intent.

    Section kinds and governed advanced-visual forms stay a small, semantic,
    validated vocabulary. A caller who wants a custom form (a waffle, a radial
    tournament map, a bespoke SVG) expresses it as visual_direction; the creative
    author realizes it from the same bounded data under the usual evidence and
    safety rules, rather than the request being rejected as an unknown type.
    """
    requested = clean_text(visual.get("type") or "")
    note = clean_text(visual.get("description") or visual.get("note") or visual.get("caption") or "")
    existing = clean_text(data.get("visual_direction") or data.get("visual_intent") or "")
    parts = [existing]
    if requested:
        parts.append(
            f"Build a bespoke '{requested}' visual as custom SVG, Canvas, or HTML from the bounded data."
        )
    if note:
        parts.append(note)
    hint_fields = {
        key: value for key, value in visual.items()
        if key not in {"type", "description", "note", "caption", "medium"}
    }
    if hint_fields:
        parts.append("Suggested encodings: " + json.dumps(hint_fields, ensure_ascii=False, default=str)[:600])
    medium = clean_text(visual.get("medium") or "").lower()
    if medium and not clean_text(data.get("medium") or ""):
        data["medium"] = medium
    data["visual_direction"] = " ".join(part for part in parts if part).strip()

    # Field-level data minimization: the discarded mapping named specific record
    # columns. Keep only those (plus any explicitly declared fields) so unmapped
    # columns — which may be sensitive — are never copied into the dossier. A
    # governed advanced visual projects mapped fields; the bespoke path must too.
    records = data.get("records") if isinstance(data.get("records"), list) else data.get("rows")
    columns = _columns_from_records(records) if isinstance(records, list) else []
    declared = [clean_text(f) for f in data.get("fields", []) if clean_text(f)] if isinstance(data.get("fields"), list) else []
    mapped = [
        clean_text(value)
        for key, value in hint_fields.items()
        if isinstance(value, str) and clean_text(value) in columns
    ]
    allow = list(dict.fromkeys([f for f in (declared + mapped) if f in columns]))
    # Always set an explicit allowlist for a folded bespoke visual — even when it
    # resolves to nothing. Downstream data minimization then fails closed (no raw
    # columns) rather than falling back to copying every column. A caller that
    # needs specific fields in a bespoke visual must name them in `fields`.
    data["fields"] = allow


def _promote_inferred_advanced_visuals(analyses: list[dict[str, Any]]) -> None:
    """Normalize familiar charts and promote unambiguous bespoke visuals."""
    for index, analysis in enumerate(analyses):
        explicit = clean_text(analysis.get("section_type") or analysis.get("kind") or "")
        # Untyped assets and assets explicitly typed as advanced_visual are both
        # candidates; any other explicit section type is left untouched.
        if explicit and explicit != "advanced_visual":
            continue
        data = analysis.get("data") if isinstance(analysis.get("data"), dict) else analysis
        visual = data.get("visual", data.get("visual_spec"))
        if isinstance(visual, dict):
            visual_type = clean_text(visual.get("type") or "").lower().replace("-", "_")
            chart_type = STANDARD_CHART_TYPE_ALIASES.get(visual_type)
            if chart_type and not explicit:
                normalized_chart = copy.deepcopy(visual)
                normalized_chart["type"] = chart_type
                data["chart"] = normalized_chart
                data.pop("visual", None)
                data.pop("visual_spec", None)
                continue
            if not visual_type or visual_type in ADVANCED_VISUAL_FIELDS:
                # A blank or governed visual type keeps the deterministic
                # advanced-visual contract, which the artifact layer validates.
                if not explicit:
                    promoted = copy.deepcopy(analysis)
                    promoted["section_type"] = "advanced_visual"
                    analyses[index] = promoted
                continue
            # An unrecognized visual type is a request for a bespoke visual, not
            # an error — whether it arrived untyped or already typed as an
            # advanced_visual. Fold it into free-text visual_direction (with a
            # field allowlist) and drop the governed typing so the creative
            # author builds a custom visual instead of hitting the closed
            # advanced-visual validator.
            _fold_visual_into_direction(data, visual)
            data.pop("visual", None)
            data.pop("visual_spec", None)
            if explicit == "advanced_visual":
                analysis.pop("section_type", None)
                analysis.pop("kind", None)
                if isinstance(analysis.get("data"), dict):
                    analysis["data"].pop("section_type", None)
                    analysis["data"].pop("kind", None)
            continue
        if explicit:
            # Explicit advanced_visual with no visual mapping: leave it for the
            # governed validator, which projects only the mapped fields.
            continue
        inferred = _inferred_advanced_visual(data)
        if inferred is None:
            continue
        promoted = copy.deepcopy(analysis)
        target = promoted.get("data") if isinstance(promoted.get("data"), dict) else promoted
        target["visual"] = inferred
        promoted["section_type"] = "advanced_visual"
        analyses[index] = promoted


def _storyboard_section_from_analysis(analysis: dict[str, Any], index: int) -> dict[str, Any] | None:
    explicit = clean_text(analysis.get("section_type") or analysis.get("kind") or "")
    data = analysis.get("data") if isinstance(analysis.get("data"), dict) else dict(analysis)
    data = dict(data)
    data.setdefault("story_arc", analysis.get("story_arc") or analysis.get("arc") or "")
    data.setdefault("title", analysis.get("title") or f"Analysis {index + 1}")
    data.setdefault("caption", analysis.get("caption") or analysis.get("summary") or "")
    # Keep the small source contract attached when an analysis wraps its
    # rendering payload in ``data``. This lets later evidence checks identify
    # the asset without imposing a component schema on the author.
    for source_key in ("visual_author_section_id", "section_id", "slug", "id", "required_visual"):
        if source_key in analysis:
            data.setdefault(source_key, analysis[source_key])
    source_material = {**analysis, **data}
    data.setdefault(
        "report_asset_source_id",
        next(
            (
                clean_text(source_material.get(key))
                for key in ("visual_author_section_id", "section_id", "slug", "id")
                if clean_text(source_material.get(key))
            ),
            f"analysis-{index + 1}",
        ),
    )

    renderable = (
        STORY_SECTION_KINDS
        | VISUAL_SECTION_KINDS
        | {"table", "callout", "text", "comparison", "checklist", "explanation", "metric_row"}
    )
    if explicit in renderable:
        return {
            "section_type": explicit,
            "layout_role": f"analysis_{index + 1}_{explicit}",
            "rationale": "Use the explicit section type chosen by the report designer.",
            "data": data,
        }
    if explicit:
        raise ValueError(
            f"analyses[{index}] requested unsupported section_type '{explicit}'; "
            f"supported types: {', '.join(sorted(renderable))}"
        )

    semantic_role = clean_text(data.get("semantic_role") or data.get("semantic_intent") or data.get("content_role") or "").lower().replace("-", "_")
    if semantic_role in {"methodology", "method", "assumptions"} and isinstance(data.get("methods", data.get("steps", data.get("items"))), list):
        data["semantic_role"] = "methodology"
        return {
            "section_type": "methodology_block",
            "layout_role": f"analysis_{index + 1}_methodology",
            "rationale": "Render declared method, assumptions, or validation steps as a compact methodology block.",
            "data": data,
        }
    if semantic_role in {"data_quality", "coverage", "uncertainty", "limitation", "caveat"} and _disclosure_text(data):
        data["semantic_role"] = "data_quality" if semantic_role in {"data_quality", "coverage"} else "uncertainty"
        return {
            "section_type": "callout",
            "layout_role": f"analysis_{index + 1}_{data['semantic_role']}",
            "rationale": "Keep declared scope, quality, or uncertainty information as a visible reader-facing disclosure.",
            "data": data,
        }
    if semantic_role in {"provenance", "evidence"} and isinstance(data.get("evidence", data.get("items")), list):
        data["semantic_role"] = "provenance"
        return {
            "section_type": "evidence_trace",
            "layout_role": f"analysis_{index + 1}_evidence_trace",
            "rationale": "Render declared provenance as a traceable evidence list rather than prose.",
            "data": data,
        }
    if semantic_role in {"timeline", "sequence", "history"} and isinstance(data.get("events", data.get("timeline", data.get("items"))), list):
        data["semantic_role"] = "timeline"
        return {
            "section_type": "ledger_timeline",
            "layout_role": f"analysis_{index + 1}_timeline",
            "rationale": "Render declared sequence data as a chronological timeline.",
            "data": data,
        }
    if semantic_role in {"status", "readiness", "checks"} and isinstance(data.get("checks", data.get("items")), list):
        data["semantic_role"] = "status"
        return {
            "section_type": "checklist",
            "layout_role": f"analysis_{index + 1}_checklist",
            "rationale": "Render declared status items as a scan-friendly checklist.",
            "data": data,
        }
    if semantic_role in {"metrics", "metric", "kpi", "scorecard", "summary_metrics"} and isinstance(data.get("metrics", data.get("items")), list):
        if "metrics" not in data:
            data["metrics"] = data.get("items", [])
        return {
            "section_type": "metric_row",
            "layout_role": f"analysis_{index + 1}_metrics",
            "rationale": "Render declared headline measures as a compact metric row.",
            "data": data,
        }
    if semantic_role in {"findings", "insights", "conclusions", "takeaways"} and isinstance(data.get("findings", data.get("insights", data.get("items"))), list):
        if "items" not in data:
            data["items"] = data.get("findings", data.get("insights", []))
        return {
            "section_type": "findings",
            "layout_role": f"analysis_{index + 1}_findings",
            "rationale": "Render declared conclusions as an editorial findings list.",
            "data": data,
        }
    if semantic_role in {"hypotheses", "hypothesis", "validation_ledger"} and isinstance(data.get("hypotheses", data.get("items")), list):
        return {
            "section_type": "hypothesis_ledger",
            "layout_role": f"analysis_{index + 1}_hypotheses",
            "rationale": "Render supplied hypothesis dispositions as a traceable ledger.",
            "data": data,
        }
    if semantic_role in {"process", "procedure", "explanation", "mechanism", "steps"} and isinstance(data.get("steps", data.get("points", data.get("items"))), list):
        if "steps" not in data:
            data["steps"] = data.get("points", data.get("items", []))
        return {
            "section_type": "explanation",
            "layout_role": f"analysis_{index + 1}_explanation",
            "rationale": "Render supplied stages or reasoning steps as a sequential explanation.",
            "data": data,
        }
    if semantic_role in {"comparison", "comparative", "side_by_side", "tradeoffs"} and isinstance(data.get("groups", data.get("items")), list):
        return {
            "section_type": "comparison",
            "layout_role": f"analysis_{index + 1}_comparison",
            "rationale": "Render supplied peers or trade-offs as a direct comparison.",
            "data": data,
        }
    if semantic_role in {"lookup", "data_table", "records", "catalog"} and isinstance(data.get("rows", data.get("records")), list):
        rows = data.get("rows", data.get("records", []))
        data.setdefault("rows", rows)
        data.setdefault("columns", _columns_from_records(rows)[:12])
        data.setdefault("filters", data.get("controls") or _infer_filters(rows))
        return {
            "section_type": "interactive_table",
            "layout_role": f"analysis_{index + 1}_interactive_table",
            "rationale": "Render supplied record-shaped evidence as a searchable exact-value table.",
            "data": data,
        }

    if isinstance(data.get("groups"), list) and data.get("groups"):
        return {
            "section_type": "comparison",
            "layout_role": f"analysis_{index + 1}_comparison",
            "rationale": "Side-by-side groups compare cleanly as comparison cards.",
            "data": data,
        }
    if isinstance(data.get("checks"), list) and data.get("checks"):
        return {
            "section_type": "checklist",
            "layout_role": f"analysis_{index + 1}_checklist",
            "rationale": "Check items render as a readiness checklist.",
            "data": data,
        }
    if isinstance(data.get("events") or data.get("timeline"), list) and (data.get("events") or data.get("timeline")):
        return {
            "section_type": "ledger_timeline",
            "layout_role": f"analysis_{index + 1}_ledger_timeline",
            "rationale": "Chronological events render as a timeline.",
            "data": data,
        }
    if isinstance(data.get("metrics"), list) and data.get("metrics"):
        return {
            "section_type": "metric_row",
            "layout_role": f"analysis_{index + 1}_metrics",
            "rationale": "Metric-shaped assets render as a compact scorecard.",
            "data": data,
        }
    if isinstance(data.get("hypotheses"), list) and data.get("hypotheses"):
        return {
            "section_type": "hypothesis_ledger",
            "layout_role": f"analysis_{index + 1}_hypotheses",
            "rationale": "Hypothesis-shaped assets render as a disposition ledger.",
            "data": data,
        }
    if isinstance(data.get("findings") or data.get("insights"), list) and (data.get("findings") or data.get("insights")):
        data.setdefault("items", data.get("findings") or data.get("insights"))
        return {
            "section_type": "findings",
            "layout_role": f"analysis_{index + 1}_findings",
            "rationale": "Finding-shaped assets render as an editorial list.",
            "data": data,
        }
    if isinstance(data.get("steps") or data.get("points"), list) and (data.get("steps") or data.get("points")):
        return {
            "section_type": "explanation",
            "layout_role": f"analysis_{index + 1}_explanation",
            "rationale": "Step-shaped assets render as a sequential explanation.",
            "data": data,
        }

    records = data.get("records", data.get("rows"))
    visual = data.get("visual", data.get("visual_spec"))
    if isinstance(records, list) and isinstance(visual, dict):
        return {
            "section_type": "advanced_visual",
            "layout_role": f"analysis_{index + 1}_advanced_visual",
            "rationale": "Use a handcrafted visual form matched to the supplied aggregate structure and keep its interpretation adjacent.",
            "data": data,
        }
    chart = data.get("chart")
    if isinstance(records, list) and isinstance(chart, dict):
        filters = data.get("filters", data.get("controls"))
        if not filters:
            filters = _infer_filters(records, chart)
        section_type = "chart_table_explorer" if data.get("columns") or filters or len(records) > 6 else "filterable_chart"
        data.setdefault("filters", filters)
        data.setdefault("columns", data.get("columns") or _columns_from_records(records)[:8])
        return {
            "section_type": section_type,
            "layout_role": f"analysis_{index + 1}_{section_type}",
            "rationale": "Pair an aggregate chart with the controls/table needed to inspect the evidence.",
            "data": data,
        }

    if isinstance(data.get("figure"), dict) or data.get("figure_json"):
        return {
            "section_type": "chart_interpretation",
            "layout_role": f"analysis_{index + 1}_chart_interpretation",
            "rationale": "Attach interpretation, caveats, and evidence beside the supplied chart.",
            "data": data,
        }

    if isinstance(records, list):
        data.setdefault("rows", records)
        data.setdefault("columns", _columns_from_records(records)[:12])
        data.setdefault("filters", data.get("controls") or _infer_filters(records))
        return {
            "section_type": "interactive_table",
            "layout_role": f"analysis_{index + 1}_interactive_table",
            "rationale": "Preserve an untyped aggregate as an exact-value table when no visual mapping is required.",
            "data": data,
        }

    if isinstance(data.get("rows"), list) and isinstance(data.get("columns"), list):
        data.setdefault("filters", data.get("controls") or _infer_filters(data.get("rows", [])))
        return {
            "section_type": "interactive_table",
            "layout_role": f"analysis_{index + 1}_interactive_table",
            "rationale": "Use an interactive table for lookup, sorting, and exact values.",
            "data": data,
        }

    items = data.get("items", data.get("entities"))
    if isinstance(items, list):
        filters = data.get("controls", data.get("filters"))
        if not filters:
            filters = _infer_filters(items)
        if filters and len(items) > 1:
            data.setdefault("controls", filters)
            return {
                "section_type": "selector_panel",
                "layout_role": f"analysis_{index + 1}_selector_panel",
                "rationale": "Let the reader choose an entity/archetype and inspect its metrics without scanning every card.",
                "data": data,
            }
        return {
            "section_type": "entity_card_grid",
            "layout_role": f"analysis_{index + 1}_entity_cards",
            "rationale": "Summarize entities/archetypes as cards instead of burying them in prose.",
            "data": data,
        }

    if clean_text(data.get("body") or data.get("text") or ""):
        return {
            "section_type": "text",
            "layout_role": f"analysis_{index + 1}_text",
            "rationale": "Prose-only analysis renders as a narrative text section.",
            "data": data,
        }

    # A bespoke visual described by visual_direction (or an interpretation-only
    # asset) is renderable: the creative author builds it from the dossier. It
    # need not carry tabular records — an illustrative custom SVG/Canvas is exactly
    # what visual_direction is for — so it must not abort the whole design.
    if clean_text(data.get("visual_direction") or data.get("visual_intent") or data.get("interpretation") or ""):
        return {
            "section_type": "chart_interpretation",
            "layout_role": f"analysis_{index + 1}_chart_interpretation",
            "rationale": "A bespoke or illustrative visual the creative author renders from its visual_direction and interpretation.",
            "data": data,
        }

    raise ValueError(
        f"analyses[{index}] ('{clean_text(data.get('title') or '')}') has no renderable shape; "
        "provide records, records+visual, records+chart, rows+columns, figure, items, metrics, findings, hypotheses, steps, groups, checks, events, or an explicit section_type"
    )


def _columns_from_records(records: list[Any]) -> list[str]:
    columns: list[str] = []
    seen: set[str] = set()
    for row in records:
        if not isinstance(row, dict):
            continue
        for key in row:
            clean_key = clean_text(key)
            if clean_key and clean_key not in seen:
                seen.add(clean_key)
                columns.append(clean_key)
    return columns


def _infer_filters(records: list[Any], chart: dict[str, Any] | None = None) -> list[dict[str, str]]:
    if not records:
        return []
    chart = chart or {}
    excluded = {
        clean_text(chart.get("x") or chart.get("x_key") or ""),
        clean_text(chart.get("y") or chart.get("y_key") or ""),
    }
    preferred = [
        clean_text(chart.get("color") or chart.get("group") or chart.get("series") or ""),
        "segment",
        "cohort",
        "category",
        "group",
        "type",
        "status",
        "region",
        "scenario",
        "stage",
    ]
    rows = [row for row in records if isinstance(row, dict)]
    candidates: list[tuple[int, str, int]] = []
    for key in _columns_from_records(rows):
        if key in excluded:
            continue
        values = [row.get(key) for row in rows if row.get(key) not in (None, "")]
        if not values or all(_is_numberish(value) for value in values):
            continue
        unique = {clean_text(value) for value in values if clean_text(value)}
        if len(unique) < 2:
            continue
        key_l = key.lower()
        priority_index = next((i for i, name in enumerate(preferred) if name and key_l == name.lower()), None)
        max_options = 32 if priority_index is not None else 16
        if len(unique) > max_options:
            continue
        priority = priority_index if priority_index is not None else 100
        candidates.append((priority, key, len(unique)))
    candidates.sort(key=lambda item: (item[0], item[2], item[1]))
    return [
        {"key": key, "label": key.replace("_", " ").title()}
        for _, key, _ in candidates[:3]
    ]


def _is_numberish(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        try:
            float(value.replace(",", ""))
        except ValueError:
            return False
        return True
    return False


QUIET_SECTION_KINDS = {
    "narrative_band", "insight_grid", "findings", "callout", "text",
    "explanation", "comparison", "entity_card_grid", "ledger_timeline",
}
TRUST_SECTION_KINDS = {"methodology_block", "hypothesis_ledger", "evidence_trace", "evidence_rail", "checklist"}
EVIDENCE_SURFACE_KINDS = VISUAL_SECTION_KINDS | INTERACTIVE_SECTION_KINDS | {"table"}


def _json_for_script(value: Any) -> str:
    return json.dumps(value, default=str).replace("</", "<\\/")


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _item_title(item: dict[str, Any], fallback: str = "Insight") -> str:
    return clean_text(
        item.get("title")
        or item.get("headline")
        or item.get("statement")
        or item.get("name")
        or fallback
    )


def _item_detail(item: dict[str, Any]) -> str:
    return clean_text(
        item.get("summary")
        or item.get("detail")
        or item.get("description")
        or item.get("rationale")
        or item.get("text")
        or item.get("body")
        or ""
    )
