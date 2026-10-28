"""Decision-model trigger for compacting history before the thresholds.

Opt-in through ``decision.routing.compaction``.  It only ever *adds* a
compaction: when ``will_compact`` already requires one, the caller compacts
without consulting this module.  Early compaction is considered once the
history reaches ``EARLY_FRACTION`` of either threshold, and runs when the
decision model says the older turns are no longer needed verbatim with at
least ``decision.min_confidence``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from dataclaw.providers.compaction.implementations.llm_summarizer import (
    _count_conversation_turns,
    _estimate_tokens,
)
from dataclaw.providers.decision.provider import DecisionConfigurationError, DecisionError, DecisionQuestion
from dataclaw.providers.decision.registry import routing_enabled

if TYPE_CHECKING:
    from dataclaw.schema import Message

logger = logging.getLogger(__name__)

EARLY_FRACTION = 0.5
# Characters of each message shown to the decision model.
MESSAGE_PREVIEW_CHARS = 1_000
QUESTION_ID = "compact_now"
QUESTION = DecisionQuestion(
    id=QUESTION_ID,
    kind="boolean",
    prompt=(
        "Has the conversation moved on so that the earlier turns can be replaced by a "
        "short summary without losing details the next reply needs?"
    ),
)


def _near_threshold(messages: list["Message"], *, max_messages: int, max_tokens: int) -> bool:
    near_turns = max_messages > 0 and _count_conversation_turns(messages) >= max_messages * EARLY_FRACTION
    near_tokens = max_tokens > 0 and _estimate_tokens(messages) >= max_tokens * EARLY_FRACTION
    return near_turns or near_tokens


def _render(messages: list["Message"]) -> str:
    lines: list[str] = []
    for message in messages:
        text = message.text() if hasattr(message, "text") else str(message.content)
        if len(text) > MESSAGE_PREVIEW_CHARS:
            text = text[:MESSAGE_PREVIEW_CHARS] + "…"
        lines.append(f"[{message.role}] {text}")
    return "\n".join(lines)


async def should_compact_early(
    compaction: Any,
    messages: list["Message"],
    *,
    max_messages: int,
    keep_recent: int,
    max_tokens: int,
) -> bool:
    """True when the decision model recommends compacting now.

    Returns False without any decision call when the toggle is off, the
    compactor cannot shorten this history, or the history is not yet near
    a threshold.  Callers compact with ``max_messages=keep_recent``.
    """
    if not routing_enabled("compaction"):
        return False
    # The compactor must be able to act on this history at all (noop never can).
    if not compaction.will_compact(messages, max_messages=keep_recent, max_tokens=0):
        return False
    if not _near_threshold(messages, max_messages=max_messages, max_tokens=max_tokens):
        return False

    from dataclaw.providers.decision.routing import decide_with_fallback

    try:
        outcome = await decide_with_fallback(_render(messages), [QUESTION], purpose="compaction")
    except (DecisionError, DecisionConfigurationError) as exc:
        logger.warning("Early-compaction decision failed; keeping history: %s", exc)
        return False
    except Exception:
        # An optional trigger must never fail the run.
        logger.exception("Early-compaction decision raised; keeping history")
        return False
    result = outcome.result(QUESTION_ID)
    return bool(result is not None and result.answer is True and outcome.confident(QUESTION_ID))
