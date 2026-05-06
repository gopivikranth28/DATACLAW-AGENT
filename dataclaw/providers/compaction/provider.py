"""CompactionProvider protocol.

Compacts conversation history to keep context within token limits.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable, TYPE_CHECKING

if TYPE_CHECKING:
    from dataclaw.schema import Message


@runtime_checkable
class CompactionProvider(Protocol):
    """Compacts a message list, e.g. by summarising older messages."""

    def will_compact(
        self,
        messages: list[Message],
        *,
        max_messages: int = 30,
        max_tokens: int = 0,
    ) -> bool:
        """Return True if compact() would actually modify the message list."""
        ...

    async def compact(
        self,
        messages: list[Message],
        *,
        max_messages: int = 30,
        keep_recent: int = 8,
        max_tokens: int = 0,
    ) -> list[Message]:
        """Return a (possibly shortened) message list.

        Compaction triggers when either:
        - len(messages) > max_messages, or
        - estimated token count > max_tokens (0 disables token check)

        When triggered, older messages are summarised and the most recent
        keep_recent messages are kept verbatim.
        """
        ...
