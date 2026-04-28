"""Tests for AgentState TypedDict."""

from dataclaw.state import AgentState


def test_agent_state_creation():
    state: AgentState = {
        "session_id": "test-session",
        "messages": [{"role": "user", "content": "hello"}],
    }
    assert state["session_id"] == "test-session"
    assert len(state["messages"]) == 1


def test_agent_state_partial():
    """AgentState is total=False, so partial dicts are valid."""
    state: AgentState = {"session_id": "s1"}
    assert state["session_id"] == "s1"
    assert state.get("messages") is None
