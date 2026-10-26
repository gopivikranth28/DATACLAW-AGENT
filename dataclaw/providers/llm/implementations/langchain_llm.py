"""LangChain-based LLM provider.

Wraps any LangChain BaseChatModel (Anthropic, OpenAI, Gemini, etc.)
and translates between Dataclaw's Message class and LangChain message
objects at this boundary only.
"""

from __future__ import annotations

import json
import logging
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, AsyncIterator

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from dataclaw.providers.llm.capabilities import (
    ANTHROPIC,
    GEMINI,
    OPENAI,
    resolve_reasoning_effort,
    supports_text_verbosity,
)
from dataclaw.providers.llm.provider import (
    BrokerEvent,
    PendingToolCall,
    TextDeltaEvent,
    ToolUseStartEvent,
    TurnCompleteEvent,
    UsageEvent,
)
from dataclaw.schema import Message

logger = logging.getLogger(__name__)

# langchain-google-genai keeps per-function-call thought signatures here
# (tool call id -> base64 signature) rather than in the content blocks.
_GEMINI_FC_SIGNATURES_KEY = "__gemini_function_call_thought_signatures__"

# Content block types that carry provider reasoning state which must be sent
# back unchanged on the next request of the same tool loop.
_REASONING_BLOCK_TYPES = frozenset({"thinking", "redacted_thinking", "reasoning"})

# Upper bound on remembered tool-call turns (see LangChainLLM._turns). A run
# consumes its entry on the next build_tool_result_message; the bound only
# matters for runs cancelled between the two calls.
_TURN_STATE_LIMIT = 256


@dataclass
class _TurnState:
    """What build_tool_result_message needs from the AI message of a turn."""

    text_blocks: list[dict[str, Any]]
    provider_state: dict[str, Any] | None


