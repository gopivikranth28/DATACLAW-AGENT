"""SystemPromptProvider protocol.

Builds the full system prompt, optionally injecting memories and skills.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from dataclaw.state import AgentState


@runtime_checkable
class SystemPromptProvider(Protocol):
    """Builds the system prompt for an agent turn.

    Implementations may read state["memories"] and
    state["skill_prompt_fragments"] to inject context.
    """

    async def build_system_prompt(self, state: AgentState) -> str: ...
