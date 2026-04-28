"""Tests for config resolution."""

import json
import pytest

from dataclaw.config.paths import DATACLAW_HOME, config_path, sessions_dir, skills_dir
from dataclaw.config.resolver import resolve, resolve_bool, invalidate_cache
from dataclaw.config.schema import DataclawConfig


def test_dataclaw_home_from_env(tmp_dataclaw_home):
    """DATACLAW_HOME should point to temp dir in tests."""
    assert tmp_dataclaw_home.exists()


def test_default_config():
    config = DataclawConfig()
    assert config.llm.backend == "anthropic"
    assert config.compaction.enabled is False
    assert config.app.max_turns == 30


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
