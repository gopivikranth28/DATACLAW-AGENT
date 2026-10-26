"""Tests for config resolution."""

import json
import threading
from types import SimpleNamespace

import pytest

import dataclaw.api.routers.config as config_router
from dataclaw.api.routers.config import (
    _hot_reload_plugins,
    _mask_secrets_recursive,
    _strip_masked_secrets,
)
from dataclaw.config.paths import DATACLAW_HOME, config_path, sessions_dir, skills_dir
from dataclaw.config.migrations import (
    migrate_config,
    migrate_llm_backends_config,
    migrate_runtime_utility_config,
)
from dataclaw.config.resolver import (
    invalidate_cache,
    resolve,
    resolve_agent_runtime,
    resolve_bool,
    resolve_utility_backend,
)
from dataclaw.config.schema import DataclawConfig


def test_dataclaw_home_from_env(tmp_dataclaw_home):
    """DATACLAW_HOME should point to temp dir in tests."""
    assert tmp_dataclaw_home.exists()


def test_default_config():
    config = DataclawConfig()
    assert config.agent.runtime == "openclaw"
    assert config.llm.backend == "codex"
    assert config.llm.backends == {}
    assert config.compaction.enabled is False
    assert config.app.max_turns == 30
    assert config.app.host == "127.0.0.1"


def test_resolve_default():
    invalidate_cache()
    result = resolve("nonexistent.key", "NONEXISTENT_ENV_VAR", "default_value")
    assert result == "default_value"


def test_resolve_env_var(monkeypatch):
    monkeypatch.setenv("TEST_RESOLVE_VAR", "from_env")
    result = resolve("some.path", "TEST_RESOLVE_VAR", "default")
    assert result == "from_env"


def test_resolve_config_file(tmp_dataclaw_home):
    invalidate_cache()
    config_file = tmp_dataclaw_home / "dataclaw.config.json"
    config_file.write_text(json.dumps({"llm": {"backend": "openai"}}))

    # Need to patch config_path to point to our temp dir
    import dataclaw.config.resolver as resolver
    import dataclaw.config.paths as paths
    original_config_path = paths.config_path

    try:
        paths.config_path = lambda: config_file
        invalidate_cache()
        result = resolve("llm.backend", "NONEXISTENT", "anthropic")
        assert result == "openai"
    finally:
        paths.config_path = original_config_path
        invalidate_cache()


def test_resolve_bool_true(monkeypatch):
    monkeypatch.setenv("TEST_BOOL", "true")
    assert resolve_bool("x", "TEST_BOOL") is True


def test_resolve_bool_false(monkeypatch):
    monkeypatch.setenv("TEST_BOOL", "false")
    assert resolve_bool("x", "TEST_BOOL") is False


def test_resolve_bool_default():
    assert resolve_bool("nonexistent", "NONEXISTENT", default=True) is True


def test_migrate_hermes_runtime_and_utility_model() -> None:
    raw = {
        "llm": {
            "backend": "hermes",
            "codex": {"model": "old-model"},
        },
        "plugins": {
            "hermes": {
                "utility_backend": "codex",
                "utility_model": "gpt-5.5",
            }
        },
    }

    assert migrate_runtime_utility_config(raw) is True
    assert raw["agent"]["runtime"] == "hermes"
    assert raw["llm"]["backend"] == "codex"
    assert raw["llm"]["backends"]["codex"]["model"] == "gpt-5.5"
    assert "utility_backend" not in raw["plugins"]["hermes"]
    assert "utility_model" not in raw["plugins"]["hermes"]

    # The legacy section then moves under llm.backends; the Hermes alias,
    # already written there, wins over the stale legacy model.
    assert migrate_llm_backends_config(raw) is True
    assert "codex" not in raw["llm"]
    assert raw["llm"]["backends"]["codex"]["model"] == "gpt-5.5"


