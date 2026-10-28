"""Size helpers shared by decision backends.

Token counts are estimated at ~4 characters per token, the same rough
measure compaction uses; backends keep a safety margin below their limits.
"""

from __future__ import annotations

import json
from typing import Any

CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    return -(-len(text) // CHARS_PER_TOKEN)


def state_text(state: str | dict[str, Any] | list[Any]) -> str:
    """The state as the text a model reads (JSON for objects)."""
    if isinstance(state, str):
        return state
    return json.dumps(state, ensure_ascii=False, default=str, sort_keys=True)


def truncate_middle(text: str, max_chars: int) -> str:
    """Keep the start and the end of ``text`` within ``max_chars``.

    The start usually frames the situation and the end holds the latest
    events, so the middle is dropped and marked.
    """
    if len(text) <= max_chars:
        return text
    if max_chars <= 0:
        return ""
    marker = f"\n…[{len(text) - max_chars} characters truncated]…\n"
    keep = max(max_chars - len(marker), 0)
    head = keep // 2
    tail = keep - head
    return text[:head] + marker + (text[-tail:] if tail else "")
