"""Hook system — intercept and modify pipeline state at named points."""

from dataclaw.hooks.base import Hook, HookError
from dataclaw.hooks.registry import HookRegistry, HOOK_POINTS

__all__ = ["Hook", "HookError", "HookRegistry", "HOOK_POINTS"]