def test_migrate_direct_backend_to_dataclaw_runtime() -> None:
    raw = {"llm": {"backend": "anthropic"}}

    assert migrate_runtime_utility_config(raw) is True
    assert raw["agent"]["runtime"] == "dataclaw"
    assert raw["llm"]["backend"] == "anthropic"


def test_resolve_separate_runtime_and_utility(
    tmp_dataclaw_home,
    monkeypatch,
) -> None:
    config_file = tmp_dataclaw_home / "dataclaw.config.json"
    config_file.write_text(
        json.dumps(
            {
                "agent": {"runtime": "openclaw"},
                "llm": {"backend": "gemini"},
            }
        )
    )
    import dataclaw.config.paths as paths

    monkeypatch.setattr(paths, "config_path", lambda: config_file)
    invalidate_cache()
    try:
        assert resolve_agent_runtime() == "openclaw"
        assert resolve_utility_backend() == "gemini"
    finally:
        invalidate_cache()


def test_kaggle_secrets_are_masked():
    config = {
        "plugins": {
            "kaggle": {
                "kaggle_api_token": "KGAT_abcdefghijklmnopqrstuvwxyz",
                "kaggle_key": "legacy-secret-value",
                "kaggle_username": "visible-user",
            },
        },
    }

    _mask_secrets_recursive(config)

    kaggle = config["plugins"]["kaggle"]
    assert kaggle["kaggle_api_token"] != "KGAT_abcdefghijklmnopqrstuvwxyz"
    assert kaggle["kaggle_key"] != "legacy-secret-value"
    assert kaggle["kaggle_username"] == "visible-user"


def test_masked_kaggle_secrets_are_not_written_back():
    updates = {
        "plugins": {
            "kaggle": {
                "kaggle_api_token": "KGAT_abc...wxyz",
                "kaggle_key": "***",
                "download_dir": "/tmp/kaggle",
            },
        },
    }

    _strip_masked_secrets(updates)

    kaggle = updates["plugins"]["kaggle"]
    assert "kaggle_api_token" not in kaggle
    assert "kaggle_key" not in kaggle
    assert kaggle["download_dir"] == "/tmp/kaggle"


def test_hot_reload_plugins_notifies_supported_plugins():
    observed = []

    class ReloadablePlugin:
        name = "reloadable"

        def on_config_update(self, config):
            observed.append(config)

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(plugins_list=[ReloadablePlugin(), object()])
        )
    )
    config = DataclawConfig(plugins={"kaggle": {"kaggle_api_token": "KGAT_new"}})

    _hot_reload_plugins(request, config)

    assert observed == [config]


@pytest.mark.asyncio
async def test_config_update_runs_plugin_reload_off_event_loop(
    monkeypatch,
):
    main_thread = threading.get_ident()
    callback_threads = []

    def fake_reload_plugins(request, config):
        callback_threads.append(threading.get_ident())

    monkeypatch.setattr(config_router, "_hot_reload_plugins", fake_reload_plugins)
    # No RuntimeManager on this request, so reload_runtime falls back to the
    # legacy synchronous agent reload.
    monkeypatch.setattr(config_router, "_hot_reload_agent", lambda request: None)
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                plugins_list=[],
                providers=SimpleNamespace(),
            )
        )
    )

    await config_router.update_config({}, request)

    assert callback_threads
    assert callback_threads[0] != main_thread


# ── llm.backends migration ──────────────────────────────────────────────────


def _legacy_llm_config() -> dict:
    """A config as written by releases before llm.backends."""
    return {
        "agent": {"runtime": "dataclaw"},
        "llm": {
            "backend": "anthropic",
            "anthropic": {"api_key": "sk-ant-secret-0001", "model": "claude-sonnet-4-20250514"},
            "openai": {"api_key": "sk-openai-secret-0002", "model": "gpt-4o", "base_url": "http://proxy.local/v1"},
            "gemini": {"api_key": "", "model": "gemini-2.5-flash"},
            "codex": {"model": "gpt-5.4", "api_key": "", "auth_mode": "api_key", "codex_bin": "/opt/codex"},
        },
    }


