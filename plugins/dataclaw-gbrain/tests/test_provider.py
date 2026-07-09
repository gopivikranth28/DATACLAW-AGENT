"""Tests for GbrainMemoryProvider — uses a fake client for unit coverage,
plus an opt-in integration test gated on `gbrain` being installed."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest

from dataclaw_gbrain.client import GbrainClient
from dataclaw_gbrain.provider import GbrainMemoryProvider


class FakeClient:
    """In-memory stand-in for GbrainClient. Records calls for assertions."""

    def __init__(self) -> None:
        self.put_calls: list[tuple[str, str]] = []
        self.queries: list[tuple[str, int]] = []
        self.next_query_result: list[dict[str, Any]] = []

    async def put_page(self, slug: str, content: str) -> dict[str, Any]:
        self.put_calls.append((slug, content))
        return {"slug": slug, "page_id": len(self.put_calls)}

    async def query(
        self,
        query: str,
        *,
        limit: int = 5,
        detail: str = "medium",
        expand: bool = True,
    ) -> list[dict[str, Any]]:
        self.queries.append((query, limit))
        return self.next_query_result


# ── read_only mode ───────────────────────────────────────────────────────


async def test_read_only_disables_save_tool():
    provider = GbrainMemoryProvider(
        brain_home=Path("/tmp/x"), mode="read_only", location="existing", client=FakeClient(),
    )
    assert provider.as_save_tool_definition() is None


async def test_read_only_save_is_noop():
    fake = FakeClient()
    provider = GbrainMemoryProvider(
        brain_home=Path("/tmp/x"), mode="read_only", location="existing", client=fake,
    )
    result = await provider.save_memory("anything", metadata={"foo": "bar"})
    assert result == {"status": "noop", "reason": "read_only"}
    assert fake.put_calls == []


async def test_read_only_search_still_works():
    fake = FakeClient()
    fake.next_query_result = [
        {"slug": "a", "score": 0.5, "chunk_text": "hello", "title": "A", "type": "note"},
    ]
    provider = GbrainMemoryProvider(
        brain_home=Path("/tmp/x"), mode="read_only", location="existing", client=fake,
    )
    out = await provider.search_memory("hi", limit=3)
    assert len(out) == 1
    assert out[0]["id"] == "a"
    assert out[0]["score"] == 0.5
    assert fake.queries == [("hi", 3)]


# ── read_write mode ──────────────────────────────────────────────────────


async def test_read_write_exposes_save_tool():
    provider = GbrainMemoryProvider(
        brain_home=Path("/tmp/x"), mode="read_write", location="existing", client=FakeClient(),
    )
    save_def = provider.as_save_tool_definition()
    assert save_def is not None
    assert save_def["name"] == "save_memory"
    assert "content" in save_def["parameters"]["properties"]


async def test_save_writes_page_with_frontmatter():
    fake = FakeClient()
    provider = GbrainMemoryProvider(
        brain_home=Path("/tmp/x"), mode="read_write", location="existing", client=fake,
    )
    result = await provider.save_memory(
        "User prefers DuckDB over Postgres for ad-hoc work.",
        metadata={"session_id": "abc-123", "auto": False},
    )
    assert result["status"] == "saved"
    assert result["id"].startswith("dataclaw-memory/")
    assert len(fake.put_calls) == 1

    slug, content = fake.put_calls[0]
    assert slug == result["id"]
    assert content.startswith("---\n")
    assert "type: note" in content
    assert "tags: [dataclaw-memory]" in content
    assert "session_id:" in content
    assert "auto: false" in content
    assert "DuckDB" in content


async def test_retrieve_memories_empty_query():
    provider = GbrainMemoryProvider(
        brain_home=Path("/tmp/x"), mode="read_write", location="existing", client=FakeClient(),
    )
    out = await provider.retrieve_memories({"user_query": "", "messages": []})
    assert out == []


async def test_retrieve_memories_formats_hits():
    fake = FakeClient()
    fake.next_query_result = [
        {"slug": "users/jack", "chunk_text": "Jack prefers DuckDB."},
        {"slug": "users/jack/profile", "chunk_text": "Loves Python."},
        {"slug": "x", "chunk_text": ""},  # filtered out — empty content
    ]
    provider = GbrainMemoryProvider(
        brain_home=Path("/tmp/x"), mode="read_write", top_k=5, location="existing", client=fake,
    )
    out = await provider.retrieve_memories({"user_query": "what does jack like"})
    assert out == [
        "[gbrain:users/jack] Jack prefers DuckDB.",
        "[gbrain:users/jack/profile] Loves Python.",
    ]
    assert fake.queries == [("what does jack like", 5)]


# ── validation ───────────────────────────────────────────────────────────


def test_unknown_mode_raises():
    with pytest.raises(ValueError, match="Unknown gbrain mode"):
        GbrainMemoryProvider(
            brain_home=Path("/tmp/x"), mode="banana", client=FakeClient(),
        )


# ── integration (skipped if gbrain is not installed) ─────────────────────


@pytest.mark.skipif(shutil.which("gbrain") is None, reason="gbrain CLI not on PATH")
async def test_integration_save_persists_page(tmp_path: Path):
    """Real gbrain round-trip: init a fresh brain, save_memory, confirm the
    page is fetchable via get_page.

    We don't assert on search/query here — those require embeddings to be
    materialized (`gbrain embed --stale`), which needs an OpenAI API key.
    """
    brain_home = tmp_path / "brain"
    brain_home.mkdir()

    # Initialize a brand-new pglite brain in this dir.
    import os, subprocess
    env = os.environ.copy()
    env["GBRAIN_HOME"] = str(brain_home)
    bun_bin = str(Path.home() / ".bun" / "bin")
    if bun_bin not in env.get("PATH", "").split(os.pathsep):
        env["PATH"] = f"{bun_bin}{os.pathsep}{env.get('PATH', '')}"
    init = subprocess.run(
        ["gbrain", "init", "--pglite"], env=env, capture_output=True, text=True, timeout=60,
    )
    if init.returncode != 0:
        pytest.skip(f"gbrain init failed: {init.stderr}")

    client = GbrainClient(brain_home=brain_home)
    provider = GbrainMemoryProvider(
        brain_home=brain_home, mode="read_write", top_k=3, client=client,
    )

    saved = await provider.save_memory(
        "Polypropylene melts at around 165 degrees Celsius.",
        metadata={"topic": "materials"},
    )
    assert saved["status"] == "saved"

    page = await client.get_page(saved["id"])
    assert page is not None
    compiled = (page.get("compiled_truth") or "").lower()
    assert "polypropylene" in compiled, f"saved page missing content; got {page}"