class LangChainLLM:
    """LLM provider backed by a LangChain BaseChatModel."""

    def __init__(
        self,
        model: BaseChatModel,
        *,
        default_reasoning_effort: str | None = None,
        compat: bool = False,
    ) -> None:
        """
        Args:
            model: The LangChain chat model.
            default_reasoning_effort: Effort used on turns that don't set one
                (the backend's configured ``reasoning_effort``).
            compat: The model is served by a third-party OpenAI-compatible
                endpoint. Optional knobs (reasoning effort) are only sent when
                the model catalog vouches for them, and verbosity never is.
        """
        self._model = model
        self._default_reasoning_effort = default_reasoning_effort or None
        self._compat = compat
        # AI-message state of turns that ended in tool calls, keyed by call id.
        # Keyed (rather than "last message") because one provider instance is
        # shared by concurrent runs and by sub-agents that run inside a tool
        # call, so a later stream_turn must not clobber an earlier turn's state.
        self._turns: OrderedDict[str, _TurnState] = OrderedDict()

    async def stream_turn(
        self,
        messages: list[Message],
        *,
        system: str,
        tools: list[dict[str, Any]],
        system_dynamic: str = "",
        reasoning_effort: str | None = None,
        text_verbosity: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[BrokerEvent]:
        lc_tools = _to_lc_tools(tools)
        bound = self._model.bind_tools(lc_tools) if lc_tools else self._model
        # Translate the provider-agnostic reasoning effort (and verbosity) to
        # each SDK's native control, so "run with lower reasoning" is effective
        # on every backend, not only the OpenAI/codex path. Applied as bind
        # kwargs, and only for models that accept them; a bind failure must
        # never break the call.
        native = _native_request_kwargs(
            self._model,
            reasoning_effort or self._default_reasoning_effort,
            text_verbosity,
            compat=self._compat,
        )
        if native:
            try:
                bound = bound.bind(**native)
            except Exception:  # pragma: no cover - defensive
                logger.warning("Could not apply request options %s", native)

        # System-role messages in the history (compaction summaries) are
        # folded into the single leading system message: Anthropic rejects
        # non-consecutive system messages and Gemini merges them into
        # system_instruction anyway, so this is the one shape every backend
        # accepts.
        context = [m.text() for m in messages if m.role == "system"]
        history = [m for m in messages if m.role != "system"]

        lc_messages: list[BaseMessage] = []
        system_message = _build_system_message(self._model, system, context, system_dynamic)
        if system_message is not None:
            lc_messages.append(system_message)
        lc_messages.extend(_to_lc_messages(history, provider=_provider_tag(self._model)))

        accumulated: AIMessage | None = None
        seen_tool_indices: set[int] = set()

        async for chunk in bound.astream(lc_messages):
            accumulated = chunk if accumulated is None else accumulated + chunk

            # Text deltas
            if isinstance(chunk.content, str) and chunk.content:
                yield TextDeltaEvent(text=chunk.content)
            elif isinstance(chunk.content, list):
                for block in chunk.content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block.get("text", "")
                        if text:
                            yield TextDeltaEvent(text=text)

            # Tool call starts
            for tc_chunk in getattr(chunk, "tool_call_chunks", None) or []:
                idx = tc_chunk.get("index", 0)
                if idx not in seen_tool_indices and tc_chunk.get("name"):
                    seen_tool_indices.add(idx)
                    yield ToolUseStartEvent(
                        tool_name=tc_chunk["name"],
                        call_id=tc_chunk.get("id", ""),
                    )

        usage = _usage_event(accumulated)
        if usage is not None:
            yield usage

        tool_calls = getattr(accumulated, "tool_calls", []) if accumulated else []
        if tool_calls and accumulated is not None:
            self._remember_turn(accumulated, [tc["id"] for tc in tool_calls])
        for tc in tool_calls:
            args = tc.get("args", {})
            yield PendingToolCall(
                call_id=tc["id"],
                tool_name=tc["name"],
                tool_input=args if isinstance(args, dict) else {},
            )

        yield TurnCompleteEvent(has_pending_tool_calls=bool(tool_calls))

    def _remember_turn(self, ai_message: AIMessage, call_ids: list[str]) -> None:
        state = _TurnState(
            text_blocks=_text_blocks(ai_message.content),
            provider_state=_capture_provider_state(self._model, ai_message),
        )
        for call_id in call_ids:
            self._turns[call_id] = state
        while len(self._turns) > _TURN_STATE_LIMIT:
            self._turns.popitem(last=False)

    def build_tool_result_message(
        self,
        tool_calls: list[PendingToolCall],
        results: list[dict[str, Any]],
        errors: list[Exception | None],
    ) -> list[Message]:
        """Build Message objects to append after tool execution."""
        # The chat loop may split one turn's calls across several calls here
        # (guardrail-blocked vs executed). Each gets the turn's text and
        # provider state; _to_lc_messages scopes native tool blocks to the
        # calls each message actually carries.
        state = next(
            (self._turns[tc.call_id] for tc in tool_calls if tc.call_id in self._turns),
            None,
        )
        for tc in tool_calls:
            self._turns.pop(tc.call_id, None)

        assistant_content: list[dict[str, Any]] = list(state.text_blocks) if state else []

        for tc in tool_calls:
            assistant_content.append({
                "type": "tool_call",
                "id": tc.call_id,
                "name": tc.tool_name,
                "input": tc.tool_input,
            })

        tool_results: list[dict[str, Any]] = []
        for tc, result, err in zip(tool_calls, results, errors):
            tool_results.append({
                "type": "tool_result",
                "call_id": tc.call_id,
                "content": json.dumps({"error": str(err)}) if err else json.dumps(result, default=str),
                "is_error": err is not None,
            })

        return [
            Message.tool_call(
                assistant_content,
                provider_state=state.provider_state if state else None,
            ),
            Message.tool_result(tool_results),
        ]


# ── Helpers ──────────────────────────────────────────────────────────────────


def _provider_tag(model: Any) -> str:
    """Identify the backend that produced (and may consume) provider state."""
    return type(model).__name__


def _provider_family(model: Any) -> str | None:
    # Walk the MRO so thin subclasses (the OpenAI-compatible client) keep
    # their SDK's family without importing any SDK here.
    for cls in type(model).__mro__:
        name = cls.__name__
        if name in ("ChatOpenAI", "AzureChatOpenAI"):
            return OPENAI
        if name == "ChatAnthropic":
            return ANTHROPIC
        if name in ("ChatGoogleGenerativeAI", "ChatVertexAI"):
            return GEMINI
    return None


def _model_id(model: Any) -> str:
    # ChatOpenAI exposes ``model_name``; ChatAnthropic/Gemini use ``model``.
    return str(getattr(model, "model_name", None) or getattr(model, "model", None) or "")


def _native_reasoning_kwargs(model: Any, effort: str | None) -> dict[str, Any]:
    """Map a provider-agnostic reasoning effort to a model's native thinking knob.

    Each LangChain chat model exposes a semantic level control:
      - ChatOpenAI            -> reasoning_effort (minimal|low|medium|high)
      - ChatAnthropic         -> output_config.effort (low|medium|high; no
                                 'minimal'). A bound ``effort`` kwarg would be
                                 forwarded as a top-level request param, which
                                 the anthropic SDK rejects.
      - ChatGoogleGenerativeAI-> thinking_level (minimal|low|medium|high)
    Returns {} for an unknown model or no effort, so the call is unchanged.
    This is the mapping only; _native_request_kwargs checks the model.
    """
    if not effort:
        return {}
    family = _provider_family(model)
    if family == OPENAI:
        return {"reasoning_effort": effort}
    if family == ANTHROPIC:
        return {"output_config": {"effort": "low" if effort == "minimal" else effort}}
    if family == GEMINI:
        return {"thinking_level": effort}
    return {}


def _native_request_kwargs(
    model: Any,
    reasoning_effort: str | None,
    text_verbosity: str | None,
    *,
    compat: bool = False,
) -> dict[str, Any]:
    """Native bind kwargs for the optional per-turn knobs this model accepts.

    Callers pass these knobs opportunistically (the plans plugin raises
    effort, the compactor lowers verbosity); a model that does not implement
    one fails the whole request, so unsupported knobs are dropped and effort
    values the model lacks map to the nearest one it offers.
    """
    family = _provider_family(model)
    model_id = _model_id(model)
    kwargs: dict[str, Any] = {}
    if reasoning_effort:
        effort = (
            resolve_reasoning_effort(family, model_id, reasoning_effort, catalog_only=compat)
            if family
            else None
        )
        if effort:
            kwargs.update(_native_reasoning_kwargs(model, effort))
        else:
            logger.debug(
                "Skipping reasoning_effort=%r: not supported by %s model %r",
                reasoning_effort, type(model).__name__, model_id,
            )
    if text_verbosity:
        if family == OPENAI and not compat and supports_text_verbosity(family, model_id):
            kwargs["verbosity"] = text_verbosity
        else:
            logger.debug(
                "Skipping text_verbosity=%r: not supported by %s model %r",
                text_verbosity, type(model).__name__, model_id,
            )
    return kwargs


def _build_system_message(
    model: Any,
    system: str,
    context: list[str],
    dynamic: str,
) -> SystemMessage | None:
    """Build the one leading system message.

    Order is static prompt, then conversation context (compaction summaries),
    then the per-turn dynamic part (memories, skills, auto-mode). The static
    prompt and the summary change rarely, so they form a stable prefix that
    provider prompt caches can match; the dynamic part goes last.

    Anthropic only caches up to explicit breakpoints, so there the prompt is
    sent as blocks with ``cache_control`` on the static block and on the
    summary. Other backends cache exact prefixes automatically and get a
    plain string.
    """
    static = system if system and system.strip() else ""
    context = [c for c in context if c and c.strip()]
    dynamic = dynamic if dynamic and dynamic.strip() else ""
    if not (static or context or dynamic):
        return None

    if _provider_family(model) == ANTHROPIC:
        blocks: list[dict[str, Any]] = []
        if static:
            blocks.append({"type": "text", "text": static, "cache_control": {"type": "ephemeral"}})
        for i, text in enumerate(context):
            block: dict[str, Any] = {"type": "text", "text": text}
            if i == len(context) - 1:
                block["cache_control"] = {"type": "ephemeral"}
            blocks.append(block)
        if dynamic:
            blocks.append({"type": "text", "text": dynamic})
        return SystemMessage(content=blocks)  # type: ignore[arg-type]

    return SystemMessage(content="\n\n".join(p for p in (static, *context, dynamic) if p))


def _usage_event(message: Any) -> UsageEvent | None:
    """Convert LangChain ``usage_metadata`` to a UsageEvent."""
    usage = getattr(message, "usage_metadata", None) if message is not None else None
    if not usage:
        return None
    input_details = usage.get("input_token_details") or {}
    output_details = usage.get("output_token_details") or {}
    return UsageEvent(
        input_tokens=int(usage.get("input_tokens") or 0),
        output_tokens=int(usage.get("output_tokens") or 0),
        cached_input_tokens=int(input_details.get("cache_read") or 0),
        reasoning_tokens=int(output_details.get("reasoning") or 0),
    )


def _text_blocks(content: Any) -> list[dict[str, Any]]:
    """Canonical text blocks of an AI message's content."""
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content else []
    blocks: list[dict[str, Any]] = []
    for block in content or []:
        if isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
            blocks.append({"type": "text", "text": block["text"]})
    return blocks


def _capture_provider_state(model: Any, ai_message: AIMessage) -> dict[str, Any] | None:
    """Keep the provider-native parts of a tool-calling AI message.

    Anthropic requires the thinking blocks (with signatures) of the assistant
    turn that issued tool calls to be sent back with the tool results, and
    Gemini 3 validates thought signatures on function calls within the
    current turn. Both live in the AIMessage (content blocks / the Gemini
    signature map) that the canonical Message cannot represent, so they are
    stored verbatim, tagged with the producing model class. Returns None when
    the message carries no such state (e.g. plain Chat Completions).
    """
    content = ai_message.content
    native: list[dict[str, Any]] = []
    has_reasoning = False
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            native.append(block)
            if (
                block.get("type") in _REASONING_BLOCK_TYPES
                or "signature" in block
                or (block.get("extras") or {}).get("signature")
            ):
                has_reasoning = True
    signatures = (ai_message.additional_kwargs or {}).get(_GEMINI_FC_SIGNATURES_KEY)
    if not has_reasoning and not signatures:
        return None

    state: dict[str, Any] = {"provider": _provider_tag(model), "content": native}
    if signatures:
        state["additional_kwargs"] = {_GEMINI_FC_SIGNATURES_KEY: signatures}
    try:
        # Messages may be serialized (sub-agent metadata, Message.to_dict), so
        # normalize to plain JSON types now rather than fail later.
        return json.loads(json.dumps(state))
    except (TypeError, ValueError):
        logger.warning("Dropping non-serializable provider state from %s", state["provider"])
        return None


def _native_ai_message(
    msg: Message,
    provider: str | None,
    tool_calls: list[dict[str, Any]],
    fallback_text: str,
) -> AIMessage:
    """Rebuild an AIMessage, restoring provider-native content when it applies.

    Provider state is only replayed to the backend that produced it; any
    other backend gets the canonical text + tool calls. Native tool-use
    blocks are scoped to the calls this message carries, since one turn's
    calls can be split across messages and every tool_use must be answered
    by a tool_result in the next message.
    """
    state = msg.provider_state
    if not provider or not state or state.get("provider") != provider:
        return AIMessage(content=fallback_text, tool_calls=tool_calls)

    call_ids = {tc["id"] for tc in tool_calls}
    content = [
        block for block in state.get("content") or []
        if not (
            isinstance(block, dict)
            and block.get("type") in ("tool_use", "function_call")
            and block.get("id") not in call_ids
        )
    ]
    additional_kwargs: dict[str, Any] = {}
    signatures = (state.get("additional_kwargs") or {}).get(_GEMINI_FC_SIGNATURES_KEY)
    if isinstance(signatures, dict):
        additional_kwargs[_GEMINI_FC_SIGNATURES_KEY] = {
            k: v for k, v in signatures.items() if k in call_ids
        }
    return AIMessage(
        content=content or fallback_text,  # type: ignore[arg-type]
        tool_calls=tool_calls,
        additional_kwargs=additional_kwargs,
    )


def _to_lc_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert canonical tool definitions to LangChain tool format."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("parameters", {"type": "object", "properties": {}}),
            },
        }
        for t in tools
    ]


