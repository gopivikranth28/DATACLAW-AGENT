"""OpenClaw ← OpenRouter provider configuration (service, endpoints, bootstrap).

Subprocesses and the OpenRouter catalog are faked; nothing here runs the real
CLI or touches the network.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

import dataclaw.config.paths as paths
import dataclaw_openclaw.openclaw_install_service as install_service
import dataclaw_openclaw.openrouter_config as orc
from dataclaw.api import security
from dataclaw_openclaw import model_router

KEY = "sk-or-v1-0123456789abcdef0123456789abcdef"
API_TOKEN = "api-token-123"
OPUS = "openrouter/anthropic/claude-opus-5.5"


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = tmp_path / ".dataclaw"
    home.mkdir()
    monkeypatch.setenv("DATACLAW_HOME", str(home))
    monkeypatch.setattr(paths, "DATACLAW_HOME", home)
    for var in ("DATACLAW_HOST", "DATACLAW_AUTH", "DATACLAW_TOKEN", "DATACLAW_ALLOWED_ORIGINS",
                orc.API_KEY_ENV_VAR, orc.MODEL_ENV_VAR):
        monkeypatch.delenv(var, raising=False)
    from dataclaw.config.resolver import invalidate_cache
    invalidate_cache()
    orc.reset_catalog_cache()
    yield
    orc.reset_catalog_cache()
    invalidate_cache()


# ── Fake openclaw CLI ───────────────────────────────────────────────────────


class FakeOpenClaw:
    """Records every ``openclaw`` invocation and answers from a small state."""

    def __init__(self, *, configured: bool = False, primary: str | None = None,
                 params: dict[str, Any] | None = None, fail: dict[str, tuple[int, str]] | None = None,
                 canonical: dict[str, str] | None = None):
        self.calls: list[dict[str, Any]] = []
        self.configured = configured
        self.primary = primary
        self.params = params or {}
        self.fail = fail or {}
        self.canonical = canonical or {}

    def respond(self, args: list[str], stdin: str | None, env: dict | None) -> tuple[int, str]:
        self.calls.append({"args": args, "stdin": stdin, "env": env})
        joined = " ".join(args)
        for prefix, result in self.fail.items():
            if joined.startswith(prefix):
                return result
        if args[:3] == ["models", "auth", "paste-api-key"]:
            self.configured = True
            return 0, "Auth profile: openrouter:manual (openrouter/api_key)\n"
        if args[:2] == ["models", "set"]:
            self.primary = self.canonical.get(args[2], args[2])
            return 0, f"Default model: {self.primary}\n"
        if args[:2] == ["models", "status"]:
            providers = []
            if self.configured:
                providers.append({
                    "provider": "openrouter",
                    "effective": {"kind": "profiles", "detail": "~/.openclaw/state/openclaw.sqlite"},
                    "profiles": {"count": 1, "labels": ["openrouter:manual=sk...ef"]},
                })
            return 0, "warning on stdout\n" + json.dumps({"auth": {"providers": providers}})
        if args[:2] == ["config", "get"]:
            path = args[2]
            if path == "agents.defaults.model":
                return (0, json.dumps({"primary": self.primary})) if self.primary else (1, "unset")
            if path == "agents.defaults.model.primary":
                return (0, json.dumps(self.primary)) if self.primary else (1, "unset")
            if path.endswith(".params"):
                return 0, json.dumps(self.params)
            return 1, "unset"
        if args[:2] == ["config", "set"]:
            return 0, "Updated config paths.\n"
        return 1, f"unexpected: {joined}"


@pytest.fixture
def fake_cli(monkeypatch: pytest.MonkeyPatch):
    holder: dict[str, FakeOpenClaw] = {"cli": FakeOpenClaw()}

    class _Proc:
        def __init__(self, rc: int, out: str):
            self.returncode = rc
            self._out = out

        async def communicate(self, data: bytes | None = None):
            return self._out.encode(), None

        def kill(self):
            pass

        async def wait(self):
            return self.returncode

    async def fake_exec(*argv, stdin=None, stdout=None, stderr=None, env=None, **_kw):
        assert argv[0] == "openclaw"
        proc_holder: dict[str, Any] = {}

        class _P(_Proc):
            async def communicate(self, data: bytes | None = None):
                rc, out = holder["cli"].respond(list(argv[1:]), data.decode() if data else None, env)
                self.returncode = rc
                return out.encode(), None

        proc_holder["p"] = _P(0, "")
        return proc_holder["p"]

    monkeypatch.setattr(orc.asyncio, "create_subprocess_exec", fake_exec)
    return holder


def _calls(cli: FakeOpenClaw, *prefix: str) -> list[dict[str, Any]]:
    return [c for c in cli.calls if c["args"][: len(prefix)] == list(prefix)]


# ── Model refs ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "ref", "upstream"),
    [
        (OPUS, OPUS, "anthropic/claude-opus-5.5"),
        ("anthropic/claude-opus-5.5", OPUS, "anthropic/claude-opus-5.5"),
        ("openrouter/auto", "openrouter/auto", "openrouter/auto"),
        ("auto", "openrouter/auto", "openrouter/auto"),
        # OpenClaw stores Fusion as openrouter/fusion; both spellings land there.
        ("openrouter/openrouter/fusion", "openrouter/fusion", "openrouter/fusion"),
        ("openrouter/fusion", "openrouter/fusion", "openrouter/fusion"),
        ("openrouter/~anthropic/claude-opus-latest", "openrouter/~anthropic/claude-opus-latest",
         "~anthropic/claude-opus-latest"),
        ("  meta-llama/llama-4:free ", "openrouter/meta-llama/llama-4:free", "meta-llama/llama-4:free"),
    ],
)
def test_normalize_model_ref(raw: str, ref: str, upstream: str) -> None:
    assert orc.normalize_model_ref(raw) == (ref, upstream)


@pytest.mark.parametrize(
    "raw",
    ["", "claude", "openrouter/", "openrouter/a/b/c", "anthropic/claude opus", "anthropic/claude;rm -rf",
     "Anthropic/claude", "/claude", "openrouter/" + "a" * 300, 'anthropic/x"]'],
)
def test_normalize_model_ref_rejects(raw: str) -> None:
    with pytest.raises(ValueError):
        orc.normalize_model_ref(raw)


def test_model_params_path_bracket_quotes_dotted_ref() -> None:
    assert orc.model_params_path(OPUS, "provider") == (
        'agents.defaults.models["openrouter/anthropic/claude-opus-5.5"].params.provider'
    )


def test_openrouter_id_from_ref() -> None:
    assert orc.openrouter_id_from_ref(OPUS) == "anthropic/claude-opus-5.5"
    assert orc.openrouter_id_from_ref("openrouter/auto") == "openrouter/auto"
    assert orc.openrouter_id_from_ref("anthropic/claude-opus-5.5") is None
    assert orc.openrouter_id_from_ref(None) is None


# ── Validation ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "routing",
    [
        {"sort": "bogus"},
        {"data_collection": "maybe"},
        {"zdr": "sometimes"},
        {"order": ["ok", "bad slug"]},
        {"only": ["x" * 80]},
        {"ignore": [f"p{i}" for i in range(40)]},
        {"max_price": {"prompt": 1}},  # not managed by Dataclaw
    ],
)
def test_routing_validation_rejects(routing: dict) -> None:
    with pytest.raises(ValidationError):
        orc.RoutingSettings.model_validate(routing)


def test_routing_dedupes_and_omits_unset_fields() -> None:
    routing = orc.RoutingSettings.model_validate(
        {"order": ["anthropic", "anthropic", "google-vertex"], "zdr": False}
    )
    assert routing.to_openrouter() == {"order": ["anthropic", "google-vertex"], "zdr": False}


@pytest.mark.parametrize("ttl", [0, 86401, -5])
def test_response_cache_ttl_bounds(ttl: int) -> None:
    with pytest.raises(ValidationError):
        orc.ResponseCacheSettings.model_validate({"enabled": True, "ttl_seconds": ttl})


@pytest.mark.parametrize(
    "body",
    [
        {"provider": "anthropic", "model": OPUS},
        {"provider": "openrouter", "model": "not a model"},
        {"provider": "openrouter", "model": OPUS, "api_key": "sk-or bad key"},
        {"provider": "openrouter", "model": OPUS, "extra": 1},
    ],
)
def test_model_config_request_rejects(body: dict) -> None:
    with pytest.raises(ValidationError):
        orc.ModelConfigRequest.model_validate(body)


def test_model_config_request_normalizes_model_and_blank_key() -> None:
    req = orc.ModelConfigRequest.model_validate(
        {"provider": "openrouter", "model": "anthropic/claude-opus-5.5", "api_key": "  "}
    )
    assert req.model == OPUS
    assert req.api_key is None
    assert KEY not in repr(orc.ModelConfigRequest.model_validate(
        {"provider": "openrouter", "model": OPUS, "api_key": KEY}
    ))


# ── Batch entries per option ────────────────────────────────────────────────


def test_build_entries_nothing_requested() -> None:
    assert orc.build_model_param_entries(OPUS, None, None) == []


@pytest.mark.parametrize(
    ("routing", "expected"),
    [
        ({"data_collection": "deny"}, {"data_collection": "deny"}),
        ({"zdr": True}, {"zdr": True}),
        ({"sort": "throughput"}, {"sort": "throughput"}),
        ({"order": ["anthropic", "amazon-bedrock"]}, {"order": ["anthropic", "amazon-bedrock"]}),
        ({"only": ["anthropic"]}, {"only": ["anthropic"]}),
        ({"ignore": ["deepinfra/fp8"]}, {"ignore": ["deepinfra/fp8"]}),
        ({"allow_fallbacks": False}, {"allow_fallbacks": False}),
        ({}, {}),  # clears every routing preference
    ],
)
def test_build_entries_routing_options(routing: dict, expected: dict) -> None:
    entries = orc.build_model_param_entries(OPUS, orc.RoutingSettings.model_validate(routing), None)
    assert entries == [{
        "path": 'agents.defaults.models["openrouter/anthropic/claude-opus-5.5"].params.provider',
        "value": expected,
    }]


def test_build_entries_response_cache() -> None:
    base = 'agents.defaults.models["openrouter/auto"].params'
    with_ttl = orc.build_model_param_entries(
        "openrouter/auto", None, orc.ResponseCacheSettings(enabled=True, ttl_seconds=300)
    )
    assert with_ttl == [
        {"path": f"{base}.responseCache", "value": True},
        {"path": f"{base}.responseCacheTtlSeconds", "value": 300},
    ]
    disabled = orc.build_model_param_entries("openrouter/auto", None, orc.ResponseCacheSettings(enabled=False))
    assert disabled == [{"path": f"{base}.responseCache", "value": False}]


# ── CLI argv / stdin ────────────────────────────────────────────────────────


async def test_apply_model_config_argv_and_key_on_stdin(fake_cli) -> None:
    cli = fake_cli["cli"]
    result = await orc.apply_model_config(
        ["openclaw"],
        model=OPUS,
        api_key=KEY,
        routing=orc.RoutingSettings(data_collection="deny", zdr=True, sort="price"),
        response_cache=orc.ResponseCacheSettings(enabled=True, ttl_seconds=600),
    )
    assert result == {"model": OPUS, "key_updated": True, "entries": 3}
    args = [c["args"] for c in cli.calls]
    assert args[0] == ["models", "auth", "paste-api-key", "--provider", "openrouter"]
    assert cli.calls[0]["stdin"] == KEY + "\n"
    assert args[1] == ["models", "set", OPUS]
    assert args[2] == ["config", "get", "agents.defaults.model.primary", "--json"]
    assert args[3][:3] == ["config", "set", "--batch-json"]
    assert json.loads(args[3][3]) == [
        {"path": f'agents.defaults.models["{OPUS}"].params.provider',
         "value": {"data_collection": "deny", "zdr": True, "sort": "price"}},
        {"path": f'agents.defaults.models["{OPUS}"].params.responseCache', "value": True},
        {"path": f'agents.defaults.models["{OPUS}"].params.responseCacheTtlSeconds', "value": 600},
    ]
    # The key only ever travels on stdin.
    assert not any(KEY in " ".join(c["args"]) for c in cli.calls)


async def test_apply_model_config_without_key_keeps_existing_credential(fake_cli) -> None:
    cli = fake_cli["cli"]
    await orc.apply_model_config(["openclaw"], model="openrouter/auto")
    assert not _calls(cli, "models", "auth")
    assert not _calls(cli, "config", "set")  # no params requested
    assert _calls(cli, "models", "set")[0]["args"] == ["models", "set", "openrouter/auto"]


async def test_params_are_keyed_on_the_ref_openclaw_stored(fake_cli) -> None:
    cli = fake_cli["cli"] = FakeOpenClaw(canonical={"openrouter/fusion": "openrouter/fusion"})
    await orc.apply_model_config(
        ["openclaw"], model="openrouter/openrouter/fusion",
        response_cache=orc.ResponseCacheSettings(enabled=True),
    )
    batch = json.loads(_calls(cli, "config", "set")[0]["args"][3])
    assert batch == [{"path": 'agents.defaults.models["openrouter/fusion"].params.responseCache', "value": True}]


async def test_status_check_hides_the_process_key(fake_cli, monkeypatch) -> None:
    monkeypatch.setenv(orc.API_KEY_ENV_VAR, KEY)
    assert await orc.is_credential_configured(["openclaw"]) is False
    env = _calls(fake_cli["cli"], "models", "status")[0]["env"]
    assert orc.API_KEY_ENV_VAR not in env


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ({"auth": {"providers": []}}, False),
        ({"auth": {"providers": [{"provider": "openrouter", "effective": {"kind": "profiles"}}]}}, True),
        ({"auth": {"providers": [{"provider": "openrouter", "effective": {"kind": "env"}}]}}, True),
        ({"auth": {"providers": [{"provider": "openrouter", "effective": {"kind": "missing"}}]}}, False),
        ({"auth": {"providers": [{"provider": "anthropic", "effective": {"kind": "profiles"}}]}}, False),
        (None, False),
    ],
)
def test_credential_configured_from_status(status: Any, expected: bool) -> None:
    assert orc.credential_configured_from_status(status) is expected


async def test_read_model_state_reports_boolean_only(fake_cli) -> None:
    fake_cli["cli"] = FakeOpenClaw(
        configured=True, primary=OPUS,
        params={"provider": {"zdr": True}, "responseCache": True, "responseCacheTtlSeconds": 120},
    )
    state = await orc.read_model_state(["openclaw"])
    assert state == {
        "provider": "openrouter",
        "model": OPUS,
        "openrouter_model": "anthropic/claude-opus-5.5",
        "configured": True,
        "env_key_available": False,
        "routing": {"zdr": True},
        "response_cache": {"enabled": True, "ttl_seconds": 120},
    }
    assert "sk..." not in json.dumps(state)


# ── Redaction ───────────────────────────────────────────────────────────────


def test_redact_known_and_key_shaped_values() -> None:
    text = f"bad key {KEY} and sk-or-v1-deadbeefcafe and token=abcd1234"
    out = orc.redact(text, ["abcd1234"])
    assert KEY not in out and "deadbeefcafe" not in out and "abcd1234" not in out
    assert out.count("****") == 3


async def test_paste_failure_error_is_redacted(fake_cli) -> None:
    fake_cli["cli"] = FakeOpenClaw(fail={"models auth paste-api-key": (1, f"Invalid key {KEY}\n")})
    with pytest.raises(orc.OpenClawCommandError) as exc:
        await orc.store_api_key(["openclaw"], KEY)
    assert KEY not in str(exc.value) and KEY not in exc.value.output
    assert "****" in str(exc.value)


async def test_stream_subprocess_redacts_secrets(monkeypatch) -> None:
    secret = "channel-token-xyz"

    class _Stdout:
        def __init__(self):
            self._lines = [f"echo {secret}\n".encode(), f"key {KEY}\n".encode()]

        def __aiter__(self):
            return self

        async def __anext__(self):
            if not self._lines:
                raise StopAsyncIteration
            return self._lines.pop(0)

    class _Proc:
        stdout = _Stdout()

        async def wait(self):
            return 1

    async def fake_exec(*_a, **_k):
        return _Proc()

    monkeypatch.setattr(install_service.asyncio, "create_subprocess_exec", fake_exec)
    events = [e async for e in install_service._stream_subprocess(["openclaw", "x"], secrets=[secret])]
    text = json.dumps(events)
    assert secret not in text and KEY not in text
    assert events[-1] == {"_rc": 1}


# ── Bundled entrypoint (env-driven) ─────────────────────────────────────────


async def test_bootstrap_stores_env_key_and_defaults_model(fake_cli) -> None:
    cli = fake_cli["cli"]
    lines = await orc.bootstrap_from_env(["openclaw"], {orc.API_KEY_ENV_VAR: KEY})
    assert _calls(cli, "models", "auth", "paste-api-key")[0]["stdin"] == KEY + "\n"
    assert _calls(cli, "models", "set")[0]["args"] == ["models", "set", orc.DEFAULT_MODEL_REF]
    assert KEY not in "\n".join(lines)


async def test_bootstrap_never_overwrites_an_existing_credential(fake_cli) -> None:
    cli = fake_cli["cli"] = FakeOpenClaw(configured=True, primary=OPUS)
    await orc.bootstrap_from_env(["openclaw"], {orc.API_KEY_ENV_VAR: KEY})
    assert not _calls(cli, "models", "auth")
    assert not _calls(cli, "models", "set")  # a model is already configured


async def test_bootstrap_applies_model_env(fake_cli) -> None:
    cli = fake_cli["cli"] = FakeOpenClaw(configured=True, primary="openrouter/auto")
    lines = await orc.bootstrap_from_env(["openclaw"], {orc.MODEL_ENV_VAR: "anthropic/claude-opus-5.5"})
    assert _calls(cli, "models", "set")[0]["args"] == ["models", "set", OPUS]
    assert lines[-1] == f"OpenClaw primary model: {OPUS}"


async def test_bootstrap_ignores_invalid_values(fake_cli) -> None:
    cli = fake_cli["cli"]
    lines = await orc.bootstrap_from_env(
        ["openclaw"], {orc.API_KEY_ENV_VAR: "has space", orc.MODEL_ENV_VAR: "nope"}
    )
    assert cli.calls == []
    assert len(lines) == 2 and all(line.startswith("warning:") for line in lines)


async def test_bootstrap_noop_without_env(fake_cli) -> None:
    assert await orc.bootstrap_from_env(["openclaw"], {}) == []
    assert fake_cli["cli"].calls == []


def test_bootstrap_script_entrypoint(fake_cli, monkeypatch, capsys) -> None:
    import importlib.util

    script = Path(__file__).resolve().parents[3] / "scripts" / "configure_openclaw_model.py"
    spec = importlib.util.spec_from_file_location("configure_openclaw_model", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv(orc.API_KEY_ENV_VAR, KEY)
    monkeypatch.setenv(orc.MODEL_ENV_VAR, OPUS)
    assert asyncio.run(module.main()) == 0
    out = capsys.readouterr()
    assert f"[openrouter] OpenClaw primary model: {OPUS}" in out.out
    assert KEY not in out.out + out.err


# ── OpenRouter catalog proxy ────────────────────────────────────────────────

CATALOG = {
    "data": [
        {"id": "anthropic/claude-opus-5.5", "name": "Anthropic: Claude Opus 5.5", "context_length": 1000000,
         "pricing": {"prompt": "0.000005", "completion": "0.000025"},
         "supported_parameters": ["tools", "reasoning"]},
        {"id": "anthropic/claude-opus-5.5:batch", "name": "batch", "pricing": {}},
        {"id": "openrouter/auto", "name": "Auto Router", "pricing": {"prompt": "-1"}},
        {"id": "~anthropic/claude-opus-latest", "name": "Latest Opus", "supported_parameters": []},
        {"id": "bad id with spaces", "name": "x"},
    ]
}


def _client(counter: dict[str, int], *, status: int = 200) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        counter["n"] += 1
        assert str(request.url) == orc.OPENROUTER_MODELS_URL
        return httpx.Response(status, json=CATALOG if status == 200 else {"error": "x"})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_catalog_summarizes_and_hides_batch() -> None:
    counter = {"n": 0}
    models, stale = await orc.fetch_openrouter_catalog(client=_client(counter))
    assert not stale
    ids = [m["id"] for m in models]
    assert ids == ["anthropic/claude-opus-5.5", "~anthropic/claude-opus-latest", "openrouter/auto"]
    opus = models[0]
    assert opus == {
        "id": "anthropic/claude-opus-5.5", "ref": OPUS, "name": "Anthropic: Claude Opus 5.5",
        "vendor": "anthropic", "context_length": 1000000, "prompt_price": "0.000005",
        "completion_price": "0.000025", "tools": True,
    }
    assert models[1]["vendor"] == "anthropic" and models[1]["ref"] == "openrouter/~anthropic/claude-opus-latest"
    assert models[2]["ref"] == "openrouter/auto"


async def test_catalog_is_cached_within_ttl(monkeypatch) -> None:
    counter = {"n": 0}
    now = {"t": 1000.0}
    monkeypatch.setattr(orc.time, "monotonic", lambda: now["t"])
    await orc.fetch_openrouter_catalog(client=_client(counter))
    now["t"] += orc.CATALOG_TTL_SECONDS - 1
    await orc.fetch_openrouter_catalog(client=_client(counter))
    assert counter["n"] == 1
    now["t"] += 2
    await orc.fetch_openrouter_catalog(client=_client(counter))
    assert counter["n"] == 2
    await orc.fetch_openrouter_catalog(client=_client(counter), force=True)
    assert counter["n"] == 3


async def test_catalog_serves_stale_on_failure_and_raises_when_empty(monkeypatch) -> None:
    counter = {"n": 0}
    with pytest.raises(httpx.HTTPError):
        await orc.fetch_openrouter_catalog(client=_client(counter, status=503))
    await orc.fetch_openrouter_catalog(client=_client(counter))
    models, stale = await orc.fetch_openrouter_catalog(client=_client(counter, status=503), force=True)
    assert stale and models[0]["id"] == "anthropic/claude-opus-5.5"


# ── HTTP endpoints (behind the API auth middleware) ─────────────────────────


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch, fake_cli):
    # A non-loopback bind requires the API token (same setup as test_api_security).
    monkeypatch.setenv("DATACLAW_HOST", "0.0.0.0")
    monkeypatch.setenv("DATACLAW_TOKEN", API_TOKEN)
    monkeypatch.setattr(model_router, "_get_openclaw_config", lambda _request: {})
    monkeypatch.setattr(model_router, "_openclaw_argv", lambda _cfg: ["openclaw"])

    async def fake_catalog(*, force: bool = False, client=None):
        return orc.summarize_catalog(CATALOG), False

    monkeypatch.setattr(orc, "fetch_openrouter_catalog", fake_catalog)
    app = FastAPI()
    app.add_middleware(security.SecurityMiddleware)
    app.include_router(model_router.router, prefix="/api/openclaw")
    return TestClient(app)


AUTH = {"authorization": f"Bearer {API_TOKEN}"}


def test_endpoints_require_the_api_token(api: TestClient) -> None:
    assert api.get("/api/openclaw/model").status_code == 401
    assert api.post("/api/openclaw/model", json={"provider": "openrouter", "model": OPUS}).status_code == 401
    assert api.get("/api/openclaw/openrouter/models").status_code == 401


def test_get_model(api: TestClient, fake_cli) -> None:
    fake_cli["cli"] = FakeOpenClaw(configured=True, primary=OPUS, params={"provider": {"sort": "price"}})
    body = api.get("/api/openclaw/model", headers=AUTH).json()
    assert body["model"] == OPUS and body["configured"] is True
    assert body["routing"] == {"sort": "price"}


def test_post_model_configures_openclaw(api: TestClient, fake_cli, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    resp = api.post("/api/openclaw/model", headers=AUTH, json={
        "provider": "openrouter", "api_key": KEY, "model": OPUS,
        "routing": {"data_collection": "deny", "zdr": True, "sort": "latency"},
        "response_cache": {"enabled": True, "ttl_seconds": 300},
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["model"] == OPUS and body["configured"] is True and body["key_updated"] is True
    assert body["warnings"] == []
    assert KEY not in resp.text and KEY not in caplog.text
    cli = fake_cli["cli"]
    assert _calls(cli, "models", "auth", "paste-api-key")[0]["stdin"] == KEY + "\n"
    assert len(json.loads(_calls(cli, "config", "set")[0]["args"][3])) == 3


def test_post_model_uses_env_key_when_omitted(api: TestClient, fake_cli, monkeypatch) -> None:
    monkeypatch.setenv(orc.API_KEY_ENV_VAR, KEY)
    resp = api.post("/api/openclaw/model", headers=AUTH, json={"provider": "openrouter", "model": "openrouter/auto"})
    assert resp.status_code == 200
    assert _calls(fake_cli["cli"], "models", "auth", "paste-api-key")[0]["stdin"] == KEY + "\n"
    assert KEY not in resp.text


def test_post_model_without_any_key_keeps_existing(api: TestClient, fake_cli) -> None:
    resp = api.post("/api/openclaw/model", headers=AUTH, json={"provider": "openrouter", "model": "openrouter/auto"})
    assert resp.status_code == 200
    assert not _calls(fake_cli["cli"], "models", "auth")
    assert resp.json()["configured"] is False
    assert resp.json()["warnings"]


def test_post_model_rejects_unknown_model(api: TestClient, fake_cli) -> None:
    resp = api.post("/api/openclaw/model", headers=AUTH, json={"provider": "openrouter", "model": "openrouter/acme/nope"})
    assert resp.status_code == 400
    assert fake_cli["cli"].calls == []


@pytest.mark.parametrize(
    "body",
    [
        {"provider": "openrouter", "api_key": KEY},  # missing model: default 422 would echo the body
        {"provider": "openrouter", "api_key": KEY, "model": "bad model"},
        {"provider": "openrouter", "api_key": KEY + " x", "model": OPUS},
        {"provider": "openrouter", "api_key": KEY, "model": OPUS, "routing": {"sort": "bogus"}},
        {"provider": "openrouter", "api_key": KEY, "model": OPUS, "response_cache": {"enabled": True, "ttl_seconds": 0}},
    ],
)
def test_post_model_validation_never_echoes_the_key(api: TestClient, fake_cli, body: dict) -> None:
    resp = api.post("/api/openclaw/model", headers=AUTH, json=body)
    assert resp.status_code == 422
    assert KEY not in resp.text
    assert fake_cli["cli"].calls == []


def test_post_model_cli_failure_is_redacted(api: TestClient, fake_cli, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    fake_cli["cli"] = FakeOpenClaw(fail={"models auth paste-api-key": (1, f"rejected {KEY}\n")})
    resp = api.post("/api/openclaw/model", headers=AUTH, json={"provider": "openrouter", "api_key": KEY, "model": OPUS})
    assert resp.status_code == 502
    assert KEY not in resp.text and KEY not in caplog.text
    assert "paste-api-key failed" in resp.json()["detail"]
    assert any("OpenClaw model configuration failed" in r.message for r in caplog.records)


def test_openrouter_models_proxy(api: TestClient) -> None:
    body = api.get("/api/openclaw/openrouter/models", headers=AUTH).json()
    assert body["count"] == 3 and body["stale"] is False
    assert not any(m["id"].endswith(":batch") for m in body["models"])


def test_openrouter_models_proxy_upstream_failure(api: TestClient, monkeypatch) -> None:
    async def failing(*, force: bool = False, client=None):
        raise httpx.HTTPError("OpenRouter catalog unavailable: boom")

    monkeypatch.setattr(orc, "fetch_openrouter_catalog", failing)
    resp = api.get("/api/openclaw/openrouter/models", headers=AUTH)
    assert resp.status_code == 502
