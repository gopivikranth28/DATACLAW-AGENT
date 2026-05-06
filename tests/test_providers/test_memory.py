"""Tests for memory providers."""

import json
import os

import pytest

from dataclaw.providers.memory.implementations.noop import NoopMemoryProvider
from dataclaw.providers.memory.implementations.keyword import KeywordMemoryProvider
from dataclaw.providers.memory.implementations.factory import memory_from_config
from dataclaw.providers.memory.hooks import MemoryIngestHook
from dataclaw.schema import Message


# ── Helpers ────────────────────────────────────────────────────────────────

def _make_state(user_query: str = "", messages: list | None = None) -> dict:
    return {
        "session_id": "test-session",
        "user_query": user_query,
        "messages": messages or [],
    }


def _make_messages(*texts: str) -> list[Message]:
    """Alternate user/assistant messages from text strings."""
    msgs = []
    for i, text in enumerate(texts):
        role = "user" if i % 2 == 0 else "assistant"
        msgs.append(Message(role=role, content=text))
    return msgs


# ── NoopMemoryProvider ─────────────────────────────────────────────────────


class TestNoopMemoryProvider:
    @pytest.mark.asyncio
    async def test_retrieve(self):
        provider = NoopMemoryProvider()
        result = await provider.retrieve_memories(_make_state("hello"))
        assert result == []

    @pytest.mark.asyncio
    async def test_search(self):
        provider = NoopMemoryProvider()
        result = await provider.search_memory("test query")
        assert result == []

    def test_tool_definition(self):
        provider = NoopMemoryProvider()
        assert provider.as_tool_definition() is None

    @pytest.mark.asyncio
    async def test_save(self):
        provider = NoopMemoryProvider()
        result = await provider.save_memory("test content")
        assert result == {}

    def test_save_tool_definition(self):
        provider = NoopMemoryProvider()
        assert provider.as_save_tool_definition() is None

    def test_config_schema_empty(self):
        assert NoopMemoryProvider.config_schema() == []


# ── KeywordMemoryProvider ──────────────────────────────────────────────────


