"""Build the WC26 knockout forecast as a bracket-led editorial report."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins" / "dataclaw-workspace"))

from dataclaw_workspace.config import WorkspaceConfig
from dataclaw_workspace.tools import report_design_report, set_project_dir


EVIDENCE_TARGETS = [
    {"id": "107a7edd", "kind": "notebook_cell", "present": True},
    {"id": "619ffc96", "kind": "notebook_cell", "present": True},
    {"id": "9b179d06", "kind": "notebook_cell", "present": True},
    {"id": "43e7adc8", "kind": "notebook_cell", "present": True},
    {"id": "429dd2e6", "kind": "notebook_cell", "present": True},
    {"id": "0e270c31", "kind": "notebook_cell", "present": True},
    {"id": "fd3095fb", "kind": "notebook_cell", "present": True},
    {"id": "840be5bd", "kind": "notebook_cell", "present": True},
    {"id": "find-two-horse", "kind": "finding", "present": True, "source": "report_section"},
    {"id": "find-france", "kind": "finding", "present": True, "source": "report_section"},
    {"id": "find-eng-nor", "kind": "finding", "present": True, "source": "report_section"},
    {"id": "find-underdogs", "kind": "finding", "present": True, "source": "report_section"},
    {"id": "find-model", "kind": "finding", "present": True, "source": "report_section"},
]


def evidence(*refs: str) -> list[dict[str, str]]:
    return [{"kind": "notebook_cell", "ref": ref} for ref in refs]


def bracket_figure() -> dict[str, Any]:
    """Return the most likely tournament path as a readable knockout bracket."""
    neutral = "#94a3b8"
    favourite = "#0f766e"
    line_width = 2.1
    shapes: list[dict[str, Any]] = []

    def line(x0: float, y0: float, x1: float, y1: float, color: str = neutral) -> None:
        shapes.append({
            "type": "line",
            "x0": x0,
            "y0": y0,
            "x1": x1,
            "y1": y1,
            "line": {"color": color, "width": line_width},
        })

    # Four quarter-final pairings converge into two semi-finals, then the final.
    for top, bottom, next_y in ((8, 7, 7.5), (6, 5, 5.5), (4, 3, 3.5), (2, 1, 1.5)):
        line(0.05, top, 0.45, top)
        line(0.05, bottom, 0.45, bottom)
        line(0.45, bottom, 0.45, top)
        line(0.45, next_y, 1.0, next_y, favourite)
    for top, bottom, next_y in ((7.5, 5.5, 6.5), (3.5, 1.5, 2.5)):
        line(1.0, top, 1.45, top, favourite)
        line(1.0, bottom, 1.45, bottom, favourite)
        line(1.45, bottom, 1.45, top, favourite)
        line(1.45, next_y, 2.0, next_y, favourite)
    line(2.0, 6.5, 2.4, 6.5, favourite)
    line(2.0, 2.5, 2.4, 2.5, favourite)
    line(2.4, 2.5, 2.4, 6.5, favourite)
    line(2.4, 4.5, 3.12, 4.5, favourite)

    def label(x: float, y: float, text: str, *, color: str | None = None, size: int = 12) -> dict[str, Any]:
        return {
            "x": x,
            "y": y,
            "text": text,
            "showarrow": False,
            "xanchor": "left",
            "yanchor": "middle",
            "align": "left",
            "font": {"size": size, **({"color": color} if color else {})},
        }

    annotations = [
        {"x": 0, "y": 1.08, "xref": "x", "yref": "paper", "text": "<b>QUARTER-FINALS</b>", "showarrow": False, "font": {"size": 11}},
        {"x": 1, "y": 1.08, "xref": "x", "yref": "paper", "text": "<b>SEMI-FINALS</b>", "showarrow": False, "font": {"size": 11}},
        {"x": 2, "y": 1.08, "xref": "x", "yref": "paper", "text": "<b>FINAL</b>", "showarrow": False, "font": {"size": 11}},
        {"x": 3.2, "y": 1.08, "xref": "x", "yref": "paper", "text": "<b>CHAMPION</b>", "showarrow": False, "font": {"size": 11}},
        label(-0.02, 8, "<b>France 73%</b>", color=favourite),
        label(-0.02, 7, "Morocco 27%"),
        label(-0.02, 6, "<b>Spain 79%</b>", color=favourite),
        label(-0.02, 5, "Belgium 21%"),
        label(-0.02, 4, "Norway 24%"),
        label(-0.02, 3, "<b>England 76%</b>", color=favourite),
        label(-0.02, 2, "<b>Argentina 81%</b>", color=favourite),
        label(-0.02, 1, "Switzerland 19%"),
        label(1.04, 7.5, "France 42%"),
        label(1.04, 5.5, "<b>Spain 58%</b>", color=favourite),
        label(1.04, 3.5, "England 36%"),
        label(1.04, 1.5, "<b>Argentina 64%</b>", color=favourite),
        label(2.04, 6.5, "<b>Spain</b>"),
        label(2.04, 2.5, "<b>Argentina</b>"),
        label(2.46, 4.5, "<b>Spain 57%</b>", color=favourite, size=13),
        label(3.16, 4.5, "🏆 <b>SPAIN</b>", color=favourite, size=14),
    ]
    return {
        "data": [{
            "type": "scatter",
            "mode": "markers",
            "x": [0, 1, 2, 3],
            "y": [1, 2, 3, 4],
            "marker": {"size": 1, "opacity": 0},
            "hoverinfo": "skip",
        }],
        "layout": {
            "height": 500,
            "margin": {"l": 8, "r": 28, "t": 44, "b": 12},
            "showlegend": False,
            "hovermode": False,
            "xaxis": {"visible": False, "range": [-0.15, 3.78], "fixedrange": True},
            "yaxis": {"visible": False, "range": [0.45, 8.8], "fixedrange": True},
            "shapes": shapes,
            "annotations": annotations,
        },
    }


def report_payload() -> dict[str, Any]:
    insights = [
        {
            "finding_id": "find-two-horse",
            "story_role": "thesis",
            "title": "Spain is the marginal favourite in a genuine two-horse race",
            "detail": "Spain wins the title in 32% of simulations, narrowly ahead of Argentina at 28%. Their 90% bootstrap intervals overlap heavily, so Spain is the pick—but not a dominant favourite.",
            "pills": [
                {"label": "Spain 32%", "tone": "accent", "color": "#0f766e"},
                {"label": "Argentina 28%", "tone": "neutral"},
            ],
            "bullets": [
                "Spain's 90% title interval is 26–38%.",
                "Argentina's 90% title interval is 21–38%.",
            ],
            "display_facts": [
                {"fact_id": "spain-title", "text": "Spain 32%", "uses": ["pill"], "evidence": "fd3095fb"},
                {"fact_id": "argentina-title", "text": "Argentina 28%", "uses": ["pill"], "evidence": "fd3095fb"},
                {"fact_id": "spain-interval", "text": "Spain's 90% title interval is 26–38%.", "uses": ["scan_point"], "evidence": "fd3095fb"},
                {"fact_id": "argentina-interval", "text": "Argentina's 90% title interval is 21–38%.", "uses": ["scan_point"], "evidence": "fd3095fb"},
            ],
            "status": "caution",
            "caveat": "A single knockout upset can reshape the run; Spain's 26–38% interval overlaps Argentina's 21–38%.",
            "evidence": evidence("fd3095fb", "0e270c31"),
        },
        {
            "finding_id": "find-france",
            "title": "France has the clearest outside path—and a hard ceiling",
            "detail": "France is 73% to clear Morocco, but the likely semi-final is a 58–42 Spain edge. It is the clear third favourite, not a co-favourite for the title.",
            "pills": [
                {"label": "73% to beat Morocco", "tone": "accent", "color": "#2563eb"},
                {"label": "58–42 Spain semi-final edge", "tone": "neutral"},
            ],
            "bullets": [
                "France is the clear third title contender.",
                "Its likely semi-final is the ceiling on the path.",
            ],
            "display_facts": [
                {"fact_id": "france-quarter", "text": "73% to beat Morocco", "uses": ["pill"], "evidence": "9b179d06"},
                {"fact_id": "france-semi", "text": "58–42 Spain semi-final edge", "uses": ["pill", "scan_point"], "evidence": "43e7adc8"},
                {"fact_id": "france-third", "text": "France is the clear third title contender.", "uses": ["scan_point"], "evidence": "9b179d06"},
            ],
            "status": "validated",
            "caveat": "This relies on the inferred France–Spain semi-final linkage in the reconstructed bracket.",
            "evidence": evidence("9b179d06", "43e7adc8"),
        },
        {
            "finding_id": "find-eng-nor",
            "title": "England, not in-form Norway, is the QF3 call",
            "detail": "Norway brings the hottest attack after knocking out Brazil, but England's stronger underlying squad and Elo make it a 76% favourite to advance.",
            "pills": [
                {"label": "England 76%", "tone": "accent", "color": "#2563eb"},
                {"label": "Norway title chance 0.7%", "tone": "neutral"},
            ],
            "bullets": [
                "Norway carries the hotter recent attack.",
                "England keeps the stronger underlying squad signal.",
            ],
            "display_facts": [
                {"fact_id": "england-quarter", "text": "England 76%", "uses": ["pill"], "evidence": "107a7edd"},
                {"fact_id": "norway-title", "text": "Norway title chance 0.7%", "uses": ["pill", "annotation"], "evidence": "619ffc96"},
                {"fact_id": "england-signal", "text": "England keeps the stronger underlying squad signal.", "uses": ["scan_point"], "evidence": "107a7edd"},
            ],
            "status": "validated",
            "caveat": "Norway remains a live one-match upset risk despite only a 0.7% title chance.",
            "evidence": evidence("107a7edd", "619ffc96"),
        },
        {
            "finding_id": "find-underdogs",
            "title": "The longshots are alive—but need multiple upsets",
            "detail": "Morocco and Belgium can win their quarters, yet each needs two more victories against elite opponents. Switzerland and Norway face the same structural problem.",
            "pills": [
                {"label": "Four longshots", "tone": "neutral"},
                {"label": "Multiple upsets required", "tone": "warn"},
            ],
            "bullets": [
                "Morocco and Belgium can each win their quarter-final.",
                "Every longshot still needs a sequence of elite wins.",
            ],
            "display_facts": [
                {"fact_id": "longshot-count", "text": "Four longshots", "uses": ["pill"], "evidence": "fd3095fb"},
                {"fact_id": "upset-sequence", "text": "Multiple upsets required", "uses": ["pill", "scan_point"], "evidence": "fd3095fb"},
                {"fact_id": "longshot-path", "text": "Every longshot still needs a sequence of elite wins.", "uses": ["scan_point"], "evidence": "fd3095fb"},
            ],
            "status": "caution",
            "caveat": "Longshot title probabilities are the least stable across bootstrap resamples.",
            "evidence": evidence("fd3095fb"),
        },
        {
            "finding_id": "find-model",
            "story_role": "trust",
            "title": "In-tournament form improves on Elo-only",
            "detail": "Adding attack, defence, and xG form lowers three-way log loss from 0.833 to 0.797 across the 96 completed matches, with 67.7% outcome accuracy.",
            "pills": [
                {"label": "Log loss −0.036", "tone": "accent", "color": "#15803d"},
                {"label": "67.7% outcome accuracy", "tone": "good"},
            ],
            "bullets": [
                "The comparison covers 96 completed matches.",
                "Calibration remains in-sample.",
            ],
            "display_facts": [
                {"fact_id": "log-loss-lift", "text": "Log loss −0.036", "uses": ["pill"], "evidence": "0e270c31"},
                {"fact_id": "accuracy", "text": "67.7% outcome accuracy", "uses": ["pill"], "evidence": "619ffc96"},
                {"fact_id": "calibration-caveat", "text": "Calibration remains in-sample.", "uses": ["annotation"], "evidence": "0e270c31"},
            ],
            "status": "confirmed",
            "caveat": "Calibration is in-sample on completed matches.",
            "evidence": evidence("0e270c31", "619ffc96"),
        },
    ]

    championship_odds = [
        {"team": "Spain", "reach_semi": 78.7, "reach_final": 50.1, "title": 32.0},
        {"team": "Argentina", "reach_semi": 80.8, "reach_final": 56.6, "title": 28.3},
        {"team": "France", "reach_semi": 73.5, "reach_final": 35.6, "title": 20.6},
        {"team": "England", "reach_semi": 76.0, "reach_final": 31.6, "title": 12.0},
        {"team": "Belgium", "reach_semi": 21.3, "reach_final": 7.1, "title": 2.5},
        {"team": "Morocco", "reach_semi": 26.5, "reach_final": 7.2, "title": 2.4},
        {"team": "Switzerland", "reach_semi": 19.2, "reach_final": 7.3, "title": 1.5},
        {"team": "Norway", "reach_semi": 24.0, "reach_final": 4.6, "title": 0.7},
    ]

    predictions = [
        {"round": "Quarter-final 1", "matchup": "France v Morocco", "favourite": "France", "advance_probability": "73%", "expected_score": "1.7–0.9"},
        {"round": "Quarter-final 2", "matchup": "Spain v Belgium", "favourite": "Spain", "advance_probability": "79%", "expected_score": "1.9–0.8"},
        {"round": "Quarter-final 3", "matchup": "Norway v England", "favourite": "England", "advance_probability": "76%", "expected_score": "1.0–2.1"},
        {"round": "Quarter-final 4", "matchup": "Argentina v Switzerland", "favourite": "Argentina", "advance_probability": "81%", "expected_score": "2.1–0.8"},
        {"round": "Semi-final 1", "matchup": "France v Spain", "favourite": "Spain", "advance_probability": "58%", "expected_score": "1.0–1.3"},
        {"round": "Semi-final 2", "matchup": "England v Argentina", "favourite": "Argentina", "advance_probability": "64%", "expected_score": "1.1–1.7"},
        {"round": "Final", "matchup": "Spain v Argentina", "favourite": "Spain", "advance_probability": "57%", "expected_score": "1.3–1.1"},
        {"round": "Third-place", "matchup": "France v England", "favourite": "France", "advance_probability": "63%", "expected_score": "1.6–1.1"},
    ]

    analyses = [
        {
            "section_type": "chart_interpretation",
            "visual_author_section_id": "knockout_path",
            "story_role": "decision_path",
            "editorial_role": "hero",
            "kicker": "The predicted bracket",
            "title": "The predicted bracket",
            "caption": "The modal path through the remaining eight matches. Percentages are the model's advance probability for the named team in each tie—not a certainty that the matchup occurs.",
            "data_note": "Bracket pairs and semi-final linkage follow the reconstructed Round-of-16 adjacency; all remaining matches are modelled at neutral venues.",
            "figure": bracket_figure(),
            "interpretation": "The forecast's centre of gravity is clear: Spain and Argentina are expected to meet in the final. The pivotal pre-final tie is Spain–France, where the edge is only 58–42.",
            "caveat": "This is the most likely route, not a deterministic bracket. The championship odds below integrate every simulated path.",
            "display_facts": [
                {"fact_id": "likely-final", "text": "Spain and Argentina are expected to meet in the final.", "uses": ["scan_point"], "evidence": "43e7adc8"},
                {"fact_id": "pivotal-semi", "text": "Spain–France is only a 58–42 edge.", "uses": ["pill", "annotation"], "evidence": "43e7adc8"},
            ],
            "evidence": evidence("43e7adc8"),
        },
        {
            "section_type": "chart_table_explorer",
            "visual_author_section_id": "championship_race",
            "story_role": "outcome_race",
            "title": "Spain and Argentina separate from the field—but not from each other",
            "caption": "Chance of reaching the semi-final, the final, and lifting the trophy. 90% bootstrap title intervals: Spain 26–38%, Argentina 21–38%, France 15–27%, England 8–15%.",
            "records": championship_odds,
            "chart": {"type": "bar", "x": "team", "y": "title", "y_label": "Title probability (%)", "x_label": "Team", "sort": "value"},
            "columns": ["team", "reach_semi", "reach_final", "title"],
            "search": False,
            "interpretation": "Spain and Argentina are the only genuine championship co-favourites. France and England form a chasing pair; the remaining four need a sequence of upsets.",
            "display_facts": [
                {"fact_id": "co-favourites", "text": "Spain and Argentina are the only genuine championship co-favourites.", "uses": ["scan_point"], "evidence": "fd3095fb"},
                {"fact_id": "spain-band", "text": "Spain 26–38% 90% title interval", "uses": ["pill"], "evidence": "fd3095fb"},
            ],
            "evidence": evidence("9b179d06", "fd3095fb"),
        },
        {
            "section_type": "comparison",
            "visual_author_section_id": "final_mechanism",
            "story_role": "mechanism",
            "title": "Why Spain edges higher-Elo Argentina",
            "caption": "Argentina begins with the higher raw rating. Spain's tournament defence is the form signal that changes the final call.",
            "groups": [
                {
                    "title": "Spain",
                    "detail": "The model's marginal final favourite.",
                    "metrics": {
                        "Pre-tournament Elo": "Lower",
                        "Defensive form": "0.85× expected goals",
                        "Projected final": "57% win",
                        "Expected score": "1.3 goals",
                    },
                },
                {
                    "title": "Argentina",
                    "detail": "Higher raw rating, but a less favourable defensive form signal.",
                    "metrics": {
                        "Pre-tournament Elo": "Higher",
                        "Defensive form": "1.14× expected goals",
                        "Projected final": "43% win",
                        "Expected score": "1.1 goals",
                    },
                },
            ],
            "data_note": "Defensive form is estimated from each survivor's five tournament matches and shrunk toward the Elo baseline.",
            "display_facts": [
                {"fact_id": "spain-final-edge", "text": "Spain 57% projected final win", "uses": ["pill"], "evidence": "840be5bd"},
                {"fact_id": "defensive-form", "text": "Spain's 0.85× expected-goals defensive form changes the final call.", "uses": ["scan_point"], "evidence": "107a7edd"},
            ],
            "evidence": evidence("107a7edd", "840be5bd"),
        },
        {
            "section_type": "chart_table_explorer",
            "visual_author_section_id": "final_distribution",
            "story_role": "outcome_distribution",
            "title": "A tight, low-scoring final explains the thin edge",
            "caption": "Most likely scorelines in a Spain–Argentina final (Spain listed first). A 1–1 draw or a 1–0 Spain win is the modal outcome.",
            "records": [
                {"scoreline": "1–1", "probability": 12.9},
                {"scoreline": "1–0", "probability": 11.8},
                {"scoreline": "0–1", "probability": 9.7},
                {"scoreline": "0–0", "probability": 8.9},
                {"scoreline": "2–1", "probability": 8.5},
                {"scoreline": "2–0", "probability": 7.8},
                {"scoreline": "1–2", "probability": 7.1},
                {"scoreline": "0–2", "probability": 5.3},
            ],
            "chart": {"type": "bar", "x": "scoreline", "y": "probability", "y_label": "Probability (%)", "x_label": "Scoreline", "sort": "value"},
            "columns": ["scoreline", "probability"],
            "search": False,
            "interpretation": "Spain wins 42% in regulation, Argentina 31%, and 27% reaches extra time or penalties—where Spain remains marginally favoured. The final is close by construction, not a coronation.",
            "display_facts": [
                {"fact_id": "modal-scoreline", "text": "1–1 is the modal scoreline at 12.9%.", "uses": ["pill", "scan_point"], "evidence": "840be5bd"},
                {"fact_id": "extra-time", "text": "27% reaches extra time or penalties.", "uses": ["annotation"], "evidence": "840be5bd"},
            ],
            "evidence": evidence("840be5bd"),
        },
        {
            "section_type": "interactive_table",
            "visual_author_section_id": "forecast_lookup",
            "story_role": "complete_lookup",
            "title": "All eight predictions",
            "caption": "The complete reference table: fixture, favourite, advance probability, and expected scoreline for every remaining match.",
            "rows": predictions,
            "columns": ["round", "matchup", "favourite", "advance_probability", "expected_score"],
            "page_size": 12,
            "search": True,
            "data_note": "The bracket is the guided view; use this searchable table when you need a specific forecast.",
            "evidence": evidence("43e7adc8"),
        },
    ]

    requirements = {
        "editorial_archetype": "path_dependent_forecast",
        "presentation": {
            "insight_layout": "editorial_list",
            "insight_evidence": "linked",
            "evidence_trace": "disclosure",
            "require_display_facts": True,
        },
        "publication": {"require_visual_review": True},
        "kicker": "WC26 · Knockout forecast",
        "hero_title": "Spain has the best chance of lifting the trophy—but only just.",
        "metrics": [
            {"label": "Spain title", "value": "32%"},
            {"label": "Argentina title", "value": "28%"},
            {"label": "Spain wins projected final", "value": "57%"},
        ],
        "pivotal_title": "The ties that could break the forecast",
        "pivotal_caption": "The matchups with enough tension to reroute the most likely path.",
        "methodology_title": "Why trust the model?",
        "methodology": [
            {"title": "Grain", "detail": "Team-match level; each survivor contributes five completed matches across the group stage, Round of 32, and Round of 16."},
            {"title": "Strength model", "detail": "Pre-tournament Elo is calibrated to expected goals, then blended with in-tournament attack and defence form (0.65 xG + 0.35 goals) using K=3 pseudo-match shrinkage."},
            {"title": "Match model", "detail": "Independent Poisson goal rates simulate each tie; knockout draws resolve through an extra-time/penalty tiebreak weighted to the stronger side."},
            {"title": "Validation", "detail": "The form-adjusted model records 0.797 three-way log loss versus 0.833 for Elo-only and 67.7% outcome accuracy across 96 completed matches."},
            {"title": "Simulation", "detail": "20,000 Monte Carlo tournaments are cross-checked against exact analytic bracket propagation (Spain 32.0% analytic vs 32.5% Monte Carlo)."},
            {"title": "Uncertainty & assumptions", "detail": "90% block-bootstrap intervals quantify title uncertainty. Spain–Belgium, Argentina–Switzerland, and semi-final linkage are inferred from Round-of-16 adjacency; a formal alternate-pairing sensitivity is not supplied."},
        ],
        "checks": [
            {"title": "No raw full dataset embedded", "status": "pass"},
            {"title": "Analytic bracket agrees with Monte Carlo", "status": "pass"},
            {"title": "Form-adjusted model compared with Elo-only baseline", "status": "pass"},
        ],
        "evidence_registry": {"targets": EVIDENCE_TARGETS},
        "analysis_review": {
            "mode": "predictive",
            "baseline": {
                "status": "complete",
                "method": "Shared completed-match three-way log loss against Elo-only",
                "result": "Form-adjusted model: 0.797; Elo-only baseline: 0.833.",
                "evidence": {"kind": "notebook_cell", "ref": "0e270c31"},
            },
            "uncertainty": {"status": "complete", "method": "Block bootstrap", "result": "90% title intervals"},
            "assumptions": ["Two quarter-final pairings and semi-final linkage are inferred from Round-of-16 adjacency."],
            "sensitivity": {"status": "not_run", "summary": "No alternate-pairing sensitivity is supplied; the inferred-bracket assumption is disclosed."},
            "decision_path": {"status": "complete", "summary": "Projected knockout bracket"},
            "outcome_distribution": {"status": "complete", "summary": "Spain–Argentina scoreline distribution"},
            "export_runtime": "local",
        },
        "footer_note": "Forecasts are conditional on the reconstructed bracket, neutral venues, and the model assumptions documented above. The evidence trace preserves the completed analysis references behind each claim.",
    }
    return {"insights": insights, "analyses": analyses, "requirements": requirements}


async def build(
    *,
    llm: Any | None = None,
    visual_author: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build from the recipe; callers may supply the runtime visual editor.

    Direct script execution remains deterministic because this repository does
    not configure a provider itself. A host can pass its configured LLM and use
    the evidence-bound runtime visual author without changing the analytical
    source facts or the report recipe.
    """
    set_project_dir(ROOT)
    payload = report_payload()
    return await report_design_report(
        cfg=WorkspaceConfig(),
        report_goal="WC26 Knockout Forecast · Quarter-finals to Champion",
        title="WC26 Knockout Forecast — Quarter-finals to Champion",
        audience="Football followers and decision-makers who need the forecast before its method.",
        report_path="docs/wc26_knockout_forecast.html",
        storyboard_path="docs/wc26_knockout_forecast.storyboard.json",
        quality_gate="fail",
        visual_author=visual_author,
        llm=llm,
        **payload,
    )


async def main() -> None:
    result = await build()
    print(json.dumps({
        "html_path": result["html_path"],
        "storyboard_path": result["storyboard_path"],
        "quality": result["quality"],
        "design_review": result["design_review"],
        "analytical_review": result["analytical_review"],
    }, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
