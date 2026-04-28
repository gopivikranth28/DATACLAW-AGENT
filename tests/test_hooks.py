"""Tests for the hook system."""

import pytest

from dataclaw.hooks.base import Hook, HookError
from dataclaw.hooks.registry import HookRegistry, HOOK_POINTS
from dataclaw.state import AgentState


@pytest.fixture
def registry():
    return HookRegistry()


def test_hook_points_defined():
    assert "userQueryHook" in HOOK_POINTS
    assert "postCompactionHook" in HOOK_POINTS
    assert "postAgentMessageHook" in HOOK_POINTS


def test_register_invalid_point(registry):
    async def noop(state):
        return state
    with pytest.raises(ValueError, match="Unknown hook point"):
        registry.register("nonexistent", noop)


@pytest.mark.asyncio
async def test_hook_passthrough(registry):
    """A hook that returns state unchanged."""
    async def passthrough(state: AgentState) -> AgentState:
        return state

    registry.register("userQueryHook", passthrough)
    state: AgentState = {"session_id": "test", "messages": []}
    result = await registry.run("userQueryHook", state)
    assert result["session_id"] == "test"


@pytest.mark.asyncio
async def test_hook_mutation(registry):
    """A hook that modifies state."""
    async def add_memory(state: AgentState) -> AgentState:
        return {**state, "memories": ["test memory"]}

    registry.register("postMemoryHook", add_memory)
    state: AgentState = {"session_id": "test", "messages": [], "memories": []}
    result = await registry.run("postMemoryHook", state)
    assert result["memories"] == ["test memory"]


@pytest.mark.asyncio
async def test_hook_chaining(registry):
    """Hooks chain sequentially, each getting the previous output."""
    async def add_one(state: AgentState) -> AgentState:
        turn = state.get("turn", 0)
        return {**state, "turn": turn + 1}

    registry.register("userQueryHook", add_one)
    registry.register("userQueryHook", add_one)
    registry.register("userQueryHook", add_one)

    state: AgentState = {"session_id": "test", "messages": [], "turn": 0}
    result = await registry.run("userQueryHook", state)
    assert result["turn"] == 3


@pytest.mark.asyncio
async def test_hook_error_propagation(registry):
    """HookError aborts the chain."""
    async def failing_hook(state: AgentState) -> AgentState:
        raise HookError("blocked by hook")

    async def never_reached(state: AgentState) -> AgentState:
        return {**state, "turn": 999}

    registry.register("userQueryHook", failing_hook)
    registry.register("userQueryHook", never_reached)

    state: AgentState = {"session_id": "test", "messages": [], "turn": 0}
    with pytest.raises(HookError, match="blocked by hook"):
        await registry.run("userQueryHook", state)


def test_unregister(registry):
    async def hook(state):
        return state

    registry.register("userQueryHook", hook)
    registry.unregister("userQueryHook", hook)
    # Should have no hooks now (won't error on run)
