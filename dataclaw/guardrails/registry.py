"""Guardrail registry — evaluates guardrails and provides hooks for the pipeline."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from dataclaw.guardrails.base import Guardrail, GuardrailVerdict
from dataclaw.guardrails.config import (
    GuardrailConfig,
    ProjectGuardrailConfig,
    SessionGuardrailConfig,
    is_guardrail_enabled,
    load_global_guardrail_config,
    load_project_guardrail_config,
    session_guardrail_config_from_dict,
)
from dataclaw.state import AgentState

logger = logging.getLogger(__name__)


def _load_session_data(session_id: str) -> dict[str, Any] | None:
    """Load session JSON data synchronously (same pattern as tool config)."""
    if not session_id:
        return None
    try:
        import json as _json
        from dataclaw.config.paths import sessions_dir
        path = sessions_dir() / f"{session_id}.json"
        if not path.exists():
            return None
        return _json.loads(path.read_text())
    except Exception:
        return None


class GuardrailRegistry:
    """Holds guardrail instances and provides hook callables for the agent pipeline."""

    def __init__(self) -> None:
        self._guardrails: list[Guardrail] = []

    @property
    def guardrails(self) -> list[Guardrail]:
        return list(self._guardrails)

    def register(self, guardrail: Guardrail) -> None:
        """Register a guardrail."""
        self._guardrails.append(guardrail)
        logger.info("Registered guardrail %s (phase=%s, mode=%s)", guardrail.id, guardrail.phase, guardrail.mode)

    def unregister(self, guardrail_id: str) -> None:
        """Remove a guardrail by id."""
        self._guardrails = [g for g in self._guardrails if g.id != guardrail_id]

    # ── Config resolution ──────────────────────────────────────────────

    def _resolve_enabled(self, state: AgentState) -> list[Guardrail]:
        """Return only guardrails that are enabled for the current context."""
        global_config = load_global_guardrail_config()

        # Load project config if we have a project_id
        project_config: ProjectGuardrailConfig | None = None
        project_id = state.get("project_id")
        if project_id:
            try:
                from dataclaw_projects.registry import get_project
                project = get_project(project_id)
                project_dir = project.get("directory", "")
                if project_dir:
                    project_config = load_project_guardrail_config(Path(project_dir))
            except Exception:
                pass

        # Load session config (sync file read — same pattern as tool config)
        session_config: SessionGuardrailConfig | None = None
        session_id = state.get("session_id")
        if session_id:
            session_data = _load_session_data(session_id)
            if session_data:
                session_config = session_guardrail_config_from_dict(
                    session_data.get("guardrailConfig")
                )

        return [
            g for g in self._guardrails
            if is_guardrail_enabled(g.id, global_config, project_config, session_config)
        ]

    # ── Hook factories ─────────────────────────────────────────────────

    def as_pre_hook(self):
        """Return a Hook callable for preToolCallHook.

        Evaluates all enabled pre-phase guardrails against pending_tool_calls.
        Triggered calls are removed from pending_tool_calls and verdicts
        are appended to state["guardrail_verdicts"].
        """

        async def _pre_hook(state: AgentState) -> AgentState:
            enabled = self._resolve_enabled(state)
            pre_guardrails = [g for g in enabled if g.phase == "pre"]
            if not pre_guardrails:
                return state

            pending = list(state.get("pending_tool_calls", []))
            verdicts: list[dict[str, Any]] = list(state.get("guardrail_verdicts", []))
            kept: list[dict[str, Any]] = []

            for tc in pending:
                triggered = False
                for guardrail in pre_guardrails:
                    verdict = guardrail.evaluate(tc, state)
                    if verdict is not None:
                        verdicts.append(_verdict_to_dict(verdict))
                        triggered = True
                        logger.warning(
                            "Guardrail %s triggered on %s (call_id=%s): %s",
                            guardrail.id, tc.get("tool_name"), tc.get("call_id"), verdict.message,
                        )
                        break  # first matching guardrail wins
                if not triggered:
                    kept.append(tc)

            return {**state, "pending_tool_calls": kept, "guardrail_verdicts": verdicts}

        return _pre_hook

    def as_post_hook(self):
        """Return a Hook callable for postToolCallHook.

        Evaluates all enabled post-phase guardrails against tool_results.
        Triggered results have their content replaced with guardrail messages
        and verdicts are appended to state["guardrail_verdicts"].
        """

        async def _post_hook(state: AgentState) -> AgentState:
            enabled = self._resolve_enabled(state)
            post_guardrails = [g for g in enabled if g.phase == "post"]
            if not post_guardrails:
                return state

            results = list(state.get("tool_results", []))
            verdicts: list[dict[str, Any]] = list(state.get("guardrail_verdicts", []))

            for i, tr in enumerate(results):
                for guardrail in post_guardrails:
                    tc_with_result = {**tr}
                    verdict = guardrail.evaluate(tc_with_result, state)
                    if verdict is not None:
                        verdicts.append(_verdict_to_dict(verdict))
                        results[i] = {**tr, "result": verdict.message, "guardrail_redacted": True}
                        logger.warning(
                            "Guardrail %s triggered on result for %s (call_id=%s): %s",
                            guardrail.id, tr.get("tool_name"), tr.get("call_id"), verdict.message,
                        )
                        break  # first matching guardrail wins

            return {**state, "tool_results": results, "guardrail_verdicts": verdicts}

        return _post_hook


def _verdict_to_dict(v: GuardrailVerdict) -> dict[str, Any]:
    """Serialize a GuardrailVerdict to a plain dict for state storage."""
    d: dict[str, Any] = {
        "tool_call_id": v.tool_call_id,
        "guardrail_id": v.guardrail_id,
        "message": v.message,
        "mode": v.mode,
        "phase": v.phase,
        "severity": v.severity,
    }
    if v.original_result is not None:
        d["original_result"] = v.original_result
    return d
