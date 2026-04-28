"""Providers router — list registered providers and their config schemas.

This endpoint lets the UI dynamically render configuration forms
for each provider based on their config_schema().
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("")
async def list_providers(request: Request) -> list[dict[str, Any]]:
    """List all registered providers with their config schemas."""
    registry = request.app.state.providers
    result = []

    for slot in ["compaction", "system_prompt", "memory", "skill",
                  "tool_availability", "llm", "agent", "sub_agent"]:
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

        result.append({
            "slot": slot,
            "name": type(provider).__name__,
            "config_schema": config_schema,
        })

    return result
