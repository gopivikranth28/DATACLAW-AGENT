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

    async def compact(
        self,
        messages: list[Message],
        *,
        max_messages: int = 30,
        keep_recent: int = 8,
    ) -> list[Message]:
        """Return a (possibly shortened) message list.

        If the list is already within max_messages, return it unchanged.
        Otherwise summarise older messages and keep the most recent
        keep_recent messages verbatim.
        """
        ...
