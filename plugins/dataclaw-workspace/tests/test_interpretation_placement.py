"""Interpretation placement — layout follows the content's shape.

docs/report-design-variance.md, D2: one short sentence reads as a caption,
discrete takeaways read as a numbered panel, a fact with coordinates is drawn
inside the figure, and only long-form reading earns the labeled side rail.
"""

import json
import re

from dataclaw_workspace.report_renderer import (
    _inject_figure_annotations,
    _interpretation_placement,
    render_report_section,
    typed_report_section,
)

FIGURE = {"data": [{"type": "bar", "x": ["A", "B"], "y": [1, 2]}]}
LONG_PROSE = (
    "Starting first converts to a win only about a third of the time, and the trend is "
    "downward: conversion has fallen steadily since the cost cap arrived, with the lowest "
    "years lining up exactly with the widest championship fields in the modern era."
)


def _render(data: dict) -> str:
    data = {"figure": FIGURE, **data}
    typed = typed_report_section("chart_interpretation", data)
    return render_report_section("chart_interpretation", data, typed)


def test_short_sentence_reads_as_caption_without_a_labeled_box():
    html = _render({"title": "Wins", "interpretation": "B doubled A."})

    assert 'class="r-caption r-interpretation-caption"' in html
    assert "r-interpretation-panel" not in html
    assert ">Interpretation<" not in html


def test_long_prose_earns_the_side_rail():
    html = _render({"title": "Poles", "interpretation": LONG_PROSE})

    assert ">Interpretation<" in html
    assert "r-interpretation-panel" in html


def test_supporting_context_forces_the_rail_even_for_short_prose():
    html = _render({
        "title": "Wins",
        "interpretation": "B doubled A.",
        "caveat": "Sample covers full seasons only.",
    })

    assert ">Interpretation<" in html
    assert "Caveat:" in html


def test_discrete_takeaways_render_as_a_numbered_panel():
    html = _render({
        "title": "Archetypes",
        "takeaways": [
            {"title": "Style predicts price", "detail": "Premium archetypes command a multiple."},
            "Clustering rediscovers the position lines.",
            {"detail": "The generational handover is visible at the bottom."},
        ],
    })

    assert "r-takeaway-panel" in html
    assert html.count('class="r-takeaway-index"') == 3
    assert "What this reveals" in html
    assert ">Interpretation<" not in html


def test_annotation_fact_is_drawn_into_the_figure_and_prose_demotes_to_caption():
    html = _render({
        "title": "Conversion",
        "interpretation": "Conversion fell after the cap.",
        "display_facts": [{
            "fact_id": "cap-era",
            "use": "annotation",
            "text": "Cost cap introduced",
            "axis": "x",
            "value": 2021,
        }],
    })

    match = re.search(r'config:(\{.*?\})\}\);</script>', html, re.DOTALL)
    assert match, "chart render queue payload missing"
    figure = json.loads(match.group(1).replace("<\\/", "</"))["figure"]
    annotations = figure["layout"]["annotations"]
    shapes = figure["layout"]["shapes"]
    assert any(entry.get("text") == "Cost cap introduced" for entry in annotations)
    assert any(shape.get("x0") == 2021 and shape.get("type") == "line" for shape in shapes)
    assert 'class="r-caption r-interpretation-caption"' in html
    assert ">Interpretation<" not in html


def test_explicit_placement_override_wins():
    html = _render({
        "title": "Wins",
        "interpretation": "B doubled A.",
        "interpretation_placement": "side_rail",
    })

    assert ">Interpretation<" in html


def test_explicit_caption_override_keeps_supporting_notes_visible():
    html = _render({
        "title": "Wins",
        "interpretation": "B doubled A.",
        "caveat": "Sample covers full seasons only.",
        "interpretation_placement": "caption",
    })

    assert 'class="r-caption r-interpretation-caption"' in html
    assert ">Notes<" in html
    assert "Caveat:" in html


def test_injection_is_append_only_and_respects_existing_layout_entries():
    figure = {"data": [], "layout": {"annotations": [{"text": "existing"}]}}
    injected = _inject_figure_annotations(figure, [
        {"text": "Threshold", "axis": "y", "value": 0.5, "x": None, "y": None},
    ])

    assert injected
    texts = [entry.get("text") for entry in figure["layout"]["annotations"]]
    assert texts == ["existing", "Threshold"]


def test_placement_decision_is_deterministic_from_shape():
    assert _interpretation_placement({"interpretation": "Short."}, has_supporting=False) == "caption"
    assert _interpretation_placement({"interpretation": "Short."}, has_supporting=True) == "side_rail"
    assert _interpretation_placement({"interpretation": LONG_PROSE}, has_supporting=False) == "side_rail"
    assert _interpretation_placement(
        {"takeaways": ["One thing.", "Another thing."]}, has_supporting=False
    ) == "takeaway_panel"
    assert _interpretation_placement(
        {"display_facts": [{"use": "annotation", "text": "T", "axis": "x", "value": 1}]},
        has_supporting=False,
    ) == "figure_annotation"
