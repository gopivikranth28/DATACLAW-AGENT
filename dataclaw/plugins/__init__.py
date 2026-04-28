"""Plugin system — discovery, registration, and provider DI."""

from dataclaw.plugins.base import DataclawPlugin, PluginContext, PluginUIManifest, PluginPage, PluginConfigField
from dataclaw.plugins.registry import ProviderRegistry
from dataclaw.plugins.loader import discover_plugins

__all__ = [
    "DataclawPlugin",
    "PluginContext",
    "PluginUIManifest",
    "PluginPage",
    "PluginConfigField",
    "ProviderRegistry",
    "discover_plugins",
]
