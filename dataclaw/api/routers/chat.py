"""Chat router — AG-UI streaming endpoint and session management.

The agent loop runs as a background task, decoupled from the HTTP response.
Events are logged in the RunTracker; the frontend tails the log via SSE.
This allows reconnection, cancellation, and message queuing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from dataclaw.api.context import current_emitter, current_thread_id
from dataclaw.api.run_tracker import RunState, get_run_tracker
from dataclaw.config.resolver import resolve
from dataclaw.events.emitter import AgentEventEmitter
# Use text/event-stream so @ag-ui/client routes to the SSE parser (not protobuf)
_SSE_MEDIA_TYPE = "text/event-stream"
from dataclaw.hooks.base import HookError
from dataclaw.hooks.registry import HookRegistry
from dataclaw.plugins.registry import ProviderRegistry
from dataclaw.providers.llm.provider import PendingToolCall, TextDeltaEvent, ToolUseStartEvent, TurnCompleteEvent
from dataclaw.providers.tool.llm_redact import redact_for_llm
from dataclaw.schema import Message
from dataclaw.storage import sessions

logger = logging.getLogger(__name__)

router = APIRouter()
agent_router = APIRouter()


# ── Agent Background Task ──────────────────────────────────────────────────


async def _run_agent_loop(
    thread_id: str,
    run_id: str,
    raw_messages: list[dict[str, Any]],
    user_query: str,
    providers: ProviderRegistry,
    hooks: HookRegistry,
) -> None:
    """Run the agent loop as a background task. Emits events to the RunTracker."""
    tracker = get_run_tracker()
    emitter = AgentEventEmitter(thread_id, run_id)

    def emit(event_str: str) -> None:
        tracker.append_event(thread_id, event_str)

    current_thread_id.set(thread_id)
    current_emitter.set(emitter)

    emit(emitter.run_started())

    try:
        # Persist user message first
        if user_query:
            await sessions.append_message(thread_id, {"role": "user", "content": user_query, "messageId": f"user-{run_id}"})

        # Load full session history (including tool calls) as LLM context
        session_data = await sessions.get_session(thread_id)
        stored_msgs = session_data.get("messages", []) if session_data else []
        sorted_msgs = sorted(stored_msgs, key=lambda m: m.get("timestamp", ""))
        messages = _stored_messages_to_llm(sorted_msgs)

        # Resolve project_id and auto_mode from session metadata
        project_id: str | None = None
        auto_mode: bool = False
        try:
            if session_data:
                project_id = session_data.get("projectId")
                auto_mode = bool(session_data.get("autoMode", False))
        except Exception:
            pass

        # Run pipeline stages (hooks + providers) before agent call
        state: dict[str, Any] = {
            "session_id": thread_id,
            "project_id": project_id,
            "user_query": user_query,
            "messages": messages,
            "metadata": {"auto_mode": auto_mode},
        }
        state = await hooks.run("userQueryHook", state)

        # Compaction: if threshold exceeded, summarize old messages and
        # persist a compaction marker so history is retained for the UI
        # while only recent messages + summary are sent to the LLM.
        # Defaults must match dataclaw/config/schema.py::CompactionConfig — the
        # resolver returns this fallback (not the Pydantic default) when a key
        # is missing from the on-disk config, which happens for legacy configs
        # written before a field was added.
        compact_kwargs = {
            "max_messages": int(resolve("compaction.max_messages", "DATACLAW_COMPACTION_MAX", "30")),
            "keep_recent": int(resolve("compaction.keep_recent", "DATACLAW_COMPACTION_KEEP", "8")),
            "max_tokens": int(resolve("compaction.max_tokens", "DATACLAW_COMPACTION_MAX_TOKENS", "100000")),
        }
        current_messages = state.get("messages", messages)
        if providers.compaction.will_compact(current_messages, max_messages=compact_kwargs["max_messages"], max_tokens=compact_kwargs["max_tokens"]):
            state = await hooks.run("preCompactionHook", state)
            compacted = await providers.compaction.compact(current_messages, **compact_kwargs)

            # Extract the summary from the compacted result (first system message)
            summary_text = ""
            if compacted and compacted[0].role == "system":
                summary_text = compacted[0].text() if hasattr(compacted[0], "text") else str(compacted[0].content)

            # Count how many messages were compacted vs kept
            keep_recent = compact_kwargs["keep_recent"]
            compacted_count = max(0, len(sorted_msgs) - keep_recent)
            kept_count = min(keep_recent, len(sorted_msgs))

            # Insert the marker at the split point: right before the kept messages
            # so the UI shows <old history> <compaction divider> <recent messages>
            marker_id = f"compaction-{uuid.uuid4()}"
            insert_idx = compacted_count  # position after old messages, before recent
            await sessions.insert_message_at(thread_id, insert_idx, {
                "role": "compaction",
                "content": summary_text,
                "messageId": marker_id,
                "compactedCount": compacted_count,
                "keptCount": kept_count,
            })

            # Emit SSE event so frontend shows the compaction in real-time.
            # Send the full summary — the divider is collapsible, so a long
            # summary doesn't crowd the chat by default but can be expanded.
            emit(emitter.custom("compaction", {
                "messageId": marker_id,
                "summary": summary_text,
                "compactedCount": compacted_count,
                "keptCount": kept_count,
            }))

            state["messages"] = compacted
            state = await hooks.run("postCompactionHook", state)

        # Memory (before system prompt so memories can be injected into it)
        memories = await providers.memory.retrieve_memories(state)
        state["memories"] = memories
        state = await hooks.run("postMemoryHook", state)

        # System prompt — build parts for cache-friendly backends
        from dataclaw.providers.system_prompt.implementations.template import SystemPromptParts
        prompt_parts: SystemPromptParts | None = None
        if hasattr(providers.system_prompt, "build_system_prompt_parts"):
            prompt_parts = providers.system_prompt.build_system_prompt_parts(state)
            state["system_prompt"] = prompt_parts.static
            state["system_prompt_dynamic"] = prompt_parts.dynamic
        else:
            system_prompt = await providers.system_prompt.build_system_prompt(state)
            state["system_prompt"] = system_prompt
        state = await hooks.run("postSystemPromptHook", state)

        # Skills
        skills = await providers.skill.resolve_skills(state)
        fragments = await providers.skill.format_for_prompt(skills)
        state["skills"] = skills
        state["skill_prompt_fragments"] = fragments
        state = await hooks.run("postSkillHook", state)

        # If we have parts, rebuild dynamic after skills are resolved
        if prompt_parts is not None and hasattr(providers.system_prompt, "build_system_prompt_parts"):
            prompt_parts = providers.system_prompt.build_system_prompt_parts(state)
            state["system_prompt_dynamic"] = prompt_parts.dynamic

        # Tool availability
        tool_defs, tool_callables = await providers.tool_availability.resolve_tools(state)
        state["tools"] = tool_defs
        state["tool_callables"] = tool_callables
        state = await hooks.run("postToolAvailabilityHook", state)

        # Set prompt cache key for providers that support it (e.g. OpenAI Responses API).
        from dataclaw.providers.llm.implementations.openai_responses import OpenAIResponsesLLM
        if isinstance(providers.llm, OpenAIResponsesLLM):
            providers.llm.prompt_cache_key = thread_id

        # Agent loop with real streaming
        max_turns = int(resolve("app.max_turns", "DATACLAW_MAX_TURNS", "30"))
        _text_chunks: list[str] = []

        for turn in range(max_turns):
            msg_id = str(uuid.uuid4())
            message_started = False
            pending: list[PendingToolCall] = []
            _text_chunks.clear()

            # Stream from agent provider directly
            async for event in providers.agent.stream_turn(state):
                if isinstance(event, TextDeltaEvent):
                    if not message_started:
                        emit(emitter.text_message_start(msg_id))
                        message_started = True
                    _text_chunks.append(event.text)
                    emit(emitter.text_delta(event.text, msg_id))

                elif isinstance(event, ToolUseStartEvent):
                    emit(emitter.tool_call_start(event.call_id, event.tool_name))

                elif isinstance(event, PendingToolCall):
                    pending.append(event)
                    emit(emitter.tool_call_args(
                        event.call_id,
                        json.dumps(event.tool_input, default=str),
                    ))
                    emit(emitter.tool_call_end(event.call_id))

                elif isinstance(event, TurnCompleteEvent):
                    if not event.has_pending_tool_calls:
                        if message_started:
                            emit(emitter.text_message_end(msg_id))

                        if event.skip_persist:
                            # External provider (e.g. OpenClaw fire-and-forget).
                            # Keep the run alive — the callback endpoint will
                            # emit the response and finish the run.
                            run = tracker.get_run(thread_id)
                            if run:
                                await run._completion.wait()
                            return
                        else:
                            # Normal provider — persist and finish.
                            agent_text = state.get("metadata", {}).get("agent_text", "")
                            if not agent_text:
                                agent_text = "".join(t for t in _text_chunks)
                            if agent_text:
                                await sessions.append_message(thread_id, {"role": "assistant", "content": agent_text, "messageId": f"asst-{msg_id}"})
                            # Bump the auto-mode turn counter so it survives page
                            # navigation. Only counts auto-driven turns — manual
                            # user messages don't drain the budget.
                            if auto_mode:
                                try:
                                    fresh = await sessions.get_session(thread_id)
                                    prev = int((fresh or {}).get("autoTurnsUsed", 0) or 0)
                                    await sessions.update_session(
                                        thread_id, {"autoTurnsUsed": prev + 1}
                                    )
                                except Exception:
                                    logger.exception("Failed to bump autoTurnsUsed")
                            state = await hooks.run("postAgentMessageHook", state)
                            emit(emitter.run_finished())
                            tracker.finish_run(thread_id)
                            return

            # Tool call path
            if pending:
                state["pending_tool_calls"] = [
                    {"tool_name": tc.tool_name, "tool_input": tc.tool_input, "call_id": tc.call_id}
                    for tc in pending
                ]
                state["guardrail_verdicts"] = []
                # Save original tool calls before hooks may remove them
                _original_tool_calls = {
                    tc.call_id: {"tool_name": tc.tool_name, "tool_input": tc.tool_input, "call_id": tc.call_id}
                    for tc in pending
                }
                state = await hooks.run("preToolCallHook", state)

                # ── Pre-phase guardrail handling ───────────────────────────
                verdicts = state.get("guardrail_verdicts", [])
                pre_verdicts = [v for v in verdicts if v.get("phase") == "pre"]

                # Separate auto-reply vs user-approval verdicts
                auto_reply_ids: set[str] = set()
                approval_verdicts: list[dict[str, Any]] = []
                for v in pre_verdicts:
                    if v["mode"] == "user_approval":
                        approval_verdicts.append(v)
                    elif v["mode"] == "auto_reply":
                        auto_reply_ids.add(v["tool_call_id"])

                # Track which user-approval calls were denied (not approved)
                denied_ids: set[str] = set()

                # Handle user-approval guardrails: pause and wait for decision
                run = tracker.get_run(thread_id)
                for v in approval_verdicts:
                    call_id = v["tool_call_id"]
                    approval_id = f"guardrail-{uuid.uuid4()}"
                    emit(emitter.custom("guardrail:approval_required", {
                        "approvalId": approval_id,
                        "guardrailId": v["guardrail_id"],
                        "toolCallId": call_id,
                        "message": v["message"],
                        "severity": v.get("severity", "warning"),
                    }))

                    if run:
                        approval_event = asyncio.Event()
                        run.guardrail_approvals[approval_id] = approval_event
                        try:
                            await asyncio.wait_for(approval_event.wait(), timeout=300)
                        except asyncio.TimeoutError:
                            run.guardrail_decisions[approval_id] = {"approved": False, "feedback": "Timed out"}
                        decision = run.guardrail_decisions.get(approval_id, {"approved": False})
                        run.guardrail_approvals.pop(approval_id, None)
                        run.guardrail_decisions.pop(approval_id, None)

                        if decision.get("approved"):
                            emit(emitter.custom("guardrail:approved", {
                                "approvalId": approval_id,
                                "toolCallId": call_id,
                            }))
                        else:
                            denied_ids.add(call_id)
                            emit(emitter.custom("guardrail:denied", {
                                "approvalId": approval_id,
                                "toolCallId": call_id,
                            }))

                # All blocked IDs = auto_reply + denied user-approval
                blocked_ids = auto_reply_ids | denied_ids

                # Emit auto-reply events only for auto_reply mode (not for denied user-approval,
                # which already got a guardrail:denied event)
                for v in pre_verdicts:
                    if v["mode"] != "auto_reply" or v["tool_call_id"] not in auto_reply_ids:
                        continue
                    call_id = v["tool_call_id"]
                    result_json = json.dumps({"guardrail": v["guardrail_id"], "blocked": v["message"]})
                    emit(emitter.tool_call_result(call_id, result_json, msg_id))
                    emit(emitter.custom("guardrail:auto_reply", {
                        "guardrailId": v["guardrail_id"],
                        "toolCallId": call_id,
                        "message": v["message"],
                        "severity": v.get("severity", "warning"),
                    }))
                    orig = _original_tool_calls.get(call_id, {})
                    await sessions.append_message(thread_id, {
                        "role": "tool_call", "messageId": f"tc-{call_id}",
                        "toolCallId": call_id, "toolName": orig.get("tool_name", "unknown"),
                        "args": json.dumps(orig.get("tool_input", {}), default=str),
                        "result": result_json, "status": "error",
                    })

                # For denied user-approval calls, emit the tool_call_result (but no extra guardrail card)
                for v in approval_verdicts:
                    call_id = v["tool_call_id"]
                    if call_id not in denied_ids:
                        continue
                    result_json = json.dumps({"guardrail": v["guardrail_id"], "denied": True, "message": "The user denied this action. Do not retry it."})
                    emit(emitter.tool_call_result(call_id, result_json, msg_id))
                    orig = _original_tool_calls.get(call_id, {})
                    await sessions.append_message(thread_id, {
                        "role": "tool_call", "messageId": f"tc-{call_id}",
                        "toolCallId": call_id, "toolName": orig.get("tool_name", "unknown"),
                        "args": json.dumps(orig.get("tool_input", {}), default=str),
                        "result": result_json, "status": "error",
                    })

                # Rebuild pending list:
                # - Start from what the hook left in pending_tool_calls
                # - Re-add approved user-approval calls (the hook removed them)
                # - Exclude anything still blocked
                patched_pending = list(state.get("pending_tool_calls", []))
                approved_ids = {v["tool_call_id"] for v in approval_verdicts} - denied_ids
                for call_id in approved_ids:
                    orig = _original_tool_calls.get(call_id)
                    if orig and not any(p.get("call_id") == call_id for p in patched_pending):
                        patched_pending.append(orig)

                remaining: list[PendingToolCall] = []
                for ptc in patched_pending:
                    if ptc.get("call_id") not in blocked_ids:
                        remaining.append(PendingToolCall(
                            call_id=ptc.get("call_id", ""),
                            tool_name=ptc.get("tool_name", ""),
                            tool_input=ptc.get("tool_input", {}),
                        ))

                # Build synthetic tool results for blocked calls so the LLM sees them
                blocked_tool_calls = [
                    PendingToolCall(
                        call_id=cid,
                        tool_name=_original_tool_calls.get(cid, {}).get("tool_name", "unknown"),
                        tool_input={},
                    )
                    for cid in blocked_ids
                ]
                blocked_results = [
                    {"guardrail": next((v["guardrail_id"] for v in pre_verdicts if v["tool_call_id"] == cid), "unknown"), "blocked": True}
                    for cid in blocked_ids
                ]
                blocked_errors: list[Exception | None] = [
                    ValueError("The user denied this action. Do not retry it.")
                    if cid in denied_ids else
                    ValueError(next((v["message"] for v in pre_verdicts if v["tool_call_id"] == cid), "Blocked by guardrail"))
                    for cid in blocked_ids
                ]
                if blocked_tool_calls:
                    blocked_msgs = providers.llm.build_tool_result_message(
                        blocked_tool_calls, blocked_results, blocked_errors
                    )
                    state["messages"] = list(state["messages"]) + blocked_msgs

                pending = remaining

                # ── Execute remaining (non-blocked) tools ──────────────────
                results_list: list[dict[str, Any]] = []
                errors_list: list[Exception | None] = []
                for tc in pending:
                    fn = tool_callables.get(tc.tool_name)
                    if fn is None:
                        results_list.append({})
                        errors_list.append(ValueError(f"Unknown tool: {tc.tool_name}"))
                        result_json = json.dumps({"error": f"Unknown tool: {tc.tool_name}"})
                        emit(emitter.tool_call_result(tc.call_id, result_json, msg_id))
                        await sessions.append_message(thread_id, {
                            "role": "tool_call", "messageId": f"tc-{tc.call_id}",
                            "toolCallId": tc.call_id, "toolName": tc.tool_name,
                            "args": json.dumps(tc.tool_input, default=str),
                            "result": result_json, "status": "error",
                        })
                        continue
                    try:
                        result = await fn(**tc.tool_input)
                        results_list.append(result)
                        errors_list.append(None)
                        result_json = json.dumps(result, default=str)
                        # Compute the LLM-side view; persist alongside the
                        # full result so reloads consistently feed the slim
                        # version back to the LLM. Only stored when it
                        # actually differs (most tool results are identical).
                        llm_view_json = json.dumps(redact_for_llm(result), default=str)
                        emit(emitter.tool_call_result(tc.call_id, result_json, msg_id))
                        msg_record: dict[str, Any] = {
                            "role": "tool_call", "messageId": f"tc-{tc.call_id}",
                            "toolCallId": tc.call_id, "toolName": tc.tool_name,
                            "args": json.dumps(tc.tool_input, default=str),
                            "result": result_json, "status": "complete",
                        }
                        if llm_view_json != result_json:
                            msg_record["result_for_llm"] = llm_view_json
                        await sessions.append_message(thread_id, msg_record)
                    except Exception as e:
                        logger.exception("Tool %s failed", tc.tool_name)
                        results_list.append({})
                        errors_list.append(e)
                        result_json = json.dumps({"error": str(e)})
                        emit(emitter.tool_call_result(tc.call_id, result_json, msg_id))
                        await sessions.append_message(thread_id, {
                            "role": "tool_call", "messageId": f"tc-{tc.call_id}",
                            "toolCallId": tc.call_id, "toolName": tc.tool_name,
                            "args": json.dumps(tc.tool_input, default=str),
                            "result": result_json, "status": "error",
                        })

                # Build canonical messages and append to conversation. Use the
                # redacted view of each result so the live-turn LLM context
                # matches what reload would feed it later.
                if pending:
                    llm_results_list = [redact_for_llm(r) for r in results_list]
                    new_msgs = providers.llm.build_tool_result_message(
                        pending, llm_results_list, errors_list
                    )
                    state["messages"] = list(state["messages"]) + new_msgs

                # ── Post-phase guardrail handling ──────────────────────────
                # Populate tool_results for post-phase guardrails to inspect
                state["tool_results"] = [
                    {
                        "call_id": tc.call_id,
                        "tool_name": tc.tool_name,
                        "tool_input": tc.tool_input,
                        "result": json.dumps(results_list[i], default=str) if i < len(results_list) else "",
                        "is_error": errors_list[i] is not None if i < len(errors_list) else False,
                    }
                    for i, tc in enumerate(pending)
                ]
                state = await hooks.run("postToolCallHook", state)

                # Check for post-phase guardrail verdicts
                post_verdicts = [
                    v for v in state.get("guardrail_verdicts", [])
                    if v.get("phase") == "post" and v["tool_call_id"] not in blocked_ids
                ]
                for v in post_verdicts:
                    emit(emitter.custom("guardrail:post_intervention", {
                        "guardrailId": v["guardrail_id"],
                        "toolCallId": v["tool_call_id"],
                        "message": v["message"],
                        "severity": v.get("severity", "warning"),
                    }))

                if message_started:
                    emit(emitter.text_message_end(msg_id))

        # Max turns reached
        emit(emitter.run_finished())
        tracker.finish_run(thread_id)

    except asyncio.CancelledError:
        logger.info("Agent loop cancelled for thread %s", thread_id)
        emit(emitter.run_finished())
        tracker.finish_run(thread_id)

    except HookError as e:
        emit(emitter.run_error(str(e)))
        tracker.finish_run(thread_id, "error")

    except Exception as e:
        logger.exception("Agent loop error")
        emit(emitter.run_error(f"Internal error: {e}"))
        emit(emitter.run_finished())
        tracker.finish_run(thread_id, "error")


# ── Session → LLM Message Conversion ──────────────────────────────────────


def _stored_messages_to_llm(stored_messages: list[dict[str, Any]]) -> list[Message]:
    """Convert stored session messages to Message objects for the LLM.

    If a compaction marker (role="compaction") exists, only messages after
    the last marker are sent to the LLM, prefixed with the summary as a
    system message. This preserves full history in storage while keeping
    the LLM context window manageable.

    The session stores tool invocations as flat entries with role "tool_call".
    We reconstruct the proper message structure:
      - tool_call entries → Message.tool_call([...blocks...])
      - their results    → Message.tool_result([...blocks...])
      - user/assistant   → Message(role=..., content=text)
    """
    # Find the last compaction marker
    last_marker_idx = -1
    for i, m in enumerate(stored_messages):
        if m.get("role") == "compaction":
            last_marker_idx = i

    # If a marker exists, start from the marker (summary + messages after it)
    summary_msg: Message | None = None
    if last_marker_idx >= 0:
        marker = stored_messages[last_marker_idx]
        summary_text = marker.get("content", "")
        if summary_text:
            summary_msg = Message.system(summary_text)
        # Only process messages after the marker
        stored_messages = stored_messages[last_marker_idx + 1:]
        # Skip leading tool_call entries — they're orphaned (their assistant
        # context was compacted into the summary). Starting with tool_call
        # violates LLM message ordering (e.g., Gemini requires tool calls
        # after a user or function response turn).
        while stored_messages and stored_messages[0].get("role") == "tool_call":
            stored_messages = stored_messages[1:]

    messages: list[Message] = []
    if summary_msg:
        messages.append(summary_msg)

    pending_tool_calls: list[dict[str, Any]] = []
    pending_tool_results: list[dict[str, Any]] = []

    def _flush_tool_calls() -> None:
        if not pending_tool_calls:
            return
        messages.append(Message.tool_call(list(pending_tool_calls)))
        messages.append(Message.tool_result(list(pending_tool_results)))
        pending_tool_calls.clear()
        pending_tool_results.clear()

    for m in stored_messages:
        role = m.get("role", "")
        if role == "tool_call":
            pending_tool_calls.append({
                "type": "tool_call",
                "id": m.get("toolCallId", m.get("messageId", "")),
                "name": m.get("toolName", "unknown"),
                "input": json.loads(m.get("args", "{}")),
            })
            pending_tool_results.append({
                "type": "tool_result",
                "call_id": m.get("toolCallId", m.get("messageId", "")),
                # Prefer the LLM-redacted payload when it was persisted; fall
                # back to the full `result` for legacy messages and for tool
                # calls whose redacted view matched the original byte-for-byte.
                "content": m.get("result_for_llm") or m.get("result", ""),
                "is_error": m.get("status") == "error",
            })
        elif role in ("user", "assistant"):
            _flush_tool_calls()
            messages.append(Message(role=role, content=m.get("content", "")))
        # Skip compaction and other non-LLM roles

    _flush_tool_calls()
    return messages


# ── Session → AG-UI Message Conversion ─────────────────────────────────────


def _session_messages_to_agui(raw_messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert stored session messages to AG-UI Message format.

    Stored format uses flat entries with role "tool_call" for tool invocations.
    AG-UI format uses AssistantMessage with nested toolCalls[] and separate
    ToolMessage entries for results.
    """
    agui: list[dict[str, Any]] = []
    # Buffer tool_call entries until the next assistant message (which used them)
    pending_tool_calls: list[dict[str, Any]] = []
    pending_tool_results: list[dict[str, Any]] = []

    for m in raw_messages:
        role = m.get("role", "")
        if role == "tool_call":
            tc_id = m.get("toolCallId", m.get("messageId", ""))
            pending_tool_calls.append({
                "id": tc_id,
                "type": "function",
                "function": {
                    "name": m.get("toolName", "unknown"),
                    "arguments": m.get("args", "{}"),
                },
            })
            pending_tool_results.append({
                "id": f"result-{tc_id}",
                "role": "tool",
                "content": m.get("result", ""),
                "toolCallId": tc_id,
            })
        elif role == "assistant":
            # Attach any pending tool calls to THIS assistant message
            msg: dict[str, Any] = {
                "id": m.get("messageId", str(uuid.uuid4())),
                "role": "assistant",
                "content": m.get("content", ""),
            }
            if pending_tool_calls:
                msg["toolCalls"] = pending_tool_calls[:]
                agui.append(msg)
                agui.extend(pending_tool_results)
                pending_tool_calls.clear()
                pending_tool_results.clear()
            else:
                agui.append(msg)
        elif role == "user":
            agui.append({
                "id": m.get("messageId", str(uuid.uuid4())),
                "role": "user",
                "content": m.get("content", ""),
            })
        elif role == "compaction":
            # Use "system" role for AG-UI protocol compatibility.
            # Encode compaction metadata in the content field with a
            # recognizable prefix so it survives Pydantic serialization
            # (AG-UI strips unknown fields from message dicts).
            count = m.get("compactedCount", 0)
            kept = m.get("keptCount", 0)
            summary = m.get("content", "")
            agui.append({
                "id": m.get("messageId", str(uuid.uuid4())),
                "role": "system",
                "content": f"[COMPACTION:{count}:{kept}]\n{summary}",
            })
        # Skip other roles (system, etc.)

    # Flush any trailing tool calls (run was interrupted before assistant responded)
    if pending_tool_calls:
        # No assistant message to attach to — emit as a bare assistant with just tool calls
        agui.append({
            "id": str(uuid.uuid4()),
            "role": "assistant",
            "content": "",
            "toolCalls": pending_tool_calls,
        })
        agui.extend(pending_tool_results)

    return agui


