"""Template-based system prompt builder.

Assembles the system prompt from a base template, injecting
memories and skill fragments from the pipeline state.
"""

from __future__ import annotations

from dataclaw.state import AgentState

_DEFAULT_BASE = (
    "You are Dataclaw, a local-first open data scientist. "
    "You help users analyze data, write queries, build models, "
    "and produce durable analytical artifacts. Be concise and precise. "
    "When writing code, prefer Python with DuckDB/Polars, and SQL using DuckDB syntax."
)


class TemplateSystemPromptProvider:
    """Builds a system prompt from a base template with injection slots."""

    def __init__(self, base_prompt: str | None = None) -> None:
        self._base = base_prompt or _DEFAULT_BASE

    async def build_system_prompt(self, state: AgentState) -> str:
        parts = [self._base]

        memories = state.get("memories", [])
        if memories:
            parts.append("\n## Relevant Memories\n")
            parts.extend(f"- {m}" for m in memories)

        fragments = state.get("skill_prompt_fragments", [])
        if fragments:
            parts.append("\n## Available Skills\n")
            parts.extend(fragments)

        return "\n".join(parts)
