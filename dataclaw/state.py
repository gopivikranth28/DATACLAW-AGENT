"""Agent pipeline state — LangGraph-compatible TypedDict.

Each node in the LangGraph StateGraph reads fields from this state
and returns a partial dict with updated fields. LangGraph merges
the partial updates into the full state automatically.

Messages use Dataclaw's own Message class (not LangChain messages).
The custom reducer `append_messages` handles merging: new messages
from a node are appended to the existing list.
"""

from __future__ import annotations

from typing import Any, Callable, Awaitable, TypedDict, Annotated

from dataclaw.schema import Message


def append_messages(
    existing: list[Message],
    updates: list[Message],
) -> list[Message]:
    """LangGraph reducer: append new messages to the conversation."""
    return existing + updates


class AgentState(TypedDict, total=False):
    # ── Identity ────────────────────────────────────────────────────────
    session_id: str
    project_id: str | None
    user_query: str

    # ── Conversation ────────────────────────────────────────────────────
    messages: Annotated[list[Message], append_messages]

    # ── Pipeline outputs (populated progressively by each node) ─────────
    system_prompt: str
    memories: list[str]
    skills: list[dict[str, Any]]
    skill_prompt_fragments: list[str]
    tools: list[dict[str, Any]]
    tool_callables: dict[str, Callable[..., Awaitable[dict[str, Any]]]]

    # ── Agent response ──────────────────────────────────────────────────
    pending_tool_calls: list[dict[str, Any]]
    tool_results: list[dict[str, Any]]

    # ── Loop metadata ───────────────────────────────────────────────────
    turn: int
    max_turns: int
    metadata: dict[str, Any]