# ── SSE Tail Generator ────────────────────────────────────────────────────


async def _tail_events(thread_id: str, after_cursor: int = 0, keepalive_interval: float = 15.0):
    """Yield SSE events from the run tracker, with keepalive comments."""
    tracker = get_run_tracker()
    cursor = after_cursor

    while True:
        run = tracker.get_run(thread_id)
        if run is None:
            break

        events = await run.wait_for_events(cursor, timeout=keepalive_interval)
        if events:
            for c, event_str in events:
                cursor = c
                yield event_str
        else:
            yield ": keepalive\n\n"

        # Exit once run is finished and all events are drained
        if run.status != "running":
            remaining = run.get_events_after(cursor)
            for c, event_str in remaining:
                yield event_str
            break


async def _stream_with_snapshot(thread_id: str, after_cursor: int = 0):
    """Emit a MessagesSnapshot from session history, then tail live events."""
    # Load session history and emit snapshot
    session = await sessions.get_session(thread_id)
    raw_msgs = session.get("messages", []) if session else []
    if raw_msgs:
        sorted_msgs = sorted(raw_msgs, key=lambda m: m.get("timestamp", ""))
        agui_msgs = _session_messages_to_agui(sorted_msgs)
    else:
        agui_msgs = []

    emitter = AgentEventEmitter(thread_id)
    yield emitter.messages_snapshot(agui_msgs)

    # Then tail live events
    async for event_str in _tail_events(thread_id, after_cursor=after_cursor):
        yield event_str


