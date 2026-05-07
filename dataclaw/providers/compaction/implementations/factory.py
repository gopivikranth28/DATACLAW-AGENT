"""Compaction provider factory — instantiate from configuration."""

from __future__ import annotations

from dataclaw.config.resolver import resolve


def compaction_from_config(llm=None):
    """Create a CompactionProvider from current configuration.

    Falls back to the legacy ``enabled`` flag if ``backend`` is not set.
    """
    backend = resolve("compaction.backend", "DATACLAW_COMPACTION_BACKEND", "noop")

    # Legacy compat: if backend is still "noop", check the old enabled flag
    if backend == "noop":
        enabled = str(resolve("compaction.enabled", "DATACLAW_COMPACTION_ENABLED", "false")).lower()
        if enabled in ("true", "1", "yes"):
            backend = "llm_summarizer"

    if backend == "noop":
        from dataclaw.providers.compaction.implementations.noop import NoopCompactor
        return NoopCompactor()

    if backend == "drop_old":
        from dataclaw.providers.compaction.implementations.drop_old import DropOldCompactor
        return DropOldCompactor()

    if backend == "llm_summarizer":
        from dataclaw.providers.compaction.implementations.llm_summarizer import LLMSummarizingCompactor
        if llm is None:
            from dataclaw.providers.llm.implementations.factory import llm_from_config
            llm = llm_from_config()
        return LLMSummarizingCompactor(llm)

    raise ValueError(f"Unknown compaction backend: {backend!r}. Valid options: noop, drop_old, llm_summarizer")