class TestKeywordMemoryProvider:
    @pytest.fixture
    def provider(self, tmp_path):
        return KeywordMemoryProvider(top_k=5, min_score=0.01, storage_dir=tmp_path)

    @pytest.mark.asyncio
    async def test_retrieve_empty(self, provider):
        result = await provider.retrieve_memories(_make_state("hello"))
        assert result == []

    @pytest.mark.asyncio
    async def test_retrieve_empty_query(self, provider):
        result = await provider.retrieve_memories(_make_state(""))
        assert result == []

    @pytest.mark.asyncio
    async def test_save_and_search(self, provider):
        await provider.save_memory("pandas dataframe operations and groupby")
        await provider.save_memory("SQL joins and subqueries")

        results = await provider.search_memory("dataframe")
        assert len(results) >= 1
        assert any("dataframe" in r["content"].lower() for r in results)

    @pytest.mark.asyncio
    async def test_save_returns_id(self, provider):
        result = await provider.save_memory("test memory content")
        assert "id" in result
        assert result["status"] == "saved"

    @pytest.mark.asyncio
    async def test_save_with_metadata(self, provider):
        result = await provider.save_memory("test", metadata={"tag": "important"})
        assert result["status"] == "saved"

        results = await provider.search_memory("test")
        assert len(results) >= 1
        assert results[0]["metadata"]["tag"] == "important"

    @pytest.mark.asyncio
    async def test_retrieve_finds_relevant_memories(self, provider):
        await provider.save_memory("The user prefers Python over R for data analysis")
        await provider.save_memory("The database schema has a users table with email column")
        await provider.save_memory("Weather forecast: sunny tomorrow")

        result = await provider.retrieve_memories(_make_state("Python data analysis"))
        assert len(result) >= 1
        assert any("Python" in r for r in result)

    @pytest.mark.asyncio
    async def test_retrieve_includes_conversation(self, provider):
        msgs = _make_messages(
            "How do I use pandas groupby?",
            "You can use df.groupby('column').agg(...) to group and aggregate data.",
        )
        result = await provider.retrieve_memories(
            _make_state("pandas groupby", messages=msgs)
        )
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_retrieve_skips_system_messages(self, provider):
        msgs = [Message.system("You are a helpful assistant.")]
        result = await provider.retrieve_memories(
            _make_state("assistant", messages=msgs)
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_respects_top_k(self, tmp_path):
        provider = KeywordMemoryProvider(top_k=2, min_score=0.01, storage_dir=tmp_path)
        for i in range(10):
            await provider.save_memory(f"memory about topic alpha number {i}")

        result = await provider.retrieve_memories(_make_state("topic alpha"))
        assert len(result) <= 2

    @pytest.mark.asyncio
    async def test_case_insensitive(self, provider):
        await provider.save_memory("PANDAS DataFrame operations")
        results = await provider.search_memory("pandas dataframe")
        assert len(results) >= 1

    def test_tool_definition(self, provider):
        tool_def = provider.as_tool_definition()
        assert tool_def is not None
        assert tool_def["name"] == "search_memory"
        assert "query" in tool_def["parameters"]["properties"]

    def test_save_tool_definition(self, provider):
        tool_def = provider.as_save_tool_definition()
        assert tool_def is not None
        assert tool_def["name"] == "save_memory"
        assert "content" in tool_def["parameters"]["properties"]

    def test_config_schema(self):
        schema = KeywordMemoryProvider.config_schema()
        assert len(schema) == 2
        names = {f.name for f in schema}
        assert "top_k" in names
        assert "min_score" in names
        # Verify they serialize correctly
        for field in schema:
            d = field.to_dict()
            assert "name" in d
            assert "field_type" in d
            assert "label" in d

    @pytest.mark.asyncio
    async def test_persistence(self, tmp_path):
        """Memories persist across provider instances."""
        p1 = KeywordMemoryProvider(storage_dir=tmp_path)
        await p1.save_memory("persistent memory about elephants")

        p2 = KeywordMemoryProvider(storage_dir=tmp_path)
        results = await p2.search_memory("elephants")
        assert len(results) >= 1


# ── MemoryIngestHook ───────────────────────────────────────────────────────


class TestMemoryIngestHook:
    @pytest.fixture
    def provider(self, tmp_path):
        return KeywordMemoryProvider(storage_dir=tmp_path)

    @pytest.fixture
    def hook(self, provider):
        return MemoryIngestHook(provider)

    @pytest.mark.asyncio
    async def test_auto_saves_conversation(self, hook, provider):
        msgs = _make_messages(
            "How do I merge two dataframes in pandas?",
            "You can use pd.merge(df1, df2, on='key') to merge two dataframes.",
        )
        state = _make_state("merge dataframes", messages=msgs)
        state["session_id"] = "test-session"

        await hook(state)

        results = await provider.search_memory("merge dataframes")
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_skips_short_exchanges(self, hook, provider):
        msgs = _make_messages("hi", "hey")
        state = _make_state("hi", messages=msgs)

        await hook(state)

        results = await provider.search_memory("hi")
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_skips_single_message(self, hook, provider):
        msgs = [Message.user("hello")]
        state = _make_state("hello", messages=msgs)

        result_state = await hook(state)
        assert result_state is state  # unchanged

    @pytest.mark.asyncio
    async def test_returns_state_unchanged(self, hook):
        msgs = _make_messages(
            "What is machine learning?",
            "Machine learning is a subset of AI that enables systems to learn from data.",
        )
        state = _make_state("ml", messages=msgs)

        result = await hook(state)
        assert result is state


# ── Factory ────────────────────────────────────────────────────────────────


class TestFactory:
    def test_default_is_noop(self, monkeypatch):
        monkeypatch.delenv("DATACLAW_MEMORY_BACKEND", raising=False)
        provider = memory_from_config()
        assert isinstance(provider, NoopMemoryProvider)

    def test_keyword_backend(self, monkeypatch):
        monkeypatch.setenv("DATACLAW_MEMORY_BACKEND", "keyword")
        provider = memory_from_config()
        assert isinstance(provider, KeywordMemoryProvider)

    def test_unknown_backend_raises(self, monkeypatch):
        monkeypatch.setenv("DATACLAW_MEMORY_BACKEND", "invalid")
        with pytest.raises(ValueError, match="Unknown memory backend"):
            memory_from_config()


# ── RAG tests (conditional on optional deps) ──────────────────────────────

try:
    import sentence_transformers
    import sqlite_vec
    _HAS_RAG_DEPS = True
except ImportError:
    _HAS_RAG_DEPS = False


@pytest.mark.skipif(not _HAS_RAG_DEPS, reason="RAG deps not installed")
class TestRAGMemoryProvider:
    @pytest.fixture
    def provider(self, tmp_path):
        from dataclaw.providers.memory.implementations.rag import RAGMemoryProvider
        return RAGMemoryProvider(top_k=5, db_dir=tmp_path)

    @pytest.mark.asyncio
    async def test_save_and_search(self, provider):
        await provider.save_memory("pandas dataframe operations and groupby")
        await provider.save_memory("SQL joins and subqueries in DuckDB")

        results = await provider.search_memory("how to group data in pandas")
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_save_returns_id(self, provider):
        result = await provider.save_memory("test content for RAG")
        assert "id" in result
        assert result["status"] == "saved"

    @pytest.mark.asyncio
    async def test_deduplication(self, provider):
        r1 = await provider.save_memory("exact duplicate content")
        r2 = await provider.save_memory("exact duplicate content")
        assert r1["status"] == "saved"
        assert r2["status"] == "duplicate"

    @pytest.mark.asyncio
    async def test_retrieve_memories(self, provider):
        await provider.save_memory("The user likes to analyze CSV files with DuckDB")
        result = await provider.retrieve_memories(_make_state("CSV analysis"))
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_retrieve_empty_query(self, provider):
        result = await provider.retrieve_memories(_make_state(""))
        assert result == []

    def test_tool_definitions(self, provider):
        search_def = provider.as_tool_definition()
        assert search_def is not None
        assert search_def["name"] == "search_memory"

        save_def = provider.as_save_tool_definition()
        assert save_def is not None
        assert save_def["name"] == "save_memory"

    def test_config_schema(self, provider):
        schema = type(provider).config_schema()
        assert len(schema) == 2
        names = {f.name for f in schema}
        assert "model" in names
        assert "top_k" in names
        for field in schema:
            d = field.to_dict()
            assert "name" in d
            assert "field_type" in d

    @pytest.mark.asyncio
    async def test_factory_rag(self, monkeypatch, tmp_path):
        monkeypatch.setenv("DATACLAW_MEMORY_BACKEND", "rag")
        provider = memory_from_config()
        from dataclaw.providers.memory.implementations.rag import RAGMemoryProvider
        assert isinstance(provider, RAGMemoryProvider)
