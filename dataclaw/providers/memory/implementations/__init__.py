"""Built-in memory implementations."""

from dataclaw.providers.memory.implementations.factory import memory_from_config
from dataclaw.providers.memory.implementations.keyword import KeywordMemoryProvider
from dataclaw.providers.memory.implementations.noop import NoopMemoryProvider

__all__ = [
    "KeywordMemoryProvider",
    "NoopMemoryProvider",
    "memory_from_config",
]

# RAGMemoryProvider requires optional deps — import on demand
try:
    from dataclaw.providers.memory.implementations.rag import RAGMemoryProvider
    __all__.append("RAGMemoryProvider")
except ImportError:
    pass
