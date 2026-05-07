"""Tests for the default tool availability registry — focused on
``seed_plugin_defaults`` and the ``seeded_plugins`` one-shot semantics."""

from __future__ import annotations

from dataclaw.providers.tool.implementations.registry import DefaultToolAvailability
from dataclaw.providers.tool.tool_config import (
    load_global_tool_config,
    save_global_tool_config,
    ToolConfig,
)


class _FakeTool:
    def __init__(self, name: str) -> None:
        self.name = name
        self.definition = {"name": name}

    async def execute(self, **_: object) -> dict[str, object]:
        return {}


def test_seed_plugin_defaults_disables_listed_tools_first_time() -> None:
    reg = DefaultToolAvailability()
    reg.register_tool(_FakeTool("foo_a"))
    reg.register_tool(_FakeTool("foo_b"))

    reg.seed_plugin_defaults("plugin-foo", ["foo_a", "foo_b"])

    cfg = load_global_tool_config()
    assert cfg.disabled == {"foo_a", "foo_b"}
    assert "plugin-foo" in cfg.seeded_plugins


def test_seed_plugin_defaults_is_one_shot_per_plugin() -> None:
    reg = DefaultToolAvailability()
    reg.register_tool(_FakeTool("foo_a"))
    reg.seed_plugin_defaults("plugin-foo", ["foo_a"])

    # User re-enables foo_a via UI.
    reg.set_tool_enabled("foo_a", True)
    assert "foo_a" not in load_global_tool_config().disabled

    # Plugin reloads and re-seeds — the user's enable must stick.
    reg2 = DefaultToolAvailability()
    reg2.register_tool(_FakeTool("foo_a"))
    reg2.seed_plugin_defaults("plugin-foo", ["foo_a"])

    assert "foo_a" not in load_global_tool_config().disabled


def test_seed_plugin_defaults_persists_seeded_marker_even_with_no_changes() -> None:
    # Pre-existing config: foo_a already manually disabled by the user before
    # the plugin's first load. Seeding adds nothing new to `disabled` but must
    # still mark the plugin id as seeded so we don't re-seed next time.
    initial = ToolConfig(disabled={"foo_a"})
    save_global_tool_config(initial)

    reg = DefaultToolAvailability()
    reg.register_tool(_FakeTool("foo_a"))
    reg.seed_plugin_defaults("plugin-foo", ["foo_a"])

    cfg = load_global_tool_config()
    assert "plugin-foo" in cfg.seeded_plugins


def test_seed_plugin_defaults_ignores_empty_inputs() -> None:
    reg = DefaultToolAvailability()
    reg.seed_plugin_defaults("", ["foo_a"])
    reg.seed_plugin_defaults("plugin-foo", ["", "foo_a"])

    cfg = load_global_tool_config()
    assert cfg.disabled == {"foo_a"}
    assert cfg.seeded_plugins == {"plugin-foo"}
