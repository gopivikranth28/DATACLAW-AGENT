"""Tests for the LLM redaction helper."""

from __future__ import annotations

import copy

from dataclaw.providers.tool.llm_redact import redact_for_llm


def test_image_drops_data_keeps_summary():
    out = redact_for_llm({
        "type": "image",
        "mimetype": "image/png",
        "data": "iVBORw0KGgo" * 1000,  # huge base64 stand-in
        "summary": "<Figure size 600x400 with 1 Axes>",
    })
    assert out["type"] == "image"
    assert out["elided"] is True
    assert "data" not in out
    assert "image/png" in out["note"]
    assert out["summary"] == "<Figure size 600x400 with 1 Axes>"


def test_image_without_summary():
    out = redact_for_llm({"type": "image", "mimetype": "image/jpeg", "data": "xyz"})
    assert out["elided"] is True
    assert "summary" not in out
    assert "image/jpeg" in out["note"]


def test_html_prefers_markdown():
    out = redact_for_llm({
        "type": "html",
        "text": "<table><tr><td>a</td></tr></table>",
        "plain_text": "  a\n  1",
        "markdown": "| a |\n|---|\n| 1 |",
    })
    assert out == {"type": "markdown", "text": "| a |\n|---|\n| 1 |"}


def test_html_falls_back_to_plain_text():
    out = redact_for_llm({
        "type": "html",
        "text": "<table>...</table>",
        "plain_text": "   col\n0    1",
        "markdown": "",
    })
    assert out == {"type": "text", "text": "   col\n0    1"}


def test_html_passthrough_when_no_alt():
    inp = {"type": "html", "text": "<table>only</table>"}
    out = redact_for_llm(inp)
    # No markdown / plain_text → leave as-is so the LLM still sees something.
    assert out == {"type": "html", "text": "<table>only</table>"}


def test_recurses_into_outputs_list():
    inp = {
        "cell_index": 3,
        "outputs": [
            {"type": "image", "mimetype": "image/png", "data": "AAA", "summary": "fig"},
            {"type": "html", "text": "<table>", "markdown": "| x |"},
            {"type": "text", "text": "hello"},
        ],
        "error": None,
    }
    out = redact_for_llm(inp)
    assert out["cell_index"] == 3
    assert out["error"] is None
    assert len(out["outputs"]) == 3
    assert "data" not in out["outputs"][0]
    assert out["outputs"][1] == {"type": "markdown", "text": "| x |"}
    assert out["outputs"][2] == {"type": "text", "text": "hello"}


def test_unknown_types_passthrough():
    cases = [
        {"type": "text", "text": "hi"},
        {"type": "error", "text": "boom"},
        {"type": "markdown", "text": "# already md"},
        {"foo": "bar"},  # no type
    ]
    for c in cases:
        assert redact_for_llm(c) == c


def test_does_not_mutate_input():
    inp = {
        "outputs": [
            {"type": "image", "mimetype": "image/png", "data": "AAA", "summary": "s"},
            {"type": "html", "text": "<t>", "markdown": "| md |"},
        ]
    }
    snapshot = copy.deepcopy(inp)
    _ = redact_for_llm(inp)
    assert inp == snapshot


def test_scalars_passthrough():
    assert redact_for_llm("hello") == "hello"
    assert redact_for_llm(42) == 42
    assert redact_for_llm(None) is None
    assert redact_for_llm([1, 2, 3]) == [1, 2, 3]


def test_nested_list_of_dicts():
    inp = [
        {"type": "image", "mimetype": "image/png", "data": "x"},
        [{"type": "html", "text": "<t>", "markdown": "| a |"}],
    ]
    out = redact_for_llm(inp)
    assert out[0]["elided"] is True
    assert out[1][0] == {"type": "markdown", "text": "| a |"}
