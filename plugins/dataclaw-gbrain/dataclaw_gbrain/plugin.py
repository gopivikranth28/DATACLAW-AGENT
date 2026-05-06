"""GbrainPlugin — registers the package as a dataclaw plugin.

Wiring lives in core: the memory provider factory at
`dataclaw/providers/memory/implementations/factory.py` instantiates
`GbrainMemoryProvider` whenever `memory.backend == "gbrain"`, and the
`/api/providers` router exposes `gbrain` as a memory backend option.

This plugin class therefore has nothing to register at startup — its only
job is to ensure the `dataclaw_gbrain` package is importable in the venv.
"""

from __future__ import annotations

from dataclaw.plugins.base import PluginContext, PluginUIManifest


class GbrainPlugin:
    name = "dataclaw-gbrain"
    depends_on: list[str] = []

    def register(self, ctx: PluginContext) -> None:
        # No-op: backend selection is config-driven via memory.backend.
        # The factory imports GbrainMemoryProvider when needed.
        return None

    def ui_manifest(self) -> PluginUIManifest | None:
        # Settings render under the Memory Provider section (driven by
        # GbrainMemoryProvider.config_schema()), not as a separate modal.
        return None