# ── AG-UI Agent Endpoint ──────────────────────────────────────────────────


class AgentRequest(BaseModel):
    thread_id: str | None = None
    threadId: str | None = None  # camelCase alias for AG-UI client compat
    run_id: str | None = None
    runId: str | None = None  # camelCase alias
    messages: list[dict[str, Any]] = []

    def get_thread_id(self) -> str:
        tid = self.thread_id or self.threadId
        if not tid:
            raise ValueError("thread_id or threadId is required")
        return tid

    def get_run_id(self) -> str | None:
        return self.run_id or self.runId


@agent_router.post("/agent")
async def run_agent(
    req: AgentRequest,
    request: Request,
) -> StreamingResponse:
    """AG-UI compatible agent endpoint. Starts background task and tails events."""
    providers: ProviderRegistry = request.app.state.providers
    hooks: HookRegistry = request.app.state.hooks
    tracker = get_run_tracker()

    thread_id = req.get_thread_id()
    run_id = req.get_run_id() or str(uuid.uuid4())

    # Extract user query
    user_query = ""
    if req.messages:
        last = req.messages[-1]
        content = last.get("content", "")
        if isinstance(content, str):
            user_query = content

    # Check for existing active run
    existing = tracker.get_run(thread_id)
    if existing and existing.status == "running":
        # Already running — emit snapshot then tail the existing run
        return StreamingResponse(
            _stream_with_snapshot(thread_id),
            media_type=_SSE_MEDIA_TYPE,
        )

    # No user message and no active run — return history snapshot only
    if not user_query:
        async def _history_only():
            emitter = AgentEventEmitter(thread_id, run_id)
            session = await sessions.get_session(thread_id)
            raw_msgs = session.get("messages", []) if session else []
            agui_msgs = _session_messages_to_agui(
                sorted(raw_msgs, key=lambda m: m.get("timestamp", ""))
            ) if raw_msgs else []
            yield emitter.messages_snapshot(agui_msgs)
            yield emitter.run_started()
            yield emitter.run_finished()
        return StreamingResponse(_history_only(), media_type=_SSE_MEDIA_TYPE)

    # Launch agent loop as background task
    task = asyncio.create_task(
        _run_agent_loop(thread_id, run_id, req.messages, user_query, providers, hooks)
    )
    tracker.start_run(thread_id, run_id, task)

    return StreamingResponse(
        _stream_with_snapshot(thread_id),
        media_type=_SSE_MEDIA_TYPE,
    )