def test_migrate_legacy_llm_sections_to_backends() -> None:
    raw = _legacy_llm_config()

    assert migrate_config(raw) is True

    llm = raw["llm"]
    assert llm["backend"] == "anthropic"
    for legacy in ("anthropic", "openai", "gemini", "codex"):
        assert legacy not in llm
    backends = llm["backends"]
    # Secrets and every other key are carried over.
    assert backends["anthropic"]["api_key"] == "sk-ant-secret-0001"
    assert backends["openai"]["api_key"] == "sk-openai-secret-0002"
    assert backends["openai"]["base_url"] == "http://proxy.local/v1"
    assert backends["codex"] == {
        "model": "gpt-5.4", "api_key": "", "auth_mode": "api_key", "codex_bin": "/opt/codex",
    }
    # Old schema defaults recorded no user choice, so the registry default
    # applies; an OpenAI proxy keeps its model.
    assert "model" not in backends["anthropic"]
    assert "model" not in backends["gemini"]
    assert backends["openai"]["model"] == "gpt-4o"

    # The migrated config parses, and a second pass is a no-op.
    DataclawConfig(**raw)
    assert migrate_config(raw) is False


def test_migrate_keeps_newer_backend_values() -> None:
    raw = {"llm": {
        "backend": "openai",
        "openai": {"api_key": "old", "model": "gpt-5"},
        "backends": {"openai": {"api_key": "new", "model": ""}},
    }}

    assert migrate_llm_backends_config(raw) is True
    assert raw["llm"]["backends"]["openai"] == {"api_key": "new", "model": "gpt-5"}


def test_migrated_config_resolves_like_legacy(tmp_dataclaw_home, monkeypatch) -> None:
    from dataclaw.providers.llm.registry import resolve_backend_config

    for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENAI_BASE_URL", "CODEX_AUTH_MODE", "CODEX_BIN"):
        monkeypatch.delenv(name, raising=False)
    config_file = tmp_dataclaw_home / "dataclaw.config.json"
    legacy = _legacy_llm_config()

    config_file.write_text(json.dumps(legacy))
    invalidate_cache()
    before = {b: resolve_backend_config(b).values for b in ("anthropic", "openai", "codex")}

    migrate_config(legacy)
    config_file.write_text(json.dumps(legacy))
    invalidate_cache()
    after = {b: resolve_backend_config(b).values for b in ("anthropic", "openai", "codex")}

    for backend in ("anthropic", "openai", "codex"):
        for key in ("api_key", "base_url", "auth_mode", "codex_bin"):
            assert after[backend].get(key) == before[backend].get(key), (backend, key)
    assert after["anthropic"]["api_key"] == "sk-ant-secret-0001"
    invalidate_cache()


def test_llm_backend_secrets_are_masked_and_preserved() -> None:
    config = {"llm": {"backends": {
        "openai_compatible": {
            "api_key": "sk-or-v1-abcdefghijklmnop",
            "base_url": "https://openrouter.ai/api/v1",
            "headers": {"Authorization": "Bearer abcdefghijklmnop", "X-Title": "DataClaw"},
        },
    }}}

    _mask_secrets_recursive(config)

    compat = config["llm"]["backends"]["openai_compatible"]
    assert compat["api_key"] != "sk-or-v1-abcdefghijklmnop"
    assert compat["headers"]["Authorization"] != "Bearer abcdefghijklmnop"
    assert compat["headers"]["X-Title"] == "DataClaw"
    assert compat["base_url"] == "https://openrouter.ai/api/v1"

    # Saving the masked values back must not overwrite the real secrets.
    _strip_masked_secrets(config)
    assert "api_key" not in compat
    assert "Authorization" not in compat["headers"]
    assert compat["headers"]["X-Title"] == "DataClaw"
