"""Tests for compaction providers."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from dataclaw.providers.compaction.implementations.drop_old import DropOldCompactor
from dataclaw.providers.compaction.implementations.llm_summarizer import (
    LLMSummarizingCompactor,
    _count_conversation_turns,
    _estimate_tokens,
    _format_message_content,
    _looks_like_scratchpad,
)
from dataclaw.schema import Message
from dataclaw.state import ReplaceMessages, append_messages
from tests.conftest import MockCompactionProvider, MockLLMProvider


# ── Mock passthrough ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mock_compaction_passthrough():
    provider = MockCompactionProvider()
    messages = [Message.user(f"msg {i}") for i in range(5)]
    result = await provider.compact(messages)
    assert len(result) == 5


# ── Token estimation ─────────────────────────────────────────────────────


def test_estimate_tokens_string_content():
    messages = [Message.user("hello world")]  # 11 chars → ~2 tokens
    assert _estimate_tokens(messages) == 11 // 4


def test_estimate_tokens_tool_result_blocks():
    messages = [
        Message(role="user", content=[
            {"type": "tool_result", "call_id": "c1", "content": "x" * 400, "is_error": False},
        ])
    ]
    assert _estimate_tokens(messages) == 400 // 4


def test_estimate_tokens_empty():
    assert _estimate_tokens([]) == 0


# ── Message content formatting ───────────────────────────────────────────


def test_format_string_content():
    msg = Message.user("hello")
    assert _format_message_content(msg) == "hello"


def test_format_tool_call_block():
    msg = Message(role="assistant", content=[
        {"type": "tool_call", "id": "c1", "name": "search", "input": {"q": "foo"}},
    ])
    result = _format_message_content(msg)
    assert "search" in result
    assert "foo" in result


def test_format_tool_result_block():
    msg = Message(role="user", content=[
        {"type": "tool_result", "call_id": "c1", "content": "found it", "is_error": False},
    ])
    result = _format_message_content(msg)
    assert "OK" in result
    assert "found it" in result


def test_format_tool_result_error():
    msg = Message(role="user", content=[
        {"type": "tool_result", "call_id": "c1", "content": "failed", "is_error": True},
    ])
    result = _format_message_content(msg)
    assert "ERROR" in result


def test_format_long_tool_result_truncated():
    msg = Message(role="user", content=[
        {"type": "tool_result", "call_id": "c1", "content": "x" * 1000, "is_error": False},
    ])
    result = _format_message_content(msg)
    assert "truncated" in result


# ── LLMSummarizingCompactor ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_compaction_under_message_limit():
    llm = MockLLMProvider(response_text="summary")
    compactor = LLMSummarizingCompactor(llm)
    messages = [Message.user(f"msg {i}") for i in range(5)]
    result = await compactor.compact(messages, max_messages=30)
    assert result is messages  # exact same object, no compaction


@pytest.mark.asyncio
async def test_compaction_triggers_over_message_limit():
    llm = MockLLMProvider(response_text="This is a summary.")
    compactor = LLMSummarizingCompactor(llm)
    messages = [Message.user(f"msg {i}") for i in range(10)]

    result = await compactor.compact(messages, max_messages=5, keep_recent=3)

    assert len(result) == 4  # 1 summary + 3 recent
    assert result[0].role == "system"
    assert "[Conversation summary]" in result[0].content
    assert "This is a summary." in result[0].content
    # Recent messages preserved
    assert result[1].content == "msg 7"
    assert result[2].content == "msg 8"
    assert result[3].content == "msg 9"


def test_tool_heavy_new_session_counts_logical_turns_not_protocol_blocks():
    """A fresh three-turn session must not compact merely because tools fan out.

    This mirrors session b1f1f69b: 10 tool calls in the first request, 4 in
    the HTML-report follow-up, then plan approval.  The old block-counting
    implementation reported 33 and split the final four outputs away from
    their calls.
    """
    messages = [
        Message.user("analyse driver and team trends"),
        Message.tool_call([
            {"type": "tool_call", "id": f"first-{i}", "name": "inspect", "input": {}}
            for i in range(10)
        ]),
        Message.tool_result([
            {"type": "tool_result", "call_id": f"first-{i}", "content": "ok", "is_error": False}
            for i in range(10)
        ]),
        Message.assistant("Plan ready"),
        Message.user("I also expect an html report"),
        Message.tool_call([
            {"type": "tool_call", "id": f"report-{i}", "name": "fetch_skill", "input": {}}
            for i in range(4)
        ]),
        Message.tool_result([
            {"type": "tool_result", "call_id": f"report-{i}", "content": "ok", "is_error": False}
            for i in range(4)
        ]),
        Message.assistant("Plan updated"),
        Message.user("Plan approved"),
    ]

    assert _count_conversation_turns(messages) == 3
    compactor = LLMSummarizingCompactor(MockLLMProvider(response_text="summary"))
    assert not compactor.will_compact(messages, max_messages=30, max_tokens=100_000)


@pytest.mark.asyncio
async def test_token_compaction_never_splits_tool_calls_from_results():
    llm = MockLLMProvider(response_text="Summary of the first request.")
    compactor = LLMSummarizingCompactor(llm)
    messages = [
        Message.user("first request"),
        Message.assistant("first answer"),
        Message.user("add an HTML report"),
        Message.tool_call([
            {"type": "tool_call", "id": f"report-{i}", "name": "fetch_skill", "input": {}}
            for i in range(4)
        ]),
        Message.tool_result([
            {
                "type": "tool_result",
                "call_id": f"report-{i}",
                "content": "x" * 100,
                "is_error": False,
            }
            for i in range(4)
        ]),
        Message.assistant("updated plan"),
        Message.user("approved"),
    ]

    result = await compactor.compact(
        messages, max_messages=30, keep_recent=2, max_tokens=1
    )

    assert [msg.role for msg in result] == [
        "system", "user", "tool_call", "tool_result", "assistant", "user"
    ]
    call_ids = {block["id"] for block in result[2].content}
    result_ids = {block["call_id"] for block in result[3].content}
    assert result_ids == call_ids


@pytest.mark.asyncio
async def test_compaction_triggers_over_token_limit():
    llm = MockLLMProvider(response_text="Token summary.")
    compactor = LLMSummarizingCompactor(llm)
    # 5 messages, each with 1000 chars → ~250 tokens each → ~1250 total
    messages = [Message.user("x" * 1000) for _ in range(5)]

    result = await compactor.compact(
        messages, max_messages=100, keep_recent=2, max_tokens=500
    )

    assert len(result) == 3  # 1 summary + 2 recent
    assert result[0].role == "system"


@pytest.mark.asyncio
async def test_no_compaction_when_tokens_disabled():
    llm = MockLLMProvider(response_text="summary")
    compactor = LLMSummarizingCompactor(llm)
    messages = [Message.user("x" * 1000) for _ in range(5)]

    # max_tokens=0 disables token-based trigger; under message limit
    result = await compactor.compact(messages, max_messages=100, max_tokens=0)
    assert result is messages


@pytest.mark.asyncio
async def test_compaction_summary_is_system_message():
    llm = MockLLMProvider(response_text="summary")
    compactor = LLMSummarizingCompactor(llm)
    messages = [Message.user(f"msg {i}") for i in range(10)]

    result = await compactor.compact(messages, max_messages=5, keep_recent=3)
    assert result[0].role == "system"


@pytest.mark.asyncio
async def test_compaction_error_returns_original():
    """If the LLM call fails, compaction should return original messages."""
    llm = MockLLMProvider(response_text="summary")
    compactor = LLMSummarizingCompactor(llm)
    # Make _summarize raise
    compactor._summarize = AsyncMock(side_effect=RuntimeError("LLM down"))

    messages = [Message.user(f"msg {i}") for i in range(10)]
    result = await compactor.compact(messages, max_messages=5, keep_recent=3)

    assert result is messages  # returned original, didn't crash


# ── Edge cases ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_keep_recent_larger_than_messages():
    llm = MockLLMProvider(response_text="summary")
    compactor = LLMSummarizingCompactor(llm)
    messages = [Message.user("a"), Message.user("b")]

    # keep_recent=100 but only 2 messages; should clamp and not crash
    result = await compactor.compact(messages, max_messages=1, keep_recent=100)
    # With 2 messages and keep_recent clamped to 1, should compact
    assert len(result) == 2  # 1 summary + 1 recent


@pytest.mark.asyncio
async def test_single_message():
    llm = MockLLMProvider(response_text="summary")
    compactor = LLMSummarizingCompactor(llm)
    messages = [Message.user("only one")]

    # Can't compact a single message
    result = await compactor.compact(messages, max_messages=0, keep_recent=0)
    assert result is messages


@pytest.mark.asyncio
async def test_empty_messages():
    llm = MockLLMProvider(response_text="summary")
    compactor = LLMSummarizingCompactor(llm)

    result = await compactor.compact([], max_messages=0)
    assert result == []


# ── DropOldCompactor ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_drop_old_no_compaction_under_limit():
    compactor = DropOldCompactor()
    messages = [Message.user(f"msg {i}") for i in range(5)]
    result = await compactor.compact(messages, max_messages=30)
    assert result is messages


@pytest.mark.asyncio
async def test_drop_old_over_message_limit():
    compactor = DropOldCompactor()
    messages = [Message.user(f"msg {i}") for i in range(10)]

    result = await compactor.compact(messages, max_messages=5, keep_recent=3)

    assert len(result) == 3
    assert result[0].content == "msg 7"
    assert result[1].content == "msg 8"
    assert result[2].content == "msg 9"


@pytest.mark.asyncio
async def test_drop_old_over_token_limit():
    compactor = DropOldCompactor()
    messages = [Message.user("x" * 1000) for _ in range(5)]

    result = await compactor.compact(
        messages, max_messages=100, keep_recent=2, max_tokens=500
    )

    assert len(result) == 2


@pytest.mark.asyncio
async def test_drop_old_token_disabled():
    compactor = DropOldCompactor()
    messages = [Message.user("x" * 1000) for _ in range(5)]
    result = await compactor.compact(messages, max_messages=100, max_tokens=0)
    assert result is messages


@pytest.mark.asyncio
async def test_drop_old_keep_recent_larger_than_messages():
    compactor = DropOldCompactor()
    messages = [Message.user("a"), Message.user("b")]
    result = await compactor.compact(messages, max_messages=1, keep_recent=100)
    assert len(result) == 2
    assert result[0].content == "a"


@pytest.mark.asyncio
async def test_drop_old_empty():
    compactor = DropOldCompactor()
    result = await compactor.compact([], max_messages=0)
    assert result == []


# ── ReplaceMessages and reducer ───────────────────────────────────────────


def test_append_messages_normal():
    existing = [Message.user("a")]
    updates = [Message.user("b")]
    result = append_messages(existing, updates)
    assert len(result) == 2
    assert result[0].content == "a"
    assert result[1].content == "b"


def test_append_messages_replace():
    existing = [Message.user("a"), Message.user("b"), Message.user("c")]
    replacement = [Message.system("summary"), Message.user("c")]
    result = append_messages(existing, ReplaceMessages(replacement))
    assert len(result) == 2
    assert result[0].role == "system"
    assert result[0].content == "summary"
    assert result[1].content == "c"


# ── Compaction marker handling in _stored_messages_to_llm ────────────────

from dataclaw.api.routers.chat import (
    _stored_messages_to_llm,
    _stored_split_for_kept_turns,
)


def test_compaction_marker_uses_the_same_logical_turn_boundary():
    stored = [
        {"role": "user", "content": "first", "timestamp": "1"},
        {"role": "tool_call", "toolCallId": "a", "timestamp": "2"},
        {"role": "assistant", "content": "done", "timestamp": "3"},
        {"role": "user", "content": "second", "timestamp": "4"},
        {"role": "tool_call", "toolCallId": "b", "timestamp": "5"},
        {"role": "assistant", "content": "done", "timestamp": "6"},
        {"role": "user", "content": "third", "timestamp": "7"},
    ]

    split_idx = _stored_split_for_kept_turns(stored, kept_turns=2)

    assert split_idx == 3
    assert stored[split_idx]["content"] == "second"


def test_stored_messages_no_marker():
    """Without a compaction marker, all messages are included."""
    stored = [
        {"role": "user", "content": "hello", "timestamp": "1"},
        {"role": "assistant", "content": "hi", "timestamp": "2"},
        {"role": "user", "content": "bye", "timestamp": "3"},
    ]
    result = _stored_messages_to_llm(stored)
    assert len(result) == 3
    assert result[0].role == "user"
    assert result[0].content == "hello"


def test_stored_messages_with_marker():
    """With a compaction marker, only summary + post-marker messages are sent."""
    stored = [
        {"role": "user", "content": "old msg 1", "timestamp": "1"},
        {"role": "assistant", "content": "old reply 1", "timestamp": "2"},
        {"role": "user", "content": "old msg 2", "timestamp": "3"},
        {"role": "assistant", "content": "old reply 2", "timestamp": "4"},
        {
            "role": "compaction",
            "content": "[Conversation summary]\nUser asked two questions.",
            "messageId": "compaction-1",
            "timestamp": "5",
        },
        {"role": "user", "content": "new msg", "timestamp": "6"},
        {"role": "assistant", "content": "new reply", "timestamp": "7"},
    ]
    result = _stored_messages_to_llm(stored)
    # Should have: 1 system (summary) + 2 messages after marker
    assert len(result) == 3
    assert result[0].role == "system"
    assert "Conversation summary" in result[0].content
    assert result[1].role == "user"
    assert result[1].content == "new msg"
    assert result[2].role == "assistant"
    assert result[2].content == "new reply"


def test_stored_messages_multiple_markers():
    """With multiple markers, only the last one is used."""
    stored = [
        {"role": "user", "content": "very old", "timestamp": "1"},
        {
            "role": "compaction",
            "content": "First summary",
            "messageId": "compaction-1",
            "timestamp": "2",
        },
        {"role": "user", "content": "middle msg", "timestamp": "3"},
        {"role": "assistant", "content": "middle reply", "timestamp": "4"},
        {
            "role": "compaction",
            "content": "Second summary",
            "messageId": "compaction-2",
            "timestamp": "5",
        },
        {"role": "user", "content": "latest msg", "timestamp": "6"},
    ]
    result = _stored_messages_to_llm(stored)
    assert len(result) == 2  # 1 summary + 1 message
    assert result[0].role == "system"
    assert result[0].content == "Second summary"
    assert result[1].role == "user"
    assert result[1].content == "latest msg"


def test_stored_messages_marker_skipped_in_output():
    """Compaction markers themselves should not appear as LLM messages."""
    stored = [
        {
            "role": "compaction",
            "content": "Summary",
            "messageId": "compaction-1",
            "timestamp": "1",
        },
        {"role": "user", "content": "hi", "timestamp": "2"},
    ]
    result = _stored_messages_to_llm(stored)
    # No message with role "compaction" should be in the output
    for msg in result:
        assert msg.role != "compaction"


def test_stored_messages_marker_with_tool_calls():
    """Tool calls after a compaction marker are properly reconstructed."""
    stored = [
        {"role": "user", "content": "old", "timestamp": "1"},
        {
            "role": "compaction",
            "content": "Summary of old conversation",
            "messageId": "compaction-1",
            "timestamp": "2",
        },
        {"role": "user", "content": "search for foo", "timestamp": "3"},
        {
            "role": "tool_call",
            "toolCallId": "tc1",
            "toolName": "search",
            "args": '{"q": "foo"}',
            "result": '{"found": true}',
            "status": "complete",
            "timestamp": "4",
        },
        {"role": "assistant", "content": "Found it!", "timestamp": "5"},
    ]
    result = _stored_messages_to_llm(stored)
    # summary + user + tool_call msg + tool_result msg + assistant
    assert len(result) == 5
    assert result[0].role == "system"
    assert result[1].role == "user"
    assert result[1].content == "search for foo"
    assert result[4].role == "assistant"
    assert result[4].content == "Found it!"


def test_stored_messages_marker_skips_orphaned_leading_tool_calls():
    """Orphaned tool_call entries right after a marker are skipped.

    This prevents LLM errors (e.g., Gemini requires tool calls after a
    user or function response turn, not after a system message).
    """
    stored = [
        {"role": "user", "content": "old question", "timestamp": "1"},
        {
            "role": "tool_call",
            "toolCallId": "tc-old",
            "toolName": "search",
            "args": '{"q": "old"}',
            "result": '{"r": "old result"}',
            "status": "complete",
            "timestamp": "2",
        },
        {"role": "assistant", "content": "old answer", "timestamp": "3"},
        {
            "role": "compaction",
            "content": "Summary",
            "messageId": "compaction-1",
            "timestamp": "4",
        },
        # These tool_calls are orphaned — their assistant context was compacted
        {
            "role": "tool_call",
            "toolCallId": "tc-orphan1",
            "toolName": "run_query",
            "args": '{}',
            "result": '"ok"',
            "status": "complete",
            "timestamp": "5",
        },
        {
            "role": "tool_call",
            "toolCallId": "tc-orphan2",
            "toolName": "run_query",
            "args": '{}',
            "result": '"ok"',
            "status": "complete",
            "timestamp": "6",
        },
        {"role": "assistant", "content": "response after tools", "timestamp": "7"},
        {"role": "user", "content": "follow up", "timestamp": "8"},
    ]
    result = _stored_messages_to_llm(stored)
    # summary + assistant + user (orphaned tool_calls skipped)
    assert len(result) == 3
    assert result[0].role == "system"
    assert result[0].content == "Summary"
    assert result[1].role == "assistant"
    assert result[1].content == "response after tools"
    assert result[2].role == "user"
    assert result[2].content == "follow up"


# ── Reasoning-leak guards ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_summarize_passes_reasoning_and_verbosity_kwargs():
    """The compactor must dial reasoning models down so they don't emit
    scratchpad as the final summary."""
    llm = MockLLMProvider(response_text="A clean prose summary in full sentences.")
    compactor = LLMSummarizingCompactor(llm)
    msgs = [Message.user("ping"), Message.assistant("pong")]
    await compactor._summarize(msgs)
    # "low" is used (not "minimal") because the codex backend rejects
    # "minimal" — see error from /api/responses with gpt-5.5.
    assert llm.last_call_kwargs.get("reasoning_effort") == "low"
    assert llm.last_call_kwargs.get("text_verbosity") == "low"


def test_looks_like_scratchpad_detects_directive_opener():
    bad = "Need summarize. Need include tool calls. Mention auto-mode. Final concise."
    assert _looks_like_scratchpad(bad)


def test_looks_like_scratchpad_detects_telegraphic_fragments():
    bad = "Round 8 incomplete. Tools. Errors guardrail. Final concise. Plan summary."
    assert _looks_like_scratchpad(bad)


def test_looks_like_scratchpad_passes_normal_prose():
    good = (
        "The user asked to train three models. The agent ran fit_model with "
        "RandomForest and reported an accuracy of 0.82. A second attempt with "
        "XGBoost improved accuracy to 0.87. The user then asked to log results."
    )
    assert not _looks_like_scratchpad(good)