# ── Run Status & Reconnection ───────────────────────────────��─────────────


@agent_router.get("/agent/status/{thread_id}")
async def agent_status(thread_id: str) -> dict[str, Any]:
    """Check if an agent run is active for a thread."""
    run = get_run_tracker().get_run(thread_id)
    if run is None:
        raise HTTPException(404, "No active run")
    return {
        "running": run.status == "running",
        "status": run.status,
        "run_id": run.run_id,
        "cursor": run.cursor,
    }


@agent_router.get("/agent/events/{thread_id}")
async def agent_events(thread_id: str, after: int = 0) -> StreamingResponse:
    """Reconnectable SSE stream — replays missed events then tails live ones."""
    run = get_run_tracker().get_run(thread_id)
    if run is None:
        raise HTTPException(404, "No active run")
    return StreamingResponse(
        _tail_events(thread_id, after_cursor=after),
        media_type=_SSE_MEDIA_TYPE,
    )


@agent_router.post("/agent/cancel/{thread_id}")
async def agent_cancel(thread_id: str) -> dict[str, Any]:
    """Cancel an active agent run."""
    if not get_run_tracker().cancel_run(thread_id):
        raise HTTPException(404, "No active run to cancel")
    return {"ok": True, "cancelled": thread_id}


class GuardrailDecisionRequest(BaseModel):
    """User decision for a guardrail approval prompt."""
    approved: bool
    feedback: str | None = None


