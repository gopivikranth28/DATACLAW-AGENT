"""Provider schema metadata used by the transactional settings UI."""

from dataclaw.api.routers.providers import _all_backend_schemas


def test_compaction_exposes_every_backend_schema_without_switching_config():
    schemas = _all_backend_schemas("compaction")

    assert schemas["noop"] == []
    assert {field["name"] for field in schemas["drop_old"]} == {
        "max_messages", "keep_recent", "max_tokens"
    }
    assert {field["name"] for field in schemas["llm_summarizer"]} == {
        "max_messages", "keep_recent", "max_tokens"
    }


def test_memory_exposes_built_in_backend_schemas_without_switching_config():
    schemas = _all_backend_schemas("memory")

    assert schemas["noop"] == []
    assert {field["name"] for field in schemas["keyword"]} == {"top_k", "min_score"}
    assert {field["name"] for field in schemas["rag"]} == {"model", "top_k"}
    assert "gbrain" in schemas
