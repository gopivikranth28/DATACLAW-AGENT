"""Keyword-based memory provider — BM25-like scoring over persisted memories."""

from __future__ import annotations

import json
import logging
import math
import re
import time
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

from dataclaw.config.paths import plugin_data_dir
from dataclaw.providers.config_field import ConfigField
from dataclaw.state import AgentState

logger = logging.getLogger(__name__)

_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    """Lowercase word tokenization."""
    return _WORD_RE.findall(text.lower())


def _bm25_score(
    query_tokens: list[str],
    doc_tokens: list[str],
    doc_freq: dict[str, int],
    num_docs: int,
    avg_dl: float,
    k1: float = 1.5,
    b: float = 0.75,
) -> float:
    """BM25 score for a single document against a query."""
    if not doc_tokens or not query_tokens:
        return 0.0
    dl = len(doc_tokens)
    tf_map = Counter(doc_tokens)
    score = 0.0
    for term in query_tokens:
        tf = tf_map.get(term, 0)
        if tf == 0:
            continue
        df = doc_freq.get(term, 0)
        idf = math.log((num_docs - df + 0.5) / (df + 0.5) + 1.0)
        numerator = tf * (k1 + 1)
        denominator = tf + k1 * (1 - b + b * dl / avg_dl)
        score += idf * numerator / denominator
    return score


class KeywordMemoryProvider:
    """Keyword search over persisted memories with BM25 scoring."""

    @classmethod
    def config_schema(cls) -> list[ConfigField]:
        return [
            ConfigField(
                name="top_k",
                field_type="int",
                label="Top K",
                description="Number of memories to retrieve",
                default=5,
            ),
            ConfigField(
                name="min_score",
                field_type="string",
                label="Min Score",
                description="Minimum BM25 score threshold for relevance",
                default="0.1",
            ),
        ]

    def __init__(
        self,
        *,
        top_k: int = 5,
        min_score: float = 0.1,
        storage_dir: Path | None = None,
    ) -> None:
        self._top_k = top_k
        self._min_score = min_score
        self._storage_dir = storage_dir or plugin_data_dir("keyword_memory")
        self._file = self._storage_dir / "memories.json"
        self._messages: list[Any] = []  # cached for tool use

    # ── Persistence ────────────────────────────────────────────────────

    def _load_memories(self) -> list[dict[str, Any]]:
        if not self._file.exists():
            return []
        try:
            return json.loads(self._file.read_text())
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to load memories from %s", self._file)
            return []

    def _save_memories(self, memories: list[dict[str, Any]]) -> None:
        self._file.write_text(json.dumps(memories, indent=2))

    # ── Scoring ────────────────────────────────────────────────────────

    def _score_entries(
        self,
        query: str,
        entries: list[dict[str, Any]],
        limit: int,
    ) -> list[tuple[dict[str, Any], float]]:
        query_tokens = _tokenize(query)
        if not query_tokens or not entries:
            return []

        all_doc_tokens = [_tokenize(e["content"]) for e in entries]
        num_docs = len(all_doc_tokens)
        avg_dl = sum(len(dt) for dt in all_doc_tokens) / max(num_docs, 1)

        # Document frequencies
        doc_freq: dict[str, int] = Counter()
        for dt in all_doc_tokens:
            for term in set(dt):
                doc_freq[term] += 1

        scored: list[tuple[dict[str, Any], float]] = []
        for entry, dt in zip(entries, all_doc_tokens):
            s = _bm25_score(query_tokens, dt, doc_freq, num_docs, avg_dl)
            if s >= self._min_score:
                scored.append((entry, s))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:limit]

    # ── Protocol: Read ─────────────────────────────────────────────────

    async def retrieve_memories(self, state: AgentState) -> list[str]:
        self._messages = state.get("messages", [])
        query = state.get("user_query", "")
        if not query:
            return []

        # Score persisted memories
        persisted = self._load_memories()

        # Also include recent conversation messages as candidates
        msg_entries: list[dict[str, Any]] = []
        for msg in self._messages:
            text = msg.text() if hasattr(msg, "text") else str(msg)
            role = getattr(msg, "role", "unknown")
            if role == "system" or len(text.strip()) < 10:
                continue
            msg_entries.append({"content": text, "role": role, "source": "conversation"})

        all_entries = persisted + msg_entries
        scored = self._score_entries(query, all_entries, self._top_k)

        results: list[str] = []
        for entry, _score in scored:
            role = entry.get("role", "memory")
            content = entry["content"][:300]
            results.append(f"[{role}]: {content}")

        return results

    async def search_memory(
        self,
        query: str,
        *,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        persisted = self._load_memories()
        scored = self._score_entries(query, persisted, limit)
        return [
            {
                "id": entry.get("id", ""),
                "score": round(score, 4),
                "content": entry["content"],
                "metadata": entry.get("metadata", {}),
            }
            for entry, score in scored
        ]

    def as_tool_definition(self) -> dict[str, Any] | None:
        return {
            "name": "search_memory",
            "description": "Search saved memories by keyword. Returns the most relevant memories matching the query.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results to return",
                        "default": 10,
                    },
                },
                "required": ["query"],
            },
        }

    # ── Protocol: Write ────────────────────────────────────────────────

    async def save_memory(
        self,
        content: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        memories = self._load_memories()
        entry = {
            "id": str(uuid.uuid4()),
            "content": content,
            "metadata": metadata or {},
            "created_at": time.time(),
        }
        memories.append(entry)
        self._save_memories(memories)
        logger.info("Saved keyword memory %s", entry["id"])
        return {"id": entry["id"], "status": "saved"}

    def as_save_tool_definition(self) -> dict[str, Any] | None:
        return {
            "name": "save_memory",
            "description": "Save a piece of information to memory for future reference. Use this to remember important facts, user preferences, or context that should persist across conversations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "The memory content to save",
                    },
                    "metadata": {
                        "type": "object",
                        "description": "Optional metadata tags for the memory",
                    },
                },
                "required": ["content"],
            },
        }
