from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from dataclaw.providers.llm.provider import TextDeltaEvent, TurnCompleteEvent
from dataclaw.providers.agent.factory import build_utility_llm
from dataclaw.schema import Message
from dataclaw.storage.runtime_runs import RuntimeRunStore
from dataclaw_hermes.agent_provider import HermesAgentProvider
from dataclaw_hermes.agent_provider import _wire_messages
from dataclaw_hermes.client import HermesAPIError, HermesClient
from dataclaw_hermes.config import (
    HERMES_COMPAT_REVISION,
    HERMES_COMPAT_TAG,
    HERMES_COMPAT_VERSION,
    HermesConfig,
)
from dataclaw_hermes.health import verify_compatibility
from dataclaw_hermes.identity import decode_correlation, encode_correlation
from dataclaw_hermes.eval import _summarize_output
from dataclaw_hermes.installer import (
    _provider_auth_status,
    _restricted_profile,
    _write_restricted_profile,
    check_installation,
    extension_environment,
    restart_hermes_gateway,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _config(**changes) -> HermesConfig:
    config = HermesConfig(
        url="http://127.0.0.1:8642",
        api_key="test-hermes-api-key",
        dataclaw_api_url="http://127.0.0.1:8000",
        profile="dataclaw",
        model="route",
        provider="",
        utility_backend="openai",
        utility_model="gpt-4o-mini",
        cli_path="hermes",
        request_timeout_seconds=60,
        reconnect_timeout_seconds=30,
        tool_callback_timeout_seconds=330,
    )
    return replace(config, **changes)


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def test_pinned_compatibility_metadata_is_exact() -> None:
    metadata = _fixture("compatibility.json")
    assert metadata["version"] == HERMES_COMPAT_VERSION
    assert metadata["tag"] == HERMES_COMPAT_TAG
    assert metadata["revision"] == HERMES_COMPAT_REVISION
    assert metadata["contracts"]["utilityLLMFullContract"] is False
    assert metadata["contracts"]["eventReplay"] is False


def test_config_requires_real_utility_model_and_rejects_provider_override() -> None:
    _config().validate()
    with pytest.raises(ValueError, match="requires API_SERVER_KEY"):
        _config(api_key="").validate()
    with pytest.raises(ValueError, match="raw utility LLM contract"):
        _config(utility_backend="", utility_model="").validate()
    with pytest.raises(ValueError, match="does not accept a provider override"):
        _config(provider="openrouter").validate()
    with pytest.raises(ValueError, match="at least 305"):
        _config(tool_callback_timeout_seconds=304).validate()


@pytest.mark.parametrize(
    ("backend", "model"),
    [
        ("anthropic", "claude-sonnet-4-5"),
        ("openai", "gpt-4o-mini"),
        ("gemini", "gemini-2.5-flash"),
        ("codex", "gpt-5.5"),
    ],
)
def test_utility_auth_failure_identifies_dataclaw_utility_model(
    monkeypatch: pytest.MonkeyPatch,
    backend: str,
    model: str,
) -> None:
    def _fail(**kwargs):
        del kwargs
        raise ValueError(
            "Codex auth_mode is 'api_key' but no API key provided"
        )

    monkeypatch.setattr(
        "dataclaw.providers.llm.implementations.factory.llm_from_config",
        _fail,
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "DataClaw utility model could not initialize "
            rf"\({re.escape(backend)}/{re.escape(model)}\).*auth_mode"
        ),
    ):
        build_utility_llm(backend, model)


@pytest.mark.parametrize(
    ("backend", "env_var"),
    [
        ("anthropic", "ANTHROPIC_API_KEY"),
        ("openai", "OPENAI_API_KEY"),
        ("gemini", "GOOGLE_API_KEY"),
    ],
)
def test_missing_utility_credentials_identify_backend(
    monkeypatch: pytest.MonkeyPatch,
    backend: str,
    env_var: str,
) -> None:
    from dataclaw.config.resolver import invalidate_cache

    monkeypatch.delenv(env_var, raising=False)
    invalidate_cache()

    with pytest.raises(
        RuntimeError,
        match=(
            rf"DataClaw utility model could not initialize \({backend}/utility-model\).*"
            rf"API key is not configured.*{env_var}.*llm\.backends\.{backend}\.api_key"
        ),
    ):
        build_utility_llm(backend, "utility-model")


@pytest.mark.parametrize(
    ("provider", "output", "expected"),
    [
        ("openai-codex", "openai-codex: logged in\n", True),
        ("anthropic", "anthropic: logged out\n", False),
        ("openrouter", "openrouter: logged in\n", True),
        ("copilot-acp", "copilot-acp: logged out (CLI not found)\n", False),
    ],
)
def test_provider_auth_status_is_provider_agnostic(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    output: str,
    expected: bool,
) -> None:
    calls: list[list[str]] = []

    def _run(command: list[str], **kwargs):
        del kwargs
        calls.append(command)
        return SimpleNamespace(stdout=output, stderr="", returncode=0)

    monkeypatch.setattr(
        "dataclaw_hermes.installer.subprocess.run",
        _run,
    )

    configured, detail = _provider_auth_status(
        "/opt/hermes/bin/hermes",
        _config(profile="dataclaw"),
        provider,
    )

    assert configured is expected
    assert detail == output.strip()
    assert calls == [
        [
            "/opt/hermes/bin/hermes",
            "-p",
            "dataclaw",
            "auth",
            "status",
            provider,
        ]
    ]


