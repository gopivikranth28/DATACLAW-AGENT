"""Tests for chat.py session-message ↔ LLM-message conversion on reload."""

from __future__ import annotations

from dataclaw.api.routers.chat import _stored_messages_to_llm


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
