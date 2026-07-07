"""Tests for chat.py session-message ↔ LLM-message conversion on reload."""

from __future__ import annotations

from dataclaw.api.routers.chat import IncomingMessage, _extract_visual_artifacts, _stored_messages_to_llm, receive_message


def _tool_call_msg(call_id: str, result: str, result_for_llm: str | None = None) -> dict:
    msg: dict = {
        "role": "tool_call",
        "messageId": f"tc-{call_id}",
        "toolCallId": call_id,
        "toolName": "execute_cell",
        "args": "{}",
        "result": result,
        "status": "complete",
    }
    if result_for_llm is not None:
        msg["result_for_llm"] = result_for_llm
    return msg


def test_stored_messages_prefer_result_for_llm():
    """When both fields are persisted, the LLM converter uses the slim one."""
    full = '{"outputs": [{"type": "image", "data": "AAA", "mimetype": "image/png"}]}'
    slim = '{"outputs": [{"type": "image", "elided": true, "note": "<image elided>"}]}'
    msgs = _stored_messages_to_llm([
        {"role": "user", "content": "go"},
        {"role": "assistant", "content": "ok"},
        _tool_call_msg("c1", result=full, result_for_llm=slim),
    ])
    # The tool_result message in the produced LLM messages must contain the
    # slim payload, not the full one with the base64.
    serialized = "\n".join(str(m) for m in msgs)
    assert "AAA" not in serialized
    assert "elided" in serialized


def test_stored_messages_fallback_to_result():
    """Legacy persisted messages without result_for_llm still feed the LLM."""
    full = '{"outputs": [{"type": "text", "text": "hello"}]}'
    msgs = _stored_messages_to_llm([
        {"role": "user", "content": "go"},
        {"role": "assistant", "content": "ok"},
        _tool_call_msg("c1", result=full),
    ])
    serialized = "\n".join(str(m) for m in msgs)
    assert "hello" in serialized


def test_empty_result_for_llm_falls_back_to_result():
    """Defensive: an empty-string result_for_llm shouldn't black-hole the LLM view."""
    full = '{"x": 1}'
    msgs = _stored_messages_to_llm([
        {"role": "user", "content": "go"},
        _tool_call_msg("c1", result=full, result_for_llm=""),
    ])
    serialized = "\n".join(str(m) for m in msgs)
    assert "{\"x\": 1}" in serialized or '"x": 1' in serialized


# ── App view layout persistence (publish route reads it from the session) ──


def test_update_session_request_accepts_app_layout():
    """appLayout must survive the PATCH model — it's how the published
    /app/<session-id> route sees the author's hide/reorder curation."""
    from dataclaw.api.routers.chat import UpdateSessionRequest

    layout = {"hidden": ["chart-1", "metric-0"], "order": ["chart-2", "chart-0"]}
    req = UpdateSessionRequest(appLayout=layout)
    updates = req.model_dump(exclude_unset=True)
    assert updates == {"appLayout": layout}


async def test_app_layout_roundtrips_through_session_storage():
    from dataclaw.storage import sessions

    created = await sessions.create_session(title="Layout test")
    layout = {"hidden": ["chart-1"], "order": ["chart-2", "chart-0", "chart-1"]}
    await sessions.update_session(created["id"], {"appLayout": layout})

    loaded = await sessions.get_session(created["id"])
    assert loaded is not None
    assert loaded["appLayout"] == layout


# ── Visual artifact normalization (App view source of truth) ───────────────


def test_extract_visual_artifacts_for_metric_and_plotly_chart():
    metric_artifacts = _extract_visual_artifacts(
        tool_name="display_metric",
        tool_call_id="m1",
        tool_input={},
        result={
            "type": "metric",
            "label": "Revenue",
            "value": "$1.2M",
            "delta": "+8%",
            "unit": "",
            "trend": "up",
        },
    )
    assert len(metric_artifacts) == 1
    assert metric_artifacts[0]["kind"] == "metric"
    assert metric_artifacts[0]["metric"]["label"] == "Revenue"
    assert metric_artifacts[0]["source_tool_call_id"] == "m1"

    figure = {"data": [{"x": ["A", "B"], "y": [1, 2], "type": "bar"}], "layout": {"title": "A vs B"}}
    chart_artifacts = _extract_visual_artifacts(
        tool_name="display_cell_output",
        tool_call_id="c1",
        tool_input={"cell_index": 4},
        result={
            "cell_index": 4,
            "caption": "B is twice A in this sample.",
            "outputs": [{"type": "plotly", "figure": figure}],
        },
    )
    assert len(chart_artifacts) == 1
    assert chart_artifacts[0]["kind"] == "chart"
    assert chart_artifacts[0]["figure"] == figure
    assert chart_artifacts[0]["caption"] == "B is twice A in this sample."
    assert chart_artifacts[0]["source_cell_index"] == 4


def test_extract_visual_artifacts_for_live_report():
    artifacts = _extract_visual_artifacts(
        tool_name="report_add_section",
        tool_call_id="r1",
        tool_input={"section_type": "header"},
        result={
            "type": "report",
            "html_path": "/tmp/workspace/reports/live.html",
            "title": "Live Report",
            "updated": True,
        },
    )
    assert len(artifacts) == 1
    assert artifacts[0]["kind"] == "report"
    assert artifacts[0]["html_path"] == "/tmp/workspace/reports/live.html"
    assert artifacts[0]["title"] == "Live Report"


async def test_openclaw_tool_call_message_persists_as_dataclaw_tool_call():
    from dataclaw.storage import sessions

    created = await sessions.create_session(title="OpenClaw tool call")
    await receive_message(
        created["id"],
        IncomingMessage(
            role="tool_call",
            messageId="tc-oc-1",
            toolCallId="oc-1",
            toolName="dataclaw_report_add_section",
            args={"section_type": "header"},
            result={
                "type": "report",
                "html_path": "/tmp/workspace/reports/live.html",
                "title": "Live Report",
            },
        ),
    )

    loaded = await sessions.get_session(created["id"])
    assert loaded is not None
    msg = loaded["messages"][-1]
    assert msg["role"] == "tool_call"
    assert msg["toolName"] == "report_add_section"
    assert msg["args"] == '{"section_type": "header"}'
    assert '"html_path": "/tmp/workspace/reports/live.html"' in msg["result"]
    assert loaded["visualArtifacts"][0]["kind"] == "report"


async def test_openclaw_tool_call_message_redacts_llm_result():
    from dataclaw.storage import sessions

    created = await sessions.create_session(title="OpenClaw redaction")
    await receive_message(
        created["id"],
        IncomingMessage(
            role="tool_call",
            messageId="tc-img-1",
            toolCallId="img-1",
            toolName="dataclaw_display_cell_output",
            args={"cell_index": 2},
            result={
                "outputs": [
                    {
                        "type": "image",
                        "mimetype": "image/png",
                        "data": "A" * 100,
                        "summary": "chart",
                    }
                ]
            },
        ),
    )

    loaded = await sessions.get_session(created["id"])
    assert loaded is not None
    msg = loaded["messages"][-1]
    assert "A" * 20 in msg["result"]
    assert "A" * 20 not in msg["result_for_llm"]
    assert "image elided" in msg["result_for_llm"]
