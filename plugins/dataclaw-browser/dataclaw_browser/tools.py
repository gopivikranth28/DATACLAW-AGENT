"""Browser automation tool — AI-driven web browsing via browser-use.

The browser-use library is imported lazily to avoid slowing down
plugin loading when the tool is disabled.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


async def browser_use(
    *,
    task: str,
    url: str = "",
    timeout: int = 300,
    max_steps: int = 100,
    save_to: str = "",
    workspace_id: str = "default",
    enabled: bool = True,
    llm_provider: str = "anthropic",
    llm_model: str = "claude-sonnet-4-20250514",
    api_key: str = "",
    timeout_max: int = 600,
    **kw: Any,
) -> dict[str, Any]:
    """Use a browser to complete a task."""
    if not enabled:
        return {"error": "Browser tool is disabled. Enable it in Config > Browser."}

    effective_timeout = min(max(timeout, 1), timeout_max)

    try:
        from browser_use import Agent as BrowserAgent, BrowserProfile
    except ImportError:
        return {"error": "browser-use is not installed. Run: pip install browser-use"}

    # Set up LLM
    llm = _create_llm(llm_provider, llm_model, api_key)
    if llm is None:
        return {"error": f"Unsupported LLM provider: {llm_provider}"}

    start = time.time()
    timed_out = False
    errors: list[str] = []

    try:
        initial_actions = []
        if url:
            initial_actions.append({"open_url": url})

        profile = BrowserProfile(headless=True)
        agent = BrowserAgent(
            task=task,
            llm=llm,
            browser_profile=profile,
            max_actions_per_step=max_steps,
            initial_actions=initial_actions,
        )

        result = await asyncio.wait_for(
            agent.run(),
            timeout=effective_timeout,
        )

        final_text = result.final_result() if hasattr(result, "final_result") else str(result)
        extracted = []
        if hasattr(result, "extracted_content"):
            extracted = result.extracted_content()

    except asyncio.TimeoutError:
        timed_out = True
        final_text = ""
        extracted = []
        errors.append(f"Timed out after {effective_timeout}s")
    except Exception as e:
        logger.exception("Browser tool error")
        final_text = ""
        extracted = []
        errors.append(str(e))

    duration = time.time() - start

    output: dict[str, Any] = {
        "task": task,
        "success": not errors and not timed_out,
        "result": final_text,
        "extracted_content": extracted,
        "duration_seconds": round(duration, 1),
        "timed_out": timed_out,
        "errors": errors,
    }

    # Save extracted content to workspace
    if save_to and extracted and not errors:
        try:
            from dataclaw.config.paths import workspaces_dir
            base = workspaces_dir() / workspace_id
            base.mkdir(parents=True, exist_ok=True)
            save_path = base / save_to
            save_path.parent.mkdir(parents=True, exist_ok=True)
            content = "\n\n---\n\n".join(str(c) for c in extracted)
            save_path.write_text(content, encoding="utf-8")
            output["saved_to"] = str(save_path)
        except Exception as e:
            errors.append(f"Failed to save: {e}")

    return output


def _create_llm(provider: str, model: str, api_key: str) -> Any:
    """Create an LLM instance for browser-use."""
    try:
        if provider == "anthropic":
            from langchain_anthropic import ChatAnthropic
            kwargs: dict[str, Any] = {"model": model}
            if api_key:
                kwargs["api_key"] = api_key
            return ChatAnthropic(**kwargs)
        elif provider == "openai":
            from langchain_openai import ChatOpenAI
            kwargs = {"model": model}
            if api_key:
                kwargs["api_key"] = api_key
            return ChatOpenAI(**kwargs)
    except Exception:
        return None
    return None