@agent_router.post("/agent/guardrail/{thread_id}/{approval_id}")
async def guardrail_decision(thread_id: str, approval_id: str, req: GuardrailDecisionRequest) -> dict[str, Any]:
    """Receive user approval/denial for a guardrail prompt."""
    run = get_run_tracker().get_run(thread_id)
    if run is None:
        raise HTTPException(404, "No active run")
    approval_event = run.guardrail_approvals.get(approval_id)
    if approval_event is None:
        raise HTTPException(404, "No pending guardrail approval with this ID")
    run.guardrail_decisions[approval_id] = {
        "approved": req.approved,
        "feedback": req.feedback,
    }
    approval_event.set()
    return {"ok": True, "approved": req.approved}


class CallbackRequest(BaseModel):
    """Final response from OpenClaw."""
    text: str = ""
    message_id: str | None = None


@agent_router.post("/agent/callback/{thread_id}")
async def agent_callback(thread_id: str, req: CallbackRequest) -> dict[str, Any]:
    """Receive final agent response (e.g. from OpenClaw) and emit to tracker."""
    tracker = get_run_tracker()
    run = tracker.get_run(thread_id)
    if run is None:
        raise HTTPException(404, "No active run")

    emitter = AgentEventEmitter(thread_id, run.run_id)
    msg_id = req.message_id or str(uuid.uuid4())

    if req.text:
        tracker.append_event(thread_id, emitter.text_message_start(msg_id))
        tracker.append_event(thread_id, emitter.text_delta(req.text, msg_id))
        tracker.append_event(thread_id, emitter.text_message_end(msg_id))
        # Note: don't persist here — OpenClaw's own persist callback
        # (POST /chat/sessions/{id}/message) already handles storage.

    tracker.append_event(thread_id, emitter.run_finished())
    tracker.finish_run(thread_id)
    return {"ok": True}


