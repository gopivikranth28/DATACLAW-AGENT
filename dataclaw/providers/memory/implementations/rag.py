"""RAG memory provider — semantic search via local embeddings + SQLite vector store."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import sqlite3
import struct
import time
import uuid
from pathlib import Path
from typing import Any

from dataclaw.config.paths import plugin_data_dir
from dataclaw.providers.config_field import ConfigField
from dataclaw.state import AgentState

logger = logging.getLogger(__name__)


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def _serialize_f32(vec: list[float]) -> bytes:
    """Serialize a float32 vector for sqlite-vec."""
    return struct.pack(f"{len(vec)}f", *vec)


class RAGMemoryProvider:
    """Embedding-based semantic search with SQLite vector storage."""

    @classmethod
    def config_schema(cls) -> list[ConfigField]:
        return [
            ConfigField(
                name="model",
                field_type="string",
                label="Embedding Model",
                description="Sentence-transformers model for embeddings",
                default="all-MiniLM-L6-v2",
            ),
            ConfigField(
                name="top_k",
                field_type="int",
                label="Top K",
                description="Number of memories to retrieve",
                default=5,
            ),
        ]

    def __init__(
        self,
        *,
        model_name: str = "all-MiniLM-L6-v2",
        top_k: int = 5,
        db_dir: Path | None = None,
    ) -> None:
        self._model_name = model_name
        self._top_k = top_k
        self._db_dir = db_dir or plugin_data_dir("rag_memory")
        self._db_path = self._db_dir / "memory.db"

        self._model: Any = None
        self._dim: int | None = None
        self._conn: sqlite3.Connection | None = None
        self._lock = asyncio.Lock()

    # ── Lazy init ──────────────────────────────────────────────────────

    def _ensure_model(self) -> None:
        if self._model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            raise ImportError(
                "RAGMemoryProvider requires sentence-transformers. "
                "Install with: pip install 'dataclaw[rag]'"
            )
        self._model = SentenceTransformer(self._model_name)
        self._dim = self._model.get_sentence_embedding_dimension()

    def _ensure_db(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        try:
            import sqlite_vec
        except ImportError:
            raise ImportError(
                "RAGMemoryProvider requires sqlite-vec. "
                "Install with: pip install 'dataclaw[rag]'"
            )

        self._ensure_model()
        self._db_dir.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(str(self._db_path))
        sqlite_vec.load(conn)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                metadata TEXT NOT NULL DEFAULT '{}',
                session_id TEXT,
                created_at REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_hash
            ON memories(content_hash)
        """)
        conn.execute(f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS memory_embeddings
            USING vec0(embedding float[{self._dim}])
        """)
        conn.commit()
        self._conn = conn
        return conn

    # ── Embedding ──────────────────────────────────────────────────────

    def _embed(self, texts: list[str]) -> list[list[float]]:
        self._ensure_model()
        embeddings = self._model.encode(texts, normalize_embeddings=True)
        return [e.tolist() for e in embeddings]

    def _embed_one(self, text: str) -> list[float]:
        return self._embed([text])[0]

    # ── Internal ops (run in thread) ───────────────────────────────────

    def _save_sync(
        self,
        content: str,
        metadata: dict[str, Any] | None,
        session_id: str | None,
    ) -> dict[str, Any]:
        conn = self._ensure_db()
        ch = _content_hash(content)

        # Dedup check
        existing = conn.execute(
            "SELECT id FROM memories WHERE content_hash = ?", (ch,)
        ).fetchone()
        if existing:
            return {"id": existing[0], "status": "duplicate"}

        mem_id = str(uuid.uuid4())
        embedding = self._embed_one(content)
        now = time.time()

        conn.execute(
            "INSERT INTO memories (id, content, content_hash, metadata, session_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (mem_id, content, ch, json.dumps(metadata or {}), session_id, now),
        )
        # sqlite-vec uses rowid; get the rowid of the inserted memory
        rowid = conn.execute(
            "SELECT rowid FROM memories WHERE id = ?", (mem_id,)
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO memory_embeddings (rowid, embedding) VALUES (?, ?)",
            (rowid, _serialize_f32(embedding)),
        )
        conn.commit()
        logger.info("Saved RAG memory %s", mem_id)
        return {"id": mem_id, "status": "saved"}

    def _search_sync(
        self,
        query: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        conn = self._ensure_db()
        embedding = self._embed_one(query)

        rows = conn.execute(
            """
            SELECT m.id, m.content, m.metadata, m.session_id, e.distance
            FROM memory_embeddings e
            JOIN memories m ON m.rowid = e.rowid
            WHERE e.embedding MATCH ?
            ORDER BY e.distance
            LIMIT ?
            """,
            (_serialize_f32(embedding), limit),
        ).fetchall()

        results = []
        for row in rows:
            results.append({
                "id": row[0],
                "content": row[1],
                "metadata": json.loads(row[2]),
                "session_id": row[3],
                "score": round(1.0 - row[4], 4),  # distance → similarity
            })
        return results

    def _retrieve_sync(
        self,
        query: str,
        limit: int,
    ) -> list[str]:
        results = self._search_sync(query, limit)
        return [f"[memory]: {r['content'][:300]}" for r in results]

    # ── Protocol: Read ─────────────────────────────────────────────────

    async def retrieve_memories(self, state: AgentState) -> list[str]:
        query = state.get("user_query", "")
        if not query:
            return []
        async with self._lock:
            return await asyncio.to_thread(self._retrieve_sync, query, self._top_k)

    async def search_memory(
        self,
        query: str,
        *,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        async with self._lock:
            return await asyncio.to_thread(self._search_sync, query, limit)

    def as_tool_definition(self) -> dict[str, Any] | None:
        return {
            "name": "search_memory",
            "description": "Semantically search saved memories using natural language. Returns the most relevant memories by meaning, not just keywords.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query (natural language)",
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
        async with self._lock:
            return await asyncio.to_thread(
                self._save_sync, content, metadata, None
            )

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
