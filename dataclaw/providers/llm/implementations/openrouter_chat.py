"""Chat Completions client for OpenRouter.

``OpenRouterChatOpenAI`` is the OpenAI-compatible client plus what
OpenRouter adds on top of Chat Completions (see ``llm/openrouter.py`` for the
wire details and their sources):

- optional knobs are gated on the model's ``supported_parameters`` from the
  live catalog: reasoning effort becomes the unified ``reasoning`` object,
  ``verbosity`` is only sent where listed;
- ``reasoning_details`` from responses are kept on the AIMessage and sent
  back on the assistant message of the next request, so reasoning models
  (Claude, Gemini, GPT) keep their state across tool turns;
- provider routing preferences and model fallbacks go in the body;
- ``usage.cost`` is copied to ``response_metadata["cost_usd"]``.

OpenRouter-only body fields are sent through the OpenAI SDK's
``extra_body``, which the SDK merges into the JSON body unchanged.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator, ClassVar

from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk, ChatResult

from dataclaw.providers.llm import openrouter
from dataclaw.providers.llm.implementations.openai_compatible import CompatibleChatOpenAI

logger = logging.getLogger(__name__)

REASONING_DETAILS_KEY = "reasoning_details"
COST_METADATA_KEY = "cost_usd"


class OpenRouterChatOpenAI(CompatibleChatOpenAI):
    """ChatOpenAI against https://openrouter.ai/api/v1 (Chat Completions)."""

    # Raw ``llm.backends.openrouter.routing`` settings.
    routing: dict[str, Any] | None = None

    # LangChainLLM passes reasoning effort and verbosity through unfiltered;
    # this class decides per model (see _get_request_payload).
    gates_request_options: ClassVar[bool] = True

    def __init__(self, **kwargs: Any) -> None:
        # ChatOpenAI switches to the Responses API when the payload carries
        # ``reasoning`` or for some model names; OpenRouter's Responses API
        # is beta, so always use Chat Completions.
        kwargs.setdefault("use_responses_api", False)
        super().__init__(**kwargs)

    @property
    def provider_state_tag(self) -> str:
        """Scope replayed reasoning state to this backend and model."""
        return f"{type(self).__name__}:{self.model_name}"

    @property
    def explicit_cache_breakpoints(self) -> bool:
        """Claude needs explicit ``cache_control`` breakpoints, which OpenRouter
        passes through on Chat Completions content blocks
        (https://openrouter.ai/docs/guides/best-practices/prompt-caching.md#anthropic-claude)."""
        return (self.model_name or "").startswith("anthropic/")

    def catalog_entry(self) -> dict[str, Any] | None:
        return openrouter.cached_model(self.model_name or "")

    async def native_structured_output(self) -> bool:
        """Whether ``response_format: json_schema`` can be used for this model."""
        await openrouter.ensure_catalog()
        return openrouter.native_structured_output(self.catalog_entry())

    # ── Requests ────────────────────────────────────────────────────────────

    def _get_request_payload(self, input_: Any, *, stop: list[str] | None = None, **kwargs: Any) -> dict:
        effort = kwargs.pop("reasoning_effort", None)
        verbosity = kwargs.pop("verbosity", None)
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)

        # Replay reasoning_details on the assistant messages that produced them.
        # The payload messages are built 1:1 from the input messages.
        messages = self._convert_input(input_).to_messages()
        for lc_message, wire in zip(messages, payload.get("messages") or []):
            if isinstance(lc_message, AIMessage) and isinstance(wire, dict):
                details = lc_message.additional_kwargs.get(REASONING_DETAILS_KEY)
                if isinstance(details, list) and details:
                    wire[REASONING_DETAILS_KEY] = details

        entry = self.catalog_entry()
        params = openrouter.supported_parameters(entry)
        extra: dict[str, Any] = dict(payload.get("extra_body") or {})
        if effort:
            reasoning = openrouter.reasoning_request(entry, effort)
            if reasoning:
                extra["reasoning"] = reasoning
            else:
                logger.debug("Skipping reasoning effort %r: not supported by %r", effort, self.model_name)
        if verbosity:
            if "verbosity" in params:
                extra["verbosity"] = verbosity
            else:
                logger.debug("Skipping verbosity %r: not supported by %r", verbosity, self.model_name)
        extra.update(openrouter.routing_request_fields(self.routing, self.model_name or ""))
        if extra:
            payload["extra_body"] = extra
        return payload

    async def _astream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ChatGenerationChunk]:
        await openrouter.ensure_catalog()
        async for chunk in super()._astream(*args, **kwargs):
            yield chunk

    async def _agenerate(self, *args: Any, **kwargs: Any) -> ChatResult:
        await openrouter.ensure_catalog()
        return await super()._agenerate(*args, **kwargs)

    # ── Responses ───────────────────────────────────────────────────────────

    def _convert_chunk_to_generation_chunk(
        self,
        chunk: dict,
        default_chunk_class: type,
        base_generation_info: dict | None,
    ) -> ChatGenerationChunk | None:
        generation = super()._convert_chunk_to_generation_chunk(chunk, default_chunk_class, base_generation_info)
        if generation is None or not isinstance(generation.message, AIMessageChunk):
            return generation
        message = generation.message
        choices = chunk.get("choices") or []
        delta = choices[0].get("delta") if choices and isinstance(choices[0], dict) else None
        details = delta.get(REASONING_DETAILS_KEY) if isinstance(delta, dict) else None
        if isinstance(details, list) and details:
            message.additional_kwargs[REASONING_DETAILS_KEY] = [
                openrouter.as_fragment(d) for d in details if isinstance(d, dict)
            ]
        cost = openrouter.usage_cost(chunk.get("usage"))
        if cost is not None:
            message.response_metadata[COST_METADATA_KEY] = cost
        return generation

    def _create_chat_result(self, response: Any, generation_info: dict | None = None) -> ChatResult:
        result = super()._create_chat_result(response, generation_info)
        data = response if isinstance(response, dict) else response.model_dump()
        cost = openrouter.usage_cost(data.get("usage"))
        for generation, choice in zip(result.generations, data.get("choices") or []):
            message = generation.message
            wire = choice.get("message") if isinstance(choice, dict) else None
            details = wire.get(REASONING_DETAILS_KEY) if isinstance(wire, dict) else None
            if isinstance(details, list) and details:
                message.additional_kwargs[REASONING_DETAILS_KEY] = details
            if cost is not None:
                message.response_metadata[COST_METADATA_KEY] = cost
        return result