def test_wire_history_preserves_tool_speaker_roles() -> None:
    messages = [
        Message.tool_call(
            [
                {
                    "type": "tool_call",
                    "id": "call-1",
                    "name": "echo",
                    "input": {},
                }
            ]
        ),
        Message.tool_result(
            [
                {
                    "type": "tool_result",
                    "call_id": "call-1",
                    "content": "ok",
                    "is_error": False,
                }
            ]
        ),
    ]
    assert [item["role"] for item in _wire_messages(messages)] == [
        "assistant",
        "user",
    ]


class _CompatibilityClient:
    def __init__(self, *, toolsets: dict | None = None) -> None:
        self._toolsets = toolsets or _fixture("toolsets.json")

    async def health(self):
        return _fixture("health.json")

    async def capabilities(self):
        return _fixture("capabilities.json")

    async def toolsets(self):
        return self._toolsets


@pytest.mark.asyncio
async def test_health_requires_exact_version_capabilities_and_tool_exposure() -> None:
    result = await verify_compatibility(_CompatibilityClient())
    assert result["tools"] == ["dataclaw_tool", "dataclaw_tool_search"]

    bad = _fixture("toolsets.json")
    bad["data"][1]["enabled"] = True
    with pytest.raises(RuntimeError, match="only the dataclaw toolset"):
        await verify_compatibility(_CompatibilityClient(toolsets=bad))


@pytest.mark.asyncio
async def test_http_client_uses_bearer_auth_and_parses_sse() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/health":
            return httpx.Response(200, json=_fixture("health.json"))
        if request.url.path == "/v1/runs":
            return httpx.Response(
                202, json={"run_id": "hrun-1", "status": "started"}
            )
        if request.url.path == "/v1/runs/hrun-1/events":
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text=(
                    ': keepalive\n\n'
                    'data: {"event":"message.delta",\n'
                    'data: "run_id":"hrun-1","delta":"ok"}\n\n'
                    'data: {"event":"run.completed","run_id":"hrun-1"}\n\n'
                ),
            )
        raise AssertionError(request.url.path)

    client = HermesClient(
        _config(api_key="secret"),
        transport=httpx.MockTransport(handler),
    )
    assert (await client.health())["version"] == HERMES_COMPAT_VERSION
    assert (await client.create_run({"input": "hello"}))["run_id"] == "hrun-1"
    events = [
        event async for event in client.stream_run_events("hrun-1")
    ]
    await client.aclose()

    assert [event["event"] for event in events] == [
        "message.delta",
        "run.completed",
    ]
    assert all(
        request.headers["authorization"] == "Bearer secret"
        for request in requests
    )


class _RunsClient:
    def __init__(self, events: list[dict], status: str = "running") -> None:
        self.events = events
        self.status_value = status
        self.payload: dict | None = None

    async def create_run(self, payload):
        self.payload = payload
        return {"run_id": "hrun-1", "status": "started"}

    async def stream_run_events(self, runtime_run_id):
        assert runtime_run_id == "hrun-1"
        for event in self.events:
            yield event

    async def status(self, runtime_run_id):
        return {"run_id": runtime_run_id, "status": self.status_value}

    async def aclose(self):
        return None


@pytest.mark.asyncio
async def test_agent_streams_fixture_and_sends_each_message_once(tmp_path) -> None:
    events = [
        json.loads(line)
        for line in (FIXTURES / "events.jsonl").read_text().splitlines()
    ]
    client = _RunsClient(events)
    store = RuntimeRunStore(tmp_path / "runtime")
    provider = HermesAgentProvider(client, _config(), store)
    state = {
        "run_id": "dc-run",
        "session_id": "session",
        "project_id": "project",
        "messages": [Message.user("Question")],
        "tools": [
            {
                "name": "echo",
                "description": "Echo",
                "parameters": {"type": "object", "properties": {}},
            }
        ],
        "metadata": {},
    }

    output = [event async for event in provider.stream_turn(state)]
    assert [event.text for event in output if isinstance(event, TextDeltaEvent)] == [
        "Hello ",
        "world",
    ]
    assert isinstance(output[-1], TurnCompleteEvent)
    assert client.payload["input"] == [
        {"role": "user", "content": "Question"}
    ]
    assert "provider" not in client.payload
    assert "dataclaw_tool" in client.payload["instructions"]
    record = await store.get_run("dc-run")
    assert record["runtimeRunId"] == "hrun-1"
    assert record["status"] == "completed"


