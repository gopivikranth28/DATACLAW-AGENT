from __future__ import annotations

import importlib
import importlib.util
import json
from pathlib import Path
import sys
import types


BRIDGE_ROOT = (
    Path(__file__).resolve().parents[1]
    / "hermes-plugins"
    / "dataclaw"
)


def _bridge(monkeypatch):
    monkeypatch.syspath_prepend(str(BRIDGE_ROOT))
    correlation = importlib.import_module(
        "dataclaw_hermes_bridge.correlation"
    )
    tools = importlib.import_module("dataclaw_hermes_bridge.tools")
    return correlation, tools


def test_bridge_callbacks_send_dataclaw_token(monkeypatch) -> None:
    _, tools = _bridge(monkeypatch)
    catalog = importlib.import_module("dataclaw_hermes_bridge.catalog")
    monkeypatch.setenv("DATACLAW_TOKEN", "tok")
    assert tools._settings()[2] == {"X-Dataclaw-Token": "tok"}
    assert catalog._settings()[2] == {"X-Dataclaw-Token": "tok"}
    monkeypatch.delenv("DATACLAW_TOKEN")
    assert tools._settings()[2] == {}


def test_directory_plugin_loads_under_hermes_namespace() -> None:
    """Match Hermes 0.19's directory-plugin import semantics."""
    parent_name = "hermes_plugins"
    module_name = f"{parent_name}.dataclaw_test"
    parent = types.ModuleType(parent_name)
    parent.__path__ = []
    parent.__package__ = parent_name
    sys.modules[parent_name] = parent
    spec = importlib.util.spec_from_file_location(
        module_name,
        BRIDGE_ROOT / "__init__.py",
        submodule_search_locations=[str(BRIDGE_ROOT)],
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    module.__package__ = module_name
    module.__path__ = [str(BRIDGE_ROOT)]
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
        assert callable(module.register)
    finally:
        for name in list(sys.modules):
            if name == parent_name or name.startswith(f"{module_name}."):
                sys.modules.pop(name, None)
        sys.modules.pop(module_name, None)


def test_correlation_round_trip_from_adapter(monkeypatch) -> None:
    from dataclaw_hermes.identity import encode_correlation

    correlation, _tools = _bridge(monkeypatch)
    encoded = encode_correlation(
        run_id="dc-run",
        session_id="session",
        project_id="project",
    )
    assert correlation.decode_correlation(encoded) == {
        "runId": "dc-run",
        "sessionId": "session",
        "projectId": "project",
    }


def test_stable_tool_call_id_reaches_callback(
    monkeypatch,
) -> None:
    from dataclaw_hermes.identity import encode_correlation

    _correlation, tools = _bridge(monkeypatch)
    requests: list[tuple[str, str, dict | None]] = []

    class _Response:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    class _Client:
        def __init__(self, **kwargs):
            requests.append(("client", str(kwargs["timeout"]), None))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, path):
            requests.append(("get", path, None))
            return _Response({"runtimeRunId": "hrun"})

        def post(self, path, json):
            requests.append(("post", path, json))
            return _Response(
                {
                    "state": "completed",
                    "isError": False,
                    "content": {"ok": True},
                    "guardrailId": None,
                }
            )

    monkeypatch.setattr(tools.httpx, "Client", _Client)
    monkeypatch.setenv("DATACLAW_API_URL", "http://127.0.0.1:8000")
    monkeypatch.setenv("DATACLAW_HERMES_TOOL_TIMEOUT_SECONDS", "330")
    encoded = encode_correlation(
        run_id="dc-run",
        session_id="session",
        project_id="project",
    )
    tools.capture_tool_call_id("dataclaw_tool", "stable-call-id")
    result = json.loads(
        tools.dispatch_tool(
            {"tool_name": "echo", "params": {"value": 1}},
            task_id=encoded,
        )
    )

    assert result["state"] == "completed"
    callback = next(item for item in requests if item[0] == "post")
    assert callback[2] == {
        "runtimeRunId": "hrun",
        "toolCallId": "stable-call-id",
        "runId": "dc-run",
        "sessionId": "session",
        "projectId": "project",
        "params": {"value": 1},
    }
    assert requests[0] == ("client", "330.0", None)
