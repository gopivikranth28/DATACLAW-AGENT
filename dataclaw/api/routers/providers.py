"""Providers router — list registered providers and their config schemas.

This endpoint lets the UI dynamically render configuration forms
for each provider based on their config_schema().
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

router = APIRouter()

# Slots that support multiple backend implementations, selectable via config.
# Maps slot name → (config_path_prefix, list of (value, label) options).
_BACKEND_SLOTS: dict[str, dict[str, Any]] = {
    "compaction": {
        "config_key": "compaction.backend",
        "options": [
            {"value": "noop", "label": "None (disabled)"},
            {"value": "drop_old", "label": "Drop Old Messages"},
            {"value": "llm_summarizer", "label": "LLM Summarizer"},
        ],
        "config_paths": {
            "noop": None,
            "drop_old": "compaction",
            "llm_summarizer": "compaction",
        },
    },
    "memory": {
        "config_key": "memory.backend",
        "options": [
            {"value": "noop", "label": "None (disabled)"},
            {"value": "keyword", "label": "Keyword Search"},
            {"value": "rag", "label": "RAG (Embeddings)"},
            {"value": "gbrain", "label": "GBrain"},
        ],
        "config_paths": {
            "noop": None,
            "keyword": "memory.keyword",
            "rag": "memory.rag",
            "gbrain": "memory.gbrain",
        },
    },
}


def _schema_dicts(provider_type: Any) -> list[dict[str, Any]]:
    """Serialize a provider type's UI schema without constructing it."""
    try:
        schema = provider_type.config_schema()
    except Exception:
        return []
    return [field.to_dict() if hasattr(field, "to_dict") else field for field in schema]


def _all_backend_schemas(slot: str) -> dict[str, list[dict[str, Any]]]:
    """Return schemas for every selectable backend in a provider slot.

    The settings UI edits a local draft and must be able to preview dependent
    fields before anything is persisted.  Previously it PATCHed a backend
    choice immediately just to make this endpoint expose the new schema.
    """
    if slot == "compaction":
        from dataclaw.providers.compaction.implementations.drop_old import DropOldCompactor
        from dataclaw.providers.compaction.implementations.llm_summarizer import LLMSummarizingCompactor

        return {
            "noop": [],
            "drop_old": _schema_dicts(DropOldCompactor),
            "llm_summarizer": _schema_dicts(LLMSummarizingCompactor),
        }

    if slot == "memory":
        from dataclaw.providers.memory.implementations.keyword import KeywordMemoryProvider
        from dataclaw.providers.memory.implementations.rag import RAGMemoryProvider

        schemas = {
            "noop": [],
            "keyword": _schema_dicts(KeywordMemoryProvider),
            "rag": _schema_dicts(RAGMemoryProvider),
            "gbrain": [],
        }
        try:
            from dataclaw_gbrain.provider import GbrainMemoryProvider

            schemas["gbrain"] = _schema_dicts(GbrainMemoryProvider)
        except ImportError:
            # The option remains visible because an existing config may refer
            # to it, but environments without the optional plugin have no
            # provider-specific fields to render.
            pass
        return schemas

    return {}


@router.get("")
async def list_providers(request: Request) -> list[dict[str, Any]]:
    """List all registered providers with their config schemas."""
    registry = request.app.state.providers
    config = getattr(request.app.state, "config", None)
    result = []

    for slot in ["compaction", "system_prompt", "memory", "skill",
                  "tool_availability", "llm", "agent"]:
        provider = getattr(registry, slot, None)
        if provider is None:
            result.append({"slot": slot, "name": None, "config_schema": []})
            continue

        config_schema = []
        if hasattr(provider, "config_schema"):
            try:
                schema = provider.config_schema()
                config_schema = [f.to_dict() if hasattr(f, "to_dict") else f for f in schema]
            except Exception:
                pass

        entry: dict[str, Any] = {
            "slot": slot,
            "name": type(provider).__name__,
            "config_schema": config_schema,
        }

        # Add backend selection metadata for slots that support it
        backend_meta = _BACKEND_SLOTS.get(slot)
        if backend_meta:
            # Resolve current backend value from config
            current_backend = None
            if config:
                parts = backend_meta["config_key"].split(".")
                obj: Any = config
                for p in parts:
                    obj = getattr(obj, p, None) if hasattr(obj, p) else (obj.get(p) if isinstance(obj, dict) else None)
                    if obj is None:
                        break
                current_backend = obj

            default_key = next(iter(backend_meta["config_paths"]))
            config_path = backend_meta["config_paths"].get(
                current_backend if current_backend is not None else default_key
            )
            entry["backend"] = {
                "config_key": backend_meta["config_key"],
                "current": current_backend if current_backend is not None else default_key,
                "options": backend_meta["options"],
                "config_paths": backend_meta["config_paths"],
                "schemas": _all_backend_schemas(slot),
            }
            entry["config_path"] = config_path

        result.append(entry)

    # Sub-agent providers: list all registered types
    result.append({
        "slot": "sub_agent",
        "name": "SubAgentRegistry",
        "config_schema": [],
        "agent_types": registry.sub_agent_registry.list_types(),
    })

    return result