@pytest.mark.asyncio
async def test_stream_drop_never_synthesizes_completion_from_status(tmp_path) -> None:
    client = _RunsClient([], status="completed")
    store = RuntimeRunStore(tmp_path / "runtime")
    provider = HermesAgentProvider(client, _config(), store)
    state = {
        "run_id": "dc-run",
        "session_id": "session",
        "project_id": None,
        "messages": [Message.user("Question")],
        "tools": [],
        "metadata": {},
    }

    with pytest.raises(HermesAPIError, match="stream ended"):
        _ = [event async for event in provider.stream_turn(state)]
    assert (await store.get_run("dc-run"))["status"] == "unknown"


def test_correlation_and_restricted_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    encoded = encode_correlation(
        run_id="run", session_id="session", project_id="project"
    )
    assert decode_correlation(encoded) == {
        "runId": "run",
        "sessionId": "session",
        "projectId": "project",
    }

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    config = _config()
    path = _write_restricted_profile(config)
    assert _restricted_profile(path)
    raw = path.read_text()
    assert "api_server:\n  - dataclaw" in raw
    assert "enabled:\n  - dataclaw" in raw
    assert "platforms:\n  api_server:\n    enabled: true" in raw
    assert "key: test-hermes-api-key" in raw
    assert "gateway:" not in raw
    assert extension_environment(config)[
        "DATACLAW_HERMES_TOOL_TIMEOUT_SECONDS"
    ] == "330"


def test_installation_status_reports_exact_cli_and_profile_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    executable = tmp_path / "bin" / "hermes"
    executable.parent.mkdir()
    executable.write_text("#!/bin/sh\n")
    executable.chmod(0o755)
    config = _config(cli_path=str(executable))
    profile_config = _write_restricted_profile(config)
    profile_config.write_text(
        profile_config.read_text()
        + "model:\n"
        + "  default: openai/gpt-5\n"
        + "  provider: openai\n"
    )
    def _run(command: list[str], **kwargs):
        del kwargs
        if "--version" in command:
            return SimpleNamespace(
                stdout=(
                    "Hermes Agent v0.19.0 (2026.7.20)\n"
                    "Python: 3.12.10\n"
                ),
                stderr="",
                returncode=0,
            )
        return SimpleNamespace(
            stdout="openai: logged in\n",
            stderr="",
            returncode=0,
        )

    monkeypatch.setattr(
        "dataclaw_hermes.installer.subprocess.run",
        _run,
    )

    status = check_installation(config)

    assert status["installed"] is True
    assert status["executable"] == str(executable)
    assert status["version"] == "0.19.0"
    assert status["version_compatible"] is True
    assert status["restricted_profile"] is True
    assert status["model_selected"] is True
    assert status["model_configured"] is True
    assert status["model"] == "openai/gpt-5"
    assert status["provider"] == "openai"
    assert status["provider_auth_configured"] is True
    assert status["provider_auth_detail"] == "openai: logged in"


@pytest.mark.parametrize(
    ("profile", "expected"),
    [
        ("dataclaw", ["-p", "dataclaw", "gateway", "restart"]),
        ("default", ["gateway", "restart"]),
    ],
)
def test_restart_gateway_uses_configured_executable_and_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    profile: str,
    expected: list[str],
) -> None:
    executable = tmp_path / "hermes"
    executable.write_text("#!/bin/sh\n")
    executable.chmod(0o755)
    calls: list[list[str]] = []

    def _run(command: list[str], **kwargs):
        calls.append(command)
        return SimpleNamespace(
            stdout="Service restarted\n",
            stderr="",
            returncode=0,
        )

    monkeypatch.setattr(
        "dataclaw_hermes.installer.subprocess.run", _run
    )

    result = restart_hermes_gateway(
        _config(cli_path=str(executable), profile=profile)
    )

    assert calls == [[str(executable), *expected]]
    assert result["status"] == "restarted"
    assert result["profile"] == profile


def test_native_batch_summary_is_machine_readable_and_scoped(
    tmp_path: Path,
) -> None:
    output = tmp_path / "data" / "run"
    output.mkdir(parents=True)
    (output / "batch_0.jsonl").write_text(
        json.dumps(
            {
                "completed": True,
                "partial": False,
                "api_calls": 2,
                "tool_stats": {
                    "dataclaw_tool": {
                        "count": 1,
                        "success": 1,
                        "failure": 0,
                    }
                },
            }
        )
        + "\n"
    )
    summary = _summarize_output(
        output_dir=output,
        expected=2,
        return_code=0,
        elapsed_seconds=1.25,
        cancelled=False,
        command=["python", "batch_runner.py"],
    )
    assert summary["status"] == "partial_failure"
    assert summary["failureRate"] == 0.5
    assert summary["apiCalls"] == 2
    assert summary["dataclawGovernanceCoverage"] is False
