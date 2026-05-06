"""No-op compaction — passes messages through unchanged."""

from __future__ import annotations

from dataclaw.schema import Message


class NoopCompactor:
    """Compaction disabled — returns messages as-is."""

    def will_compact(self, messages: list[Message], *, max_messages: int = 30, max_tokens: int = 0) -> bool:
        return False

    async def compact(
        self,
        messages: list[Message],
        *,
        max_messages: int = 30,
        keep_recent: int = 8,
        max_tokens: int = 0,
    ) -> list[Message]:
        return messages
