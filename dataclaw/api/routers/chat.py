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

from dataclaw.api.run_tracker import RunState, get_run_tracker
from dataclaw.config.resolver import resolve
from dataclaw.events.emitter import AgentEventEmitter
from dataclaw.events.types import AGUI_MEDIA_TYPE
from dataclaw.hooks.base import HookError
from dataclaw.hooks.registry import HookRegistry
from dataclaw.plugins.registry import ProviderRegistry
from dataclaw.providers.llm.provider import PendingToolCall, TextDeltaEvent, ToolUseStartEvent, TurnCompleteEvent
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

    emit(emitter.run_started())

    try:
        messages = [Message.from_dict(m) for m in raw_messages]

        # Persist user message
        if user_query:
            await sessions.append_message(thread_id, {"role": "user", "content": user_query, "messageId": f"user-{run_id}"})

        # Resolve project_id from session metadata
        project_id: str | None = None
        try:
            session_data = await sessions.get_session(thread_id)
            if session_data:
                project_id = session_data.get("projectId")
        except Exception:
            pass

        # Run pipeline stages (hooks + providers) before agent call
        state: dict[str, Any] = {
            "session_id": thread_id,
            "project_id": project_id,
            "user_query": user_query,
            "messages": messages,
        }
        state = await hooks.run("userQueryHook", state)

        # Compaction
        compacted = await providers.compaction.compact(
            state.get("messages", messages),
            max_messages=int(resolve("compaction.max_messages", "DATACLAW_COMPACTION_MAX", "30")),
            keep_recent=int(resolve("compaction.keep_recent", "DATACLAW_COMPACTION_KEEP", "8")),
        )
        state["messages"] = compacted
        state = await hooks.run("postCompactionHook", state)

        # System prompt
        system_prompt = await providers.system_prompt.build_system_prompt(state)
        state["system_prompt"] = system_prompt
        state = await hooks.run("postSystemPromptHook", state)

        # Memory
        memories = await providers.memory.retrieve_memories(state)
        state["memories"] = memories
        state = await hooks.run("postMemoryHook", state)

        # Skills
        skills = await providers.skill.resolve_skills(state)
        fragments = await providers.skill.format_for_prompt(skills)
        state["skills"] = skills
        state["skill_prompt_fragments"] = fragments
        state = await hooks.run("postSkillHook", state)

        # Tool availability
        tool_defs, tool_callables = await providers.tool_availability.resolve_tools(state)
        state["tools"] = tool_defs
        state["tool_callables"] = tool_callables
        state = await hooks.run("postToolAvailabilityHook", state)

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
                state = await hooks.run("preToolCallHook", state)
                for i, tc in enumerate(pending):
                    patched = state.get("pending_tool_calls", [])[i] if i < len(state.get("pending_tool_calls", [])) else None
                    if patched:
                        pending[i] = PendingToolCall(
                            call_id=patched.get("call_id", tc.call_id),
                            tool_name=patched.get("tool_name", tc.tool_name),
                            tool_input=patched.get("tool_input", tc.tool_input),
                        )

                # Execute tools and collect results
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
                        emit(emitter.tool_call_result(tc.call_id, result_json, msg_id))
                        await sessions.append_message(thread_id, {
                            "role": "tool_call", "messageId": f"tc-{tc.call_id}",
                            "toolCallId": tc.call_id, "toolName": tc.tool_name,
                            "args": json.dumps(tc.tool_input, default=str),
                            "result": result_json, "status": "complete",
                        })
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

                # Build canonical messages and append to conversation
                new_msgs = providers.llm.build_tool_result_message(
                    pending, results_list, errors_list
                )
                state["messages"] = list(state["messages"]) + new_msgs
                state = await hooks.run("postToolCallHook", state)

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


# ── AG-UI Agent Endpoint ──────────────────────────────────────────────────


class AgentRequest(BaseModel):
    thread_id: str
    run_id: str | None = None
    messages: list[dict[str, Any]] = []


@agent_router.post("/agent")
async def run_agent(
    req: AgentRequest,
    request: Request,
) -> StreamingResponse:
    """AG-UI compatible agent endpoint. Starts background task and tails events."""
    providers: ProviderRegistry = request.app.state.providers
    hooks: HookRegistry = request.app.state.hooks
    tracker = get_run_tracker()

    thread_id = req.thread_id
    run_id = req.run_id or str(uuid.uuid4())

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
        # Already running — just tail the existing run
        return StreamingResponse(
            _tail_events(thread_id),
            media_type=AGUI_MEDIA_TYPE,
        )

    # Launch agent loop as background task
    task = asyncio.create_task(
        _run_agent_loop(thread_id, run_id, req.messages, user_query, providers, hooks)
    )
    tracker.start_run(thread_id, run_id, task)

    return StreamingResponse(
        _tail_events(thread_id),
        media_type=AGUI_MEDIA_TYPE,
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
        media_type=AGUI_MEDIA_TYPE,
    )


@agent_router.post("/agent/cancel/{thread_id}")
async def agent_cancel(thread_id: str) -> dict[str, Any]:
    """Cancel an active agent run."""
    if not get_run_tracker().cancel_run(thread_id):
        raise HTTPException(404, "No active run to cancel")
    return {"ok": True, "cancelled": thread_id}


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


@router.get("/sessions")
async def list_chat_sessions(project_id: str | None = None) -> list[dict[str, Any]]:
    return await sessions.list_sessions(project_id)


@router.post("/sessions")
async def create_chat_session(req: CreateSessionRequest) -> dict[str, Any]:
    # Seed dataset_ids from project defaults if not explicitly provided
    dataset_ids = req.dataset_ids
    if dataset_ids is None and req.project_id:
        try:
            from dataclaw_projects.registry import get_project
            project = get_project(req.project_id)
            dataset_ids = project.get("dataset_ids")
        except Exception:
            pass
    return await sessions.create_session(
        project_id=req.project_id, title=req.title, dataset_ids=dataset_ids,
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


@router.patch("/sessions/{session_id}")
async def update_chat_session(session_id: str, req: UpdateSessionRequest) -> dict[str, Any]:
    result = await sessions.update_session(session_id, req.model_dump(exclude_unset=True))
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