class QueueMessageRequest(BaseModel):
    text: str


@agent_router.post("/agent/message/{thread_id}")
async def agent_queue_message(thread_id: str, req: QueueMessageRequest) -> dict[str, Any]:
    """Queue a message for the running agent loop."""
    if not get_run_tracker().queue_message(thread_id, req.text):
        raise HTTPException(404, "No active run")
    return {"ok": True, "queued": True}


# ── Session CRUD ────────────────────────────────────────────────���───────────


class CreateSessionRequest(BaseModel):
    project_id: str | None = None
    title: str = "New Chat"
    dataset_ids: list[str] | None = None
    tool_ids: list[str] | None = None
    skill_ids: list[str] | None = None
    subagent_ids: list[str] | None = None


@router.get("/sessions")
async def list_chat_sessions(project_id: str | None = None) -> list[dict[str, Any]]:
    return await sessions.list_sessions(project_id)


@router.post("/sessions")
async def create_chat_session(req: CreateSessionRequest) -> dict[str, Any]:
    dataset_ids = req.dataset_ids
    project_id = req.project_id
    session_id: str | None = None

    # Auto-create a session-scoped project so notebooks and files have a home
    if not project_id:
        from dataclaw_projects.registry import create_project
        from dataclaw.config.paths import workspaces_dir

        session_id = str(uuid.uuid4())
        project = create_project(
            name=req.title or "New Chat",
            directory=str(workspaces_dir() / session_id),
        )
        project_id = project["id"]

    # Seed from project defaults if not explicitly provided
    tool_ids = req.tool_ids
    skill_ids = req.skill_ids
    subagent_ids = req.subagent_ids
    if project_id:
        try:
            from dataclaw_projects.registry import get_project
            proj = get_project(project_id)
            if dataset_ids is None:
                dataset_ids = proj.get("dataset_ids")
            if tool_ids is None:
                tool_ids = proj.get("tool_ids")
            if skill_ids is None:
                skill_ids = proj.get("skill_ids")
            if subagent_ids is None:
                subagent_ids = proj.get("subagent_ids")
        except Exception:
            pass

    return await sessions.create_session(
        session_id=session_id, project_id=project_id,
        title=req.title, dataset_ids=dataset_ids,
        tool_ids=tool_ids, skill_ids=skill_ids, subagent_ids=subagent_ids,
    )


