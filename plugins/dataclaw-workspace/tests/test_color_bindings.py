"""Semantic color bindings — recurring entities keep one color everywhere.

docs/report-design-variance.md, D1: an entity appearing in two or more
sections is bound to a stable categorical palette slot; entity cards and
chart traces that name it render in the same hue.
"""

from dataclaw_workspace.report_renderer import (
    COLOR_BINDINGS_ATTR,
    _apply_color_bindings_to_plan,
    _build_color_bindings,
    render_report_from_storyboard,
)


def _chart_section(*trace_names: str) -> dict:
    return {
        "section_type": "chart",
        "data": {
            "title": "Chart of " + ", ".join(trace_names),
            "figure": {"data": [{"type": "bar", "name": name, "x": ["a"], "y": [1]} for name in trace_names]},
        },
    }


def _entity_section(*titles: str) -> dict:
    return {
        "section_type": "entity_card_grid",
        "data": {
            "title": "Entities",
            "items": [{"title": title, "detail": f"About {title}."} for title in titles],
        },
    }


def test_entities_recurring_across_sections_get_stable_slots():
    plan = [
        _entity_section("Elite Goalscorer", "Support Striker"),
        _chart_section("Elite Goalscorer", "One-Off Series"),
        _chart_section("Support Striker", "Elite Goalscorer"),
    ]

    bindings = _build_color_bindings(plan)

    by_label = {entry["label"]: entry for entry in bindings["assignments"]}
    assert set(by_label) == {"Elite Goalscorer", "Support Striker"}
    # Slots follow first appearance and are 1-indexed onto --dc-cat-N.
    assert by_label["Elite Goalscorer"]["slot"] == 1
    assert by_label["Support Striker"]["slot"] == 2
    assert by_label["Elite Goalscorer"]["sections"] == [0, 1, 2]
    # Single-section labels never earn a binding: color only carries meaning.
    assert all(entry["label"] != "One-Off Series" for entry in bindings["assignments"])


def test_binding_matching_is_case_insensitive_and_skips_numeric_labels():
    plan = [
        _chart_section("ELITE goalscorer", "2024"),
        _entity_section("Elite Goalscorer"),
        _chart_section("2024"),
    ]

    bindings = _build_color_bindings(plan)

    assert [entry["key"] for entry in bindings["assignments"]] == ["elite goalscorer"]


def test_slots_are_capped_to_the_palette_and_overflow_is_recorded():
    names = [f"Entity {chr(ord('A') + i)}" for i in range(10)]
    plan = [_chart_section(*names), _entity_section(*names)]

    bindings = _build_color_bindings(plan)

    assert len(bindings["assignments"]) == 8
    assert len(bindings["unbound"]) == 2


def test_apply_decorates_unstyled_entity_cards_only():
    plan = [
        _entity_section("Elite Goalscorer", "Support Striker"),
        _chart_section("Elite Goalscorer", "Support Striker"),
    ]
    plan[0]["data"]["items"][1]["accent_color"] = "#123456"

    _apply_color_bindings_to_plan(plan, _build_color_bindings(plan))

    items = plan[0]["data"]["items"]
    assert items[0]["accent_color"] == "var(--dc-cat-1)"
    assert items[1]["accent_color"] == "#123456"


def test_render_embeds_bindings_and_stores_them_on_the_storyboard():
    storyboard = {
        "title": "Bound colors",
        "report_goal": "Explain the completed comparison.",
        "section_plan": [
            {"section_type": "header", "data": {"title": "Bound colors", "subtitle": "Two entities."}},
            _entity_section("Elite Goalscorer", "Support Striker"),
            _chart_section("Elite Goalscorer", "Support Striker"),
        ],
    }

    html = render_report_from_storyboard(storyboard)

    assert f'<script type="application/json" {COLOR_BINDINGS_ATTR}>' in html
    assert "bindSemanticColors" in html
    assert 'style="--card-accent: var(--dc-cat-1)"' in html
    stored = storyboard["color_bindings"]
    assert stored["color_bindings_schema"] == 1
    assert {entry["label"] for entry in stored["assignments"]} == {"Elite Goalscorer", "Support Striker"}


def test_render_without_recurring_entities_embeds_no_binding_payload():
    storyboard = {
        "title": "No recurrence",
        "report_goal": "Explain the completed single chart.",
        "section_plan": [
            {"section_type": "header", "data": {"title": "No recurrence", "subtitle": "One chart."}},
            _chart_section("Lone Series"),
        ],
    }

    html = render_report_from_storyboard(storyboard)

    assert f'<script type="application/json" {COLOR_BINDINGS_ATTR}>' not in html
    assert storyboard["color_bindings"]["assignments"] == []
