"""Artifact plugin hooks."""

from __future__ import annotations

import json
from typing import Any

from dataclaw.state import AgentState
from dataclaw_artifacts.store import append_living_report_event


ARTIFACT_TOOLS = {
    "publish_artifact",
    "read_artifact",
    "list_artifacts",
    "export_artifact",
    "delete_artifact",
    "report_note",
}


async def artifact_context_hook(state: AgentState) -> AgentState:
    """Inject session/project context into artifact tool calls."""
    pending = state.get("pending_tool_calls", [])
    session_id = state.get("session_id", "")
    project_id = state.get("project_id", "")
    active_plan_step_id = str(state.get("active_plan_step_id") or "").strip()

    if not pending:
        return state

    updated = []
    for tc in pending:
        tool_name = tc.get("tool_name", "")
        tool_input = tc.get("tool_input", {})
        if tool_name in ARTIFACT_TOOLS:
            injected = dict(tool_input)
            if session_id and (not injected.get("session_id") or injected.get("session_id") == "default"):
                injected["session_id"] = session_id
            if project_id and not injected.get("project_id"):
                injected["project_id"] = project_id
            if tool_name in {"publish_artifact", "report_note"} and active_plan_step_id and not injected.get("plan_step_id"):
                injected["plan_step_id"] = active_plan_step_id
            tc = {**tc, "tool_input": injected}
        updated.append(tc)

    return {**state, "pending_tool_calls": updated}


async def artifact_capture_hook(state: AgentState) -> AgentState:
    """Capture useful tool results into the session living report."""
    session_id = state.get("session_id", "")
    if not session_id:
        return state

    project_id = state.get("project_id") or None
    for result in state.get("tool_results", []):
        if result.get("is_error"):
            continue
        tool_name = str(result.get("tool_name") or "")
        event = _event_for_tool_result(tool_name, result.get("tool_input", {}), _parse_result(result.get("result")))
        if event:
            append_living_report_event(session_id=session_id, project_id=project_id, event=event)
    return state


def _parse_result(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"text": raw[:2000]}
    return parsed if isinstance(parsed, dict) else {"value": parsed}


def _event_for_tool_result(tool_name: str, tool_input: dict[str, Any], result: dict[str, Any]) -> dict[str, Any] | None:
    if tool_name == "publish_artifact" and result.get("success"):
        session_id = str(tool_input.get("session_id") or result.get("session_id") or "")
        return {
            "kind": "artifact_published",
            "page": "analyses",
            "plan_step_id": str(tool_input.get("plan_step_id") or result.get("plan_step_id") or ""),
            "session_id": session_id,
            "status": "active",
            "payload": {
                "title": tool_input.get("title") or result.get("artifact_id"),
                "summary": tool_input.get("description", ""),
                "artifact_id": result.get("artifact_id"),
                "version": result.get("version"),
                "url": result.get("url"),
                "session_id": session_id,
            },
        }

    if tool_name in {"propose_plan", "update_plan"} and result:
        return {
            "kind": "plan_update",
            "page": "decisions",
            "status": "active",
            "payload": {
                "title": "Plan updated" if tool_name == "update_plan" else "Plan proposed",
                "proposal_id": result.get("proposal_id"),
                "snapshot_id": result.get("snapshot_id"),
                "status": result.get("status"),
                "summary": result.get("message") or tool_input.get("summary", ""),
            },
        }

    if tool_name == "display_metric" and result.get("type") == "metric":
        return {
            "kind": "metric",
            "page": "overview",
            "status": "active",
            "payload": {
                "title": result.get("label") or "Metric",
                "label": result.get("label"),
                "value": result.get("value"),
                "delta": result.get("delta"),
                "unit": result.get("unit"),
                "trend": result.get("trend"),
            },
        }

    if tool_name in {"execute_cell", "display_cell_output", "execute_code"}:
        outputs = result.get("outputs") if isinstance(result.get("outputs"), list) else []
        if not outputs:
            return None
        return {
            "kind": "cell_output",
            "page": "analyses",
            "status": "active",
            "payload": {
                "title": result.get("caption") or "Notebook output",
                "summary": f"Captured {len(outputs)} output item(s).",
                "cell_index": result.get("cell_index") or tool_input.get("cell_index"),
                "output_types": [o.get("type") for o in outputs if isinstance(o, dict)],
            },
        }

    if tool_name == "query_mlflow_runs" and isinstance(result.get("runs"), list):
        return {
            "kind": "mlflow_snapshot",
            "page": "models",
            "status": "active",
            "payload": {
                "title": "MLflow runs refreshed",
                "summary": f"Captured metadata for {len(result['runs'])} run(s).",
                "runs": result["runs"][:20],
            },
        }

    return None
