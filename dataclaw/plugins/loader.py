"""Plugin discovery and dependency-ordered loading.

Plugins register themselves in their pyproject.toml:

    [project.entry-points."dataclaw.plugins"]
    my_plugin = "my_package:MyPlugin"

discover_plugins() finds, instantiates, and topologically sorts all
plugins by their depends_on declarations. Plugins are returned in
dependency order — if B depends on A, A comes first.
"""

from __future__ import annotations

import logging
from importlib.metadata import entry_points

from dataclaw.plugins.base import DataclawPlugin

logger = logging.getLogger(__name__)


def discover_plugins() -> list[DataclawPlugin]:
    """Discover, instantiate, and dependency-sort all registered plugins."""
    eps = entry_points(group="dataclaw.plugins")
    plugins: list[DataclawPlugin] = []
    for ep in eps:
        try:
            cls = ep.load()
            plugin = cls()
            plugins.append(plugin)
            logger.info("Loaded plugin: %s (%s)", ep.name, ep.value)
        except Exception:
            logger.exception("Failed to load plugin: %s", ep.name)

    return _topo_sort(plugins)


def _topo_sort(plugins: list[DataclawPlugin]) -> list[DataclawPlugin]:
    """Topologically sort plugins by depends_on. Raises on cycles."""
    by_name: dict[str, DataclawPlugin] = {}
    for p in plugins:
        by_name[p.name] = p

    visited: set[str] = set()
    in_stack: set[str] = set()
    order: list[DataclawPlugin] = []

    def visit(name: str) -> None:
        if name in visited:
            return
        if name in in_stack:
            raise ValueError(f"Circular plugin dependency involving: {name}")
        in_stack.add(name)

        plugin = by_name.get(name)
        if plugin is not None:
            for dep in getattr(plugin, "depends_on", []):
                if dep in by_name:
                    visit(dep)
                else:
                    logger.warning(
                        "Plugin %s depends on %s which is not installed",
                        name, dep,
                    )

            in_stack.discard(name)
            visited.add(name)
            order.append(plugin)
        else:
            in_stack.discard(name)
            visited.add(name)

    for name in by_name:
        visit(name)

    return order
