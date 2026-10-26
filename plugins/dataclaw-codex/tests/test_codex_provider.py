"""Codex sub-agent: registry default model, and API keys never touch os.environ."""

from __future__ import annotations

import os
import sys
import types
from typing import Any

import pytest

from dataclaw.providers.sub_agent.provider import SubAgentContext
from dataclaw_codex.provider import CodexSubAgentProvider


def _install_fake_codex(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    seen: dict[str, Any] = {}

    class AppServerConfig:
        def __init__(self, **kwargs: Any) -> None:
            seen["config"] = kwargs

    class _Thread:
        def run(self, task: str) -> Any:
            return types.SimpleNamespace(final_response=f"done: {task}", items=[])

    class Codex:
        def __init__(self, config: Any) -> None:
            pass

        def __enter__(self) -> "Codex":
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def thread_start(self, model: str) -> _Thread:
            seen["model"] = model
            return _Thread()

    sdk = types.ModuleType("codex_app_server")
    sdk.Codex = Codex  # type: ignore[attr-defined]
    client = types.ModuleType("codex_app_server.client")
    client.AppServerConfig = AppServerConfig  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "codex_app_server", sdk)
    monkeypatch.setitem(sys.modules, "codex_app_server.client", client)
    return seen


@pytest.mark.asyncio
async def test_api_key_goes_to_subprocess_env_only(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    seen = _install_fake_codex(monkeypatch)
    before = dict(os.environ)

    result = await CodexSubAgentProvider().run(
        "fix it",
        context=SubAgentContext(definition={}, config={"api_key": "sk-override", "codex_bin": "codex"}),
    )

    assert result.status == "completed"
    assert dict(os.environ) == before
    assert seen["config"]["env"] == {"OPENAI_API_KEY": "sk-override"}
    # No model configured: the codex backend default from the registry.
    assert seen["model"] == "gpt-5.5"


@pytest.mark.asyncio
async def test_no_override_key_leaves_env_unset(monkeypatch: pytest.MonkeyPatch):
    seen = _install_fake_codex(monkeypatch)

    await CodexSubAgentProvider().run(
        "task",
        context=SubAgentContext(definition={}, config={"model": "gpt-x", "codex_bin": "codex"}),
    )

    assert seen["config"]["env"] is None
    assert seen["model"] == "gpt-x"