@router.get("/sessions/{session_id}")
async def get_chat_session(session_id: str) -> dict[str, Any]:
    session = await sessions.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


class UpdateSessionRequest(BaseModel):
    title: str | None = None
    datasetIds: list[str] | None = None
    toolIds: list[str] | None = None
    skillIds: list[str] | None = None
    subagentIds: list[str] | None = None
    autoMode: bool | None = None
    autoMessage: str | None = None
    maxAutoTurns: int | None = None
    autoTurnsUsed: int | None = None


@router.patch("/sessions/{session_id}")
async def update_chat_session(session_id: str, req: UpdateSessionRequest) -> dict[str, Any]:
    updates = req.model_dump(exclude_unset=True)

    # Reset the auto-turn counter when auto-mode flips false → true so each
    # enable starts with a fresh budget. (Don't reset on changes to
    # maxAutoTurns or autoMessage alone, and don't reset if it's already on.)
    if updates.get("autoMode") is True and "autoTurnsUsed" not in updates:
        existing = await sessions.get_session(session_id)
        if existing is not None and not existing.get("autoMode"):
            updates["autoTurnsUsed"] = 0

    result = await sessions.update_session(session_id, updates)
    if result is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return result


@router.delete("/sessions/{session_id}")
async def delete_chat_session(session_id: str) -> dict[str, str]:
    deleted = await sessions.delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": "deleted"}


class IncomingMessage(BaseModel):
    """Message from OpenClaw's persist callback."""
    role: str = "assistant"
    content: str = ""
    messageId: str | None = None


@router.post("/sessions/{session_id}/message")
async def receive_message(session_id: str, msg: IncomingMessage) -> dict[str, Any]:
    """Persist a message to a session. Used by OpenClaw's fire-and-forget callback."""
    await sessions.append_message(session_id, {
        "role": msg.role,
        "content": msg.content,
        **({"messageId": msg.messageId} if msg.messageId else {}),
    })
    return {"ok": True}
