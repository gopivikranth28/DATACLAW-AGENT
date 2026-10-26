"""CodexSubAgentProvider — OpenAI Codex as a SubAgentProvider.

Wraps the Codex app-server SDK to run coding tasks through the
subagent delegation system. Codex manages its own internal agent
loop; this provider acts as a single-turn wrapper that emits
progress events and returns a standardized result.
"""

from __future__ import annotations

import logging
import shutil
import time
import uuid
from typing import Any

from dataclaw.providers.config_field import ConfigField
from dataclaw.providers.sub_agent.provider import SubAgentContext, SubAgentResult

logger = logging.getLogger(__name__)


def _default_model() -> str:
    """The codex backend's default model from DataClaw's LLM backend registry."""
    from dataclaw.providers.llm.registry import default_model_for

    return default_model_for("codex")


class CodexSubAgentProvider:
    """Executes coding tasks via OpenAI Codex."""

    agent_type: str = "codex"

    @classmethod
    def config_schema(cls) -> list[ConfigField]:
        return [
            ConfigField(
                name="model",
                field_type="string",
                label="Codex Model",
                description="Model to use for Codex tasks. Leave empty for the codex backend's default.",
            ),
            ConfigField(
                name="api_key",
                field_type="string",
                label="OpenAI API Key (override)",
                description="Leave empty to use OPENAI_API_KEY environment variable",
            ),
            ConfigField(
                name="codex_bin",
                field_type="string",
                label="Codex Binary Path",
                description="Path to the codex CLI binary",
                default=shutil.which("codex") or "codex",
            ),
            ConfigField(
                name="cwd",
                field_type="string",
                label="Working Directory",
                description="Directory Codex operates in. Leave empty to use the project directory.",
            ),
        ]

    async def run(self, task: str, *, context: SubAgentContext) -> SubAgentResult:
        config = context.config
        emit = context.emit
        conversation_id = context.conversation_id or str(uuid.uuid4())
        subagent_name = context.definition.get("name", "codex")

        model = config.get("model", "") or _default_model()
        api_key = config.get("api_key", "")

        # Emit start
        _emitter = None
        if emit:
            from dataclaw.events.emitter import AgentEventEmitter
            _emitter = AgentEventEmitter.__new__(AgentEventEmitter)
            _emitter.encoder = __import__("ag_ui.encoder", fromlist=["EventEncoder"]).EventEncoder()
            emit(_emitter.custom("subagent:started", {
                "name": subagent_name,
                "agent_type": self.agent_type,
                "task": task,
                "conversation_id": conversation_id,
            }))

        start = time.time()
        errors: list[str] = []

        try:
            from codex_app_server import Codex
        except ImportError:
            return SubAgentResult(
                status="error",
                result="codex_app_server is not installed. Install from: git+https://github.com/openai/codex.git#subdirectory=sdk/python",
                conversation_id=conversation_id,
            )

        try:
            from codex_app_server.client import AppServerConfig
            codex_bin = config.get("codex_bin", "") or shutil.which("codex") or "codex"
            cwd = config.get("cwd", "") or None
            # An override key goes to the Codex subprocess only; this
            # process's environment is left untouched.
            codex_config = AppServerConfig(
                codex_bin=codex_bin,
                cwd=cwd,
                env={"OPENAI_API_KEY": api_key} if api_key else None,
            )
            with Codex(config=codex_config) as codex:
                thread = codex.thread_start(model=model)
                result = thread.run(task)

                final_text = result.final_response or ""
                items_count = len(result.items) if hasattr(result, "items") else 0

        except Exception as e:
            logger.exception("Codex subagent error")
            final_text = ""
            items_count = 0
            errors.append(str(e))

        duration = round(time.time() - start, 1)
        status = "error" if errors else "completed"
        result_text = final_text or ("Error: " + "; ".join(errors) if errors else "No result")

        # Emit finish
        if emit and _emitter:
            emit(_emitter.custom("subagent:finished", {
                "name": subagent_name,
                "status": status,
                "turns_used": 1,
                "conversation_id": conversation_id,
                "duration_seconds": duration,
            }))

        return SubAgentResult(
            status=status,
            result=result_text,
            turns_used=1,
            conversation_id=conversation_id,
            metadata={
                "duration_seconds": duration,
                "items_count": items_count,
                "errors": errors,
            },
        )
