"""Evidence-bound runtime visual author for storyboard-backed reports.

The visual author is deliberately not an HTML generator.  It lets an LLM make
editorial choices at report-build time while keeping claims, text, and browser
code under deterministic control:

* the model can select only supplied fact IDs;
* it can choose from a finite visual grammar for known storyboard sections;
* the renderer materializes the selected facts and named theme tokens; and
* an invalid or unavailable model falls back to the original storyboard.

That boundary makes runtime composition useful without turning a report into an
unreviewable prompt-to-HTML artifact.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import re
from typing import Any

from dataclaw.providers.llm.provider import LLMProvider, TextDeltaEvent
from dataclaw.schema import Message


VISUAL_AUTHOR_SCHEMA = 1

# These are names, not arbitrary CSS supplied by a model.  The renderer uses
# them as an optional override for its existing semantic color tokens.
THEME_TOKENS: dict[str, dict[str, str]] = {
    "blue": {"accent": "#2563eb", "accent_2": "#0f766e", "accent_3": "#c2410c", "accent_soft": "#e8f0ff"},
    "ocean": {"accent": "#0369a1", "accent_2": "#0f766e", "accent_3": "#b45309", "accent_soft": "#e0f2fe"},
    "forest": {"accent": "#166534", "accent_2": "#0f766e", "accent_3": "#b45309", "accent_soft": "#dcfce7"},
    "plum": {"accent": "#6d28d9", "accent_2": "#0f766e", "accent_3": "#c2410c", "accent_soft": "#f3e8ff"},
    "slate": {"accent": "#334155", "accent_2": "#0f766e", "accent_3": "#b45309", "accent_soft": "#e2e8f0"},
}

_VALID_MODES = {"off", "runtime", "required", "provided"}
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
_MAX_DISPLAY_FACTS = {"pill": 4, "scan_point": 5, "example": 4, "annotation": 3}


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
        # Every report still receives the renderer's bounded desktop/editorial
        # visual system.  Runtime authoring is opt-in because an LLM must not
        # become a prerequisite for a reproducible report; expose the default
        # in the receipt so "off" cannot be mistaken for an unstyled fallback.
        return {"mode": "off", "baseline": "deterministic_desktop_editorial"}
    if not isinstance(supplied, dict):
        raise ValueError("visual_author must be a dictionary when supplied")
    config = copy.deepcopy(supplied)
    mode = _clean(config.get("mode") or "runtime").lower().replace("-", "_")
    if mode not in _VALID_MODES:
        raise ValueError("visual_author.mode must be 'off', 'runtime', 'required', or 'provided'")
    config["mode"] = mode
    facts = config.get("facts", config.get("source_facts", []))
    if facts is not None and not isinstance(facts, list):
        raise ValueError("visual_author.facts must be a list when supplied")
    config["timeout_seconds"] = _bounded_int(
        config.get("timeout_seconds"),
        default=_DEFAULT_TIMEOUT_SECONDS,
        minimum=1,
        maximum=60,
        field="visual_author.timeout_seconds",
    )
    config["max_output_chars"] = _bounded_int(
        config.get("max_output_chars"),
        default=_DEFAULT_MAX_OUTPUT_CHARS,
        minimum=512,
        maximum=50_000,
        field="visual_author.max_output_chars",
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
        if capability is None:
            continue
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

    facts = _collect_facts(storyboard, config, {entry["section_id"] for entry in sections}, insight_targets)
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
    }


def build_visual_author_prompt(catalog: dict[str, Any]) -> tuple[str, str]:
    """Return the instruction and data prompt for the runtime visual author."""
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


async def author_report_visuals(
    storyboard: dict[str, Any],
    *,
    config: dict[str, Any] | None = None,
    llm: LLMProvider | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run the optional runtime visual-author stage and materialize valid output.

    Runtime and required mode fail safe: ``runtime`` preserves the unmodified
    storyboard on an unavailable model, malformed JSON, or invalid selection.
    ``required`` raises after recording enough context for the caller to make
    the failure visible rather than silently publishing a fallback.
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

    return {
        "schema": VISUAL_AUTHOR_SCHEMA,
        **({"theme": theme} if theme else {}),
        "sections": sections_out,
        "insights": insights_out,
        **({"composition": composition_out} if composition_out else {}),
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
                "chart", "chart_interpretation", "filterable_chart", "chart_table_explorer",
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
    if section_type in {"chart", "chart_interpretation", "filterable_chart", "chart_table_explorer", "interactive_table", "table", "selector_panel"}:
        return {"surfaces": ["strong", "evidence"], "evidence_presentations": sorted(_VALID_CHART_EVIDENCE)}
    if section_type == "evidence_trace":
        return {"surfaces": ["trust"], "evidence_presentations": sorted(_VALID_TRACE_EVIDENCE)}
    if section_type in {"methodology_block", "hypothesis_ledger", "evidence_rail", "ledger_timeline"}:
        return {"surfaces": ["trust"]}
    if section_type in {"metric_row", "narrative_band", "findings", "entity_card_grid", "comparison", "checklist", "explanation", "text", "callout"}:
        return {"surfaces": ["quiet"]}
    return None


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


def _stable_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
