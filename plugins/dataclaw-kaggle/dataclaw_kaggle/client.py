"""Async wrapper around the synchronous kaggle Python package."""

from __future__ import annotations

import asyncio
import os
from typing import Any

_api: Any = None


def _get_api(username: str = "", key: str = "") -> Any:
    """Return a cached, authenticated KaggleApi instance.

    Import is deferred so the module loads even without credentials.
    Plugin config credentials are injected as env vars so they take priority
    over ~/.kaggle/kaggle.json.
    """
    global _api
    if _api is not None:
        return _api
    if username:
        os.environ["KAGGLE_USERNAME"] = username
    if key:
        os.environ["KAGGLE_KEY"] = key
    from kaggle.api.kaggle_api_extended import KaggleApi
    api = KaggleApi()
    api.authenticate()
    _api = api
    return api


def reset_api() -> None:
    """Clear the cached client so the next call re-authenticates."""
    global _api
    _api = None


async def run_kaggle(
    method: str,
    *args: Any,
    username: str = "",
    key: str = "",
    **kwargs: Any,
) -> Any:
    """Run a KaggleApi method in a thread to keep the event loop free."""
    api = _get_api(username, key)
    fn = getattr(api, method)
    return await asyncio.to_thread(fn, *args, **kwargs)


def get_config(plugin_cfg: dict[str, Any]) -> tuple[str, str]:
    """Extract username and key from plugin config dict."""
    return (
        plugin_cfg.get("kaggle_username", "") or "",
        plugin_cfg.get("kaggle_key", "") or "",
    )
