"""BrowserSubAgentProvider — browser-use as a SubAgentProvider.

Wraps the browser-use Agent to run browser automation tasks through
the subagent delegation system. Browser-use manages its own internal
LLM loop and browser actions; this provider acts as a single-turn
wrapper that emits progress events and returns a standardized result.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

from dataclaw.providers.config_field import ConfigField
from dataclaw.providers.sub_agent.provider import SubAgentContext, SubAgentResult

from dataclaw_browser.tools import _create_llm

logger = logging.getLogger(__name__)


class BrowserSubAgentProvider:
    """Executes browser automation tasks via browser-use."""

    agent_type: str = "browser"

    @classmethod
    def config_schema(cls) -> list[ConfigField]:
        return [
            ConfigField(
                name="start_url",
                field_type="string",
                label="Start URL",
                description="Default starting URL for the browser",
            ),
            ConfigField(
                name="timeout",
                field_type="int",
                label="Timeout (sec)",
                description="Maximum time for the browser task",
                default=300,
            ),
            ConfigField(
                name="max_steps",
                field_type="int",
                label="Max Steps",
                description="Maximum browser actions per session",
                default=100,
            ),
            ConfigField(
                name="llm_provider",
                field_type="select",
                label="Browser LLM Provider",
                options=[
                    {"value": "anthropic", "label": "Anthropic"},
                    {"value": "openai", "label": "OpenAI"},
                    {"value": "gemini", "label": "Google Gemini"},
                ],
                default="anthropic",
            ),
            ConfigField(
                name="llm_model",
                field_type="string",
                label="Browser LLM Model",
                default="claude-sonnet-4-20250514",
            ),
            ConfigField(
                name="api_key",
                field_type="string",
                label="API Key (override)",
                description="Leave empty to use the environment variable for your provider (ANTHROPIC_API_KEY, OPENAI_API_KEY, or GOOGLE_API_KEY)",
            ),
        ]

    async def run(self, task: str, *, context: SubAgentContext) -> SubAgentResult:
        config = context.config
        emit = context.emit
        conversation_id = context.conversation_id or str(uuid.uuid4())
        subagent_name = context.definition.get("name", "browser")

        url = config.get("start_url", "")
        timeout = int(config.get("timeout", 300))
        max_steps = int(config.get("max_steps", 100))
        llm_provider = config.get("llm_provider", "anthropic")
        llm_model = config.get("llm_model", "claude-sonnet-4-20250514")
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
        timed_out = False
        errors: list[str] = []

        try:
            from browser_use import Agent as BrowserAgent, BrowserProfile
        except ImportError:
            return SubAgentResult(
                status="error",
                result="browser-use is not installed. Run: pip install browser-use",
                conversation_id=conversation_id,
            )

        llm = _create_llm(llm_provider, llm_model, api_key)
        if llm is None:
            return SubAgentResult(
                status="error",
                result=f"Unsupported LLM provider: {llm_provider}",
                conversation_id=conversation_id,
            )

        try:
            profile = BrowserProfile(headless=True)
            agent = BrowserAgent(
                task=task,
                llm=llm,
                browser_profile=profile,
                max_actions_per_step=max_steps,
                **({"directly_open_url": url} if url else {}),
            )

            result = await asyncio.wait_for(agent.run(), timeout=timeout)

            final_text = result.final_result() if hasattr(result, "final_result") else str(result)
            extracted = []
            if hasattr(result, "extracted_content"):
                extracted = result.extracted_content()

        except asyncio.TimeoutError:
            timed_out = True
            final_text = ""
            extracted = []
            errors.append(f"Timed out after {timeout}s")
        except Exception as e:
            logger.exception("Browser subagent error")
            final_text = ""
            extracted = []
            errors.append(str(e))

        duration = round(time.time() - start, 1)
        status = "error" if errors else "completed"

        # Build result text
        result_parts = []
        if final_text:
            result_parts.append(final_text)
        if extracted:
            result_parts.append(f"\n\nExtracted content:\n" + "\n---\n".join(str(c) for c in extracted))
        result_text = "".join(result_parts) or ("Timed out" if timed_out else "No result")

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
                "timed_out": timed_out,
                "errors": errors,
                "extracted_content": extracted,
            },
        )
