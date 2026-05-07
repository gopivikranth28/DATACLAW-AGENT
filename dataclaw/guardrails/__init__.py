"""Guardrail system — per-tool-call policy enforcement.

Guardrails inspect tool calls before or after execution and can:
- Auto-reply: inject a synthetic tool result so the agent adapts.
- User-approval: pause the loop and surface an approve/deny prompt in the UI.
"""

from dataclaw.guardrails.base import Guardrail, GuardrailVerdict
from dataclaw.guardrails.registry import GuardrailRegistry

__all__ = ["Guardrail", "GuardrailVerdict", "GuardrailRegistry"]
