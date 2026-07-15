"""D3/D4 design-variance features: note callouts, split pairs, seeded themes.

docs/report-design-variance.md: deterministic craft must vary output without
any model in the loop, inside contrast-validated bounds.
"""

from dataclaw_workspace.report_renderer import (
    _seeded_visual_theme,
    render_report_from_storyboard,
    render_report_section,
    typed_report_section,
)
from dataclaw_workspace.visual_author import THEME_TOKENS


def _storyboard(title: str, *, theme: dict | None = None) -> dict:
    storyboard = {
        "title": title,
        "report_goal": f"Explain the completed analysis behind {title}.",
        "section_plan": [
            {"section_type": "header", "data": {"title": title, "subtitle": "Completed analysis."}},
            {"section_type": "narrative_band", "data": {"heading": "The answer", "body": "The supplied answer."}},
        ],
    }
    if theme:
        storyboard["visual_theme"] = theme
    return storyboard


def test_callout_note_variant_renders_tinted_aside():
    data = {
        "title": "Method note",
        "body": "Clustering was blind to position, rating, and value.",
        "layout_variant": "note",
        "tone": "warn",
    }
    html = render_report_section("callout", data, typed_report_section("callout", data))

    assert "r-callout-note" in html
    assert "is-tone-warn" in html


def test_callout_without_variant_keeps_the_classic_treatment():
    data = {"title": "Note", "body": "Plain callout."}
    html = render_report_section("callout", data, typed_report_section("callout", data))

    assert 'class="r-callout"' in html
    assert "r-callout-note" not in html


def test_layout_group_ratio_renders_asymmetric_pair():
    storyboard = _storyboard("Split pair")
    storyboard["section_plan"].extend([
        {
            "section_type": "callout",
            "layout_group": "pair-1",
            "layout_group_ratio": "60-40",
            "data": {"title": "Wide side", "body": "Main exhibit."},
        },
        {
            "section_type": "callout",
            "layout_group": "pair-1",
            "data": {"title": "Narrow side", "body": "Companion."},
        },
    ])

    html = render_report_from_storyboard(storyboard)

    assert 'class="r-diagnostic-pair is-split-60-40"' in html


def test_seeded_theme_is_deterministic_and_valid():
    first = _seeded_visual_theme(_storyboard("Formula 1 economics"))
    again = _seeded_visual_theme(_storyboard("Formula 1 economics"))
    other = _seeded_visual_theme(_storyboard("Customer retention"))

    assert first == again
    assert first["name"] in THEME_TOKENS
    assert other["name"] in THEME_TOKENS
    assert first["source"] == "seeded"


def test_render_applies_seeded_theme_only_when_none_is_set():
    seeded_html = render_report_from_storyboard(_storyboard("Formula 1 economics"))
    assert 'data-dc-visual-theme="' in seeded_html

    explicit = _storyboard("Formula 1 economics", theme={"name": "plum"})
    explicit_html = render_report_from_storyboard(explicit)
    assert 'data-dc-visual-theme="plum"' in explicit_html
    assert explicit["visual_theme"]["name"] == "plum"


def test_uppercase_theme_names_still_match_their_css_override():
    html = render_report_from_storyboard(_storyboard("Case check", theme={"name": "Plum"}))

    assert 'data-dc-visual-theme="plum"' in html
    assert ':root[data-dc-visual-theme="plum"]' in html
