"""Memory provider factory — instantiate from configuration."""

from __future__ import annotations

import logging
from pathlib import Path

from dataclaw.config.resolver import resolve

logger = logging.getLogger(__name__)


def memory_from_config():
    """Create a MemoryProvider from current configuration."""
    backend = resolve("memory.backend", "DATACLAW_MEMORY_BACKEND", "noop")

    if backend == "noop":
        from dataclaw.providers.memory.implementations.noop import NoopMemoryProvider
        return NoopMemoryProvider()

    if backend == "keyword":
        from dataclaw.providers.memory.implementations.keyword import KeywordMemoryProvider
        top_k = int(resolve("memory.keyword.top_k", "DATACLAW_MEMORY_TOP_K", "5"))
        min_score = float(resolve("memory.keyword.min_score", "DATACLAW_MEMORY_MIN_SCORE", "0.1"))
        return KeywordMemoryProvider(top_k=top_k, min_score=min_score)

    if backend == "rag":
        from dataclaw.providers.memory.implementations.rag import RAGMemoryProvider
        model_name = resolve("memory.rag.model", "DATACLAW_EMBEDDING_MODEL", "all-MiniLM-L6-v2")
        top_k = int(resolve("memory.rag.top_k", "DATACLAW_MEMORY_TOP_K", "5"))
        return RAGMemoryProvider(model_name=model_name, top_k=top_k)

    if backend == "gbrain":
        try:
            from dataclaw_gbrain.provider import GbrainMemoryProvider
        except ImportError:
            logger.error(
                "memory.backend='gbrain' requested but dataclaw-gbrain is not "
                "installed. Falling back to noop. Install with `uv sync` after "
                "adding the plugin to dependencies."
            )
            from dataclaw.providers.memory.implementations.noop import NoopMemoryProvider
            return NoopMemoryProvider()

        location = resolve("memory.gbrain.location", "DATACLAW_GBRAIN_LOCATION", "new")
        brain_home = Path(
            resolve("memory.gbrain.brain_home", "DATACLAW_GBRAIN_HOME", "~/.dataclaw/memory")
        ).expanduser()
        mode = resolve("memory.gbrain.mode", "DATACLAW_GBRAIN_MODE", "read_write")
        top_k = int(resolve("memory.gbrain.top_k", "DATACLAW_MEMORY_TOP_K", "5"))
        gbrain_bin = resolve("memory.gbrain.gbrain_bin", "DATACLAW_GBRAIN_BIN", "gbrain")

        try:
            return GbrainMemoryProvider(
                brain_home=brain_home,
                mode=mode,
                top_k=top_k,
                location=location,
                gbrain_bin=gbrain_bin,
            )
        except Exception as exc:
            logger.error("Failed to initialize gbrain memory provider: %s", exc)
            from dataclaw.providers.memory.implementations.noop import NoopMemoryProvider
            return NoopMemoryProvider()

    raise ValueError(
        f"Unknown memory backend: {backend!r}. Valid options: noop, keyword, rag, gbrain"
    )
