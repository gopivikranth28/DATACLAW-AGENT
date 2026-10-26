"""Structured (JSON-schema) output from any LLMProvider.

``structured_output(llm, messages, schema)`` returns a dict matching
``schema``.  Providers with a native implementation
(``StructuredOutputProvider``: OpenAI Responses / Chat, Anthropic, Gemini)
are used directly; anything else answers through a single tool call whose
parameters are the schema.
"""

from __future__ import annotations

import json
from typing import Any

from dataclaw.providers.llm.provider import (
    LLMProvider,
    PendingToolCall,
    StructuredOutputError,
    StructuredOutputProvider,
)
from dataclaw.schema import Message


async def structured_output(
    llm: LLMProvider,
    messages: list[Message],
    schema: dict[str, Any],
    *,
    system: str = "",
    name: str = "response",
    strict: bool = False,
) -> dict[str, Any]:
    """Answer ``messages`` with an object conforming to ``schema``.

    See ``StructuredOutputProvider.structured_output`` for the arguments and
    errors.
    """
    if isinstance(llm, StructuredOutputProvider):
        result = await llm.structured_output(messages, schema, system=system, name=name, strict=strict)
    else:
        result = await tool_call_structured_output(llm, messages, schema, system=system, name=name)
    return check_required(result, schema)


async def tool_call_structured_output(
    llm: LLMProvider,
    messages: list[Message],
    schema: dict[str, Any],
    *,
    system: str = "",
    name: str = "response",
) -> dict[str, Any]:
    """Fallback: offer one tool whose parameters are ``schema`` and read its call.

    Works with any provider that supports tool calls, including
    OpenAI-compatible servers without a JSON-schema response format.
    """
    tool = {
        "name": name,
        "description": "Return the answer. Its arguments are the complete structured response.",
        "parameters": schema,
    }
    instruction = (
        f"Respond only by calling the `{name}` tool exactly once, with the "
        "complete answer as its arguments."
    )
    prompt = f"{system}\n\n{instruction}" if system else instruction

    result: dict[str, Any] | None = None
    async for event in llm.stream_turn(messages, system=prompt, tools=[tool]):
        if isinstance(event, PendingToolCall) and event.tool_name == name and result is None:
            result = event.tool_input
    if result is None:
        raise StructuredOutputError(f"The model did not call the {name!r} tool")
    return check_required(result, schema)


def parse_json_object(text: str) -> dict[str, Any]:
    """Parse a model's JSON reply, which must be an object."""
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise StructuredOutputError("The model's reply is not valid JSON") from exc
    if not isinstance(data, dict):
        raise StructuredOutputError("The model's reply is not a JSON object")
    return data


def check_required(result: Any, schema: dict[str, Any]) -> dict[str, Any]:
    """Shallow conformance check: an object carrying the required properties.

    Native modes enforce the full schema server-side; this catches a model
    that ignored a non-strict schema or tool.
    """
    if not isinstance(result, dict):
        raise StructuredOutputError("The model's reply is not a JSON object")
    missing = [key for key in schema.get("required") or [] if key not in result]
    if missing:
        raise StructuredOutputError(f"The model's reply is missing required properties: {missing}")
    return result


def titled_schema(schema: dict[str, Any], name: str) -> dict[str, Any]:
    """LangChain derives the response-format / tool name from ``title``."""
    return schema if schema.get("title") else {**schema, "title": name}