def _to_lc_messages(
    messages: list[Message],
    provider: str | None = None,
) -> list[BaseMessage]:
    """Convert Dataclaw Message objects to LangChain message objects.

    This is the only place LangChain types are created from our Messages.
    ``provider`` is the consuming model's tag (see _provider_tag); provider
    state stored on messages is only replayed when it matches.

    ``system`` messages (compaction summaries) map to SystemMessage.
    LangChainLLM.stream_turn folds them into the leading system message
    before calling this, because not every backend accepts a system message
    mid-conversation.
    """
    result: list[BaseMessage] = []
    for msg in messages:
        role = msg.role
        content = msg.content

        if role == "system":
            text = msg.text()
            if text:
                result.append(SystemMessage(content=text))

        elif role == "user":
            if isinstance(content, str):
                result.append(HumanMessage(content=content))
            elif isinstance(content, list):
                # Legacy: user messages with tool_result blocks (pre-refactor)
                for block in content:
                    if block.get("type") == "tool_result":
                        result.append(ToolMessage(
                            content=block.get("content", ""),
                            tool_call_id=block["call_id"],
                        ))
                    else:
                        text = block.get("text", "")
                        if text:
                            result.append(HumanMessage(content=text))

        elif role == "assistant" and isinstance(content, str):
            result.append(AIMessage(content=content))

        elif role in ("assistant", "tool_call") and isinstance(content, list):
            # Dedicated tool_call role (and legacy assistant messages with
            # mixed blocks) — text plus tool_call blocks
            text_parts: list[str] = []
            lc_tool_calls: list[dict[str, Any]] = []
            for block in content:
                btype = block.get("type")
                if btype == "text":
                    text_parts.append(block.get("text", ""))
                elif btype == "tool_call":
                    lc_tool_calls.append({
                        "id": block["id"],
                        "name": block["name"],
                        "args": block.get("input", {}),
                        "type": "tool_call",
                    })
            result.append(_native_ai_message(msg, provider, lc_tool_calls, "".join(text_parts)))

        elif role == "tool_result":
            # Dedicated tool_result role — content is list of tool_result blocks
            if isinstance(content, list):
                for block in content:
                    if block.get("type") == "tool_result":
                        result.append(ToolMessage(
                            content=block.get("content", ""),
                            tool_call_id=block["call_id"],
                        ))

    return result
