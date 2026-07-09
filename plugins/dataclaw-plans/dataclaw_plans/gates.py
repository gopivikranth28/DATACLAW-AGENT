"""Plan gate state and audit helpers.

Gates are intentionally owned by the plans plugin while live evaluators are
registered by other plugins. That keeps plans as the spine without importing
analysis-review, EDA, artifacts, or modeling code.
"""

from __future__ import annotations

import inspect
import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from dataclaw.config.paths import plugin_data_dir
from dataclaw.guardrails.base import GuardrailVerdict
from dataclaw.state import AgentState

from dataclaw_plans.store import append_snapshot, read_proposals, write_proposals

GATE_STATUSES = {"pass", "fail", "unknown", "accepted"}
GateResolver = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any] | Awaitable[dict[str, Any]]]
GATE_RESOLVERS: dict[str, GateResolver] = {}

HIGH_RISK_STEP_KEYWORDS = (
    "model",
    "modeling",
    "mlflow",
    "train",
    "predict",
    "publish",
    "export",
    "external",
    "share",
    "send",
)
EDA_STEP_KEYWORDS = (
    "eda",
    "exploratory",
    "explore",
    "profile",
    "profiling",
    "readiness",
    "data quality",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _audit_file() -> Path:
    path = plugin_data_dir("plans") / "gate_events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(record, default=str, sort_keys=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(encoded + "\n")
        f.flush()
        os.fsync(f.fileno())


def _atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _step_identity(step: dict[str, Any]) -> str:
    return str(step.get("plan_step_id") or step.get("id") or step.get("step_id") or "").strip()


def _normalize_gate_name(gate_name: str) -> str:
    name = str(gate_name or "").strip()
    if not name:
        raise ValueError("gate_name is required")
    return name


def _normalize_gate(raw: dict[str, Any], gate_name: str) -> dict[str, Any]:
    status = str(raw.get("status") or "unknown")
    if status not in GATE_STATUSES:
        status = "unknown"
    return {
        "name": gate_name,
        "status": status,
        "required": bool(raw.get("required", False)),
        "reason": str(raw.get("reason") or ""),
        "actor": str(raw.get("actor") or ""),
        "updated_at": str(raw.get("updated_at") or ""),
        "accepted": bool(raw.get("accepted") or status == "accepted"),
        "accepted_at": str(raw.get("accepted_at") or ""),
        "accepted_rationale": str(raw.get("accepted_rationale") or ""),
        "details": raw.get("details") or {},
    }


def _gate_map(step: dict[str, Any]) -> dict[str, dict[str, Any]]:
    gates = step.get("gates") or {}
    if isinstance(gates, list):
        return {
            str(g.get("name") or ""): _normalize_gate(g, str(g.get("name") or ""))
            for g in gates
            if isinstance(g, dict) and str(g.get("name") or "")
        }
    if isinstance(gates, dict):
        return {
            str(name): _normalize_gate(value if isinstance(value, dict) else {}, str(name))
            for name, value in gates.items()
        }
    return {}


def _store_gate_map(step: dict[str, Any], gates: dict[str, dict[str, Any]]) -> None:
    step["gates"] = {name: _normalize_gate(gate, name) for name, gate in sorted(gates.items())}


def register_gate_resolver(gate_name: str, resolver: GateResolver) -> None:
    """Register a live gate evaluator by name."""
    GATE_RESOLVERS[_normalize_gate_name(gate_name)] = resolver


def step_requires_review_gate(step: dict[str, Any]) -> bool:
    """Return True when the plan step should require analysis review by policy."""
    haystack = " ".join(
        [
            str(step.get("name") or ""),
            str(step.get("description") or ""),
            str(step.get("summary") or ""),
            " ".join(str(o) for o in (step.get("outputs") or [])),
        ]
    ).lower()
    return any(keyword in haystack for keyword in HIGH_RISK_STEP_KEYWORDS + EDA_STEP_KEYWORDS)


def _gate_has_audited_acceptance(gate: dict[str, Any]) -> bool:
    if not gate.get("accepted") and gate.get("status") != "accepted":
        return False
    return bool(str(gate.get("accepted_at") or "").strip()) and bool(
        str(gate.get("accepted_rationale") or "").strip()
    )


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def resolve_step_gates(proposal: dict[str, Any], step: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return stored gates plus live resolver output for one step."""
    gates = _gate_map(step)
    for name, resolver in GATE_RESOLVERS.items():
        try:
            resolved = await _maybe_await(resolver(proposal, step))
        except Exception as exc:
            resolved = {
                "status": "unknown",
                "required": False,
                "reason": f"gate resolver failed: {exc}",
                "actor": name,
            }
        if isinstance(resolved, dict):
            prior = gates.get(name, {})
            gates[name] = _normalize_gate({**prior, **resolved, "name": name}, name)

    if step_requires_review_gate(step) and "analysis_review" not in gates:
        gates["analysis_review"] = _normalize_gate(
            {
                "status": "unknown",
                "required": True,
                "reason": "Analysis review required by plan gate policy",
                "actor": "gate_policy",
            },
            "analysis_review",
        )
    elif step_requires_review_gate(step):
        gates["analysis_review"]["required"] = True
        if not gates["analysis_review"].get("reason"):
            gates["analysis_review"]["reason"] = "Analysis review required by plan gate policy"

    return gates


async def blocking_gates(proposal: dict[str, Any], step: dict[str, Any]) -> list[dict[str, Any]]:
    gates = await resolve_step_gates(proposal, step)
    blockers: list[dict[str, Any]] = []
    for gate in gates.values():
        if not gate.get("required"):
            continue
        if _gate_has_audited_acceptance(gate):
            continue
        if gate.get("status") in {"fail", "unknown"}:
            blockers.append(gate)
    return blockers


def _append_gate_event(event: dict[str, Any]) -> None:
    _append_jsonl(_audit_file(), event)


def append_ready_check_event(
    *,
    proposal_id: str,
    plan_step_id: str,
    requested: bool,
    outcome: str,
    blocking: list[dict[str, Any]] | None = None,
    actor: str = "agent",
) -> None:
    _append_gate_event(
        {
            "event_id": f"gate-{uuid.uuid4().hex[:8]}",
            "event_type": "ready_for_validation_check",
            "proposal_id": proposal_id,
            "plan_step_id": plan_step_id,
            "requested": requested,
            "outcome": outcome,
            "blocking_gates": blocking or [],
            "actor": actor,
            "created_at": _now_iso(),
        }
    )


def recent_gate_events(proposal_id: str, limit: int = 50) -> list[dict[str, Any]]:
    path = _audit_file()
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("proposal_id") == proposal_id:
            events.append(event)
    return events[-limit:]


def set_step_gate(
    *,
    proposal_id: str,
    plan_step_id: str,
    gate_name: str,
    status: str,
    required: bool = False,
    reason: str = "",
    actor: str = "system",
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Patch a step gate, append audit, and snapshot the plan."""
    gate_name = _normalize_gate_name(gate_name)
    if status not in GATE_STATUSES:
        raise ValueError(f"Unsupported gate status: {status}")

    proposals = read_proposals()
    for proposal in proposals:
        if proposal.get("id") != proposal_id:
            continue
        for step in proposal.get("steps", []):
            if _step_identity(step) != plan_step_id:
                continue
            gates = _gate_map(step)
            previous = gates.get(gate_name)
            gate = _normalize_gate(
                {
                    **(previous or {}),
                    "status": status,
                    "required": required,
                    "reason": reason,
                    "actor": actor,
                    "updated_at": _now_iso(),
                    "accepted": status == "accepted",
                    "accepted_at": (previous or {}).get("accepted_at", "") if status == "accepted" else "",
                    "accepted_rationale": (previous or {}).get("accepted_rationale", "") if status == "accepted" else "",
                    "details": details or {},
                },
                gate_name,
            )
            gates[gate_name] = gate
            _store_gate_map(step, gates)
            proposal["updated_at"] = _now_iso()
            write_proposals(proposals)
            snapshot = append_snapshot(proposal, trigger="gate")
            _append_gate_event(
                {
                    "event_id": f"gate-{uuid.uuid4().hex[:8]}",
                    "event_type": "gate_set",
                    "proposal_id": proposal_id,
                    "plan_step_id": plan_step_id,
                    "gate_name": gate_name,
                    "previous": previous,
                    "new": gate,
                    "actor": actor,
                    "reason": reason,
                    "created_at": gate["updated_at"],
                }
            )
            return {"success": True, "gate": gate, "snapshot_id": snapshot["id"]}
        raise KeyError(f"Plan step not found: {plan_step_id}")
    raise KeyError(f"Plan proposal not found: {proposal_id}")


async def accept_gate_risk(
    *,
    proposal_id: str,
    plan_step_id: str,
    gate_name: str,
    rationale: str,
    actor: str = "user",
    **_: Any,
) -> dict[str, Any]:
    """Accept a required gate risk with an audit trail.

    A pre-tool guardrail requires explicit user approval before this tool can
    run in chat. Direct API calls without that approval are blocked by the same
    guardrail path.
    """
    if not rationale.strip():
        raise ValueError("rationale is required")
    result = set_step_gate(
        proposal_id=proposal_id,
        plan_step_id=plan_step_id,
        gate_name=gate_name,
        status="accepted",
        required=True,
        reason="Gate risk accepted by user",
        actor=actor or "user",
        details={"rationale": rationale},
    )
    gate = result["gate"]
    gate["accepted"] = True
    gate["accepted_at"] = _now_iso()
    gate["accepted_rationale"] = rationale

    proposals = read_proposals()
    for proposal in proposals:
        if proposal.get("id") != proposal_id:
            continue
        for step in proposal.get("steps", []):
            if _step_identity(step) == plan_step_id:
                gates = _gate_map(step)
                gates[gate_name] = gate
                _store_gate_map(step, gates)
                proposal["updated_at"] = _now_iso()
                write_proposals(proposals)
                snapshot = append_snapshot(proposal, trigger="gate_accept")
                _append_gate_event(
                    {
                        "event_id": f"gate-{uuid.uuid4().hex[:8]}",
                        "event_type": "gate_accepted",
                        "proposal_id": proposal_id,
                        "plan_step_id": plan_step_id,
                        "gate_name": gate_name,
                        "new": gate,
                        "actor": actor or "user",
                        "reason": rationale,
                        "created_at": gate["accepted_at"],
                    }
                )
                return {"success": True, "gate": gate, "snapshot_id": snapshot["id"]}
    raise KeyError(f"Plan proposal not found: {proposal_id}")


async def get_plan_gates(proposal_id: str) -> dict[str, Any]:
    proposals = read_proposals()
    proposal = next((p for p in proposals if p.get("id") == proposal_id), None)
    if proposal is None:
        raise KeyError(f"Plan proposal not found: {proposal_id}")
    steps = []
    for step in proposal.get("steps", []):
        step_id = _step_identity(step)
        gates = await resolve_step_gates(proposal, step)
        steps.append(
            {
                "plan_step_id": step_id,
                "name": step.get("name", ""),
                "ready_for_validation": bool(step.get("ready_for_validation")),
                "gates": gates,
                "blocking_gates": await blocking_gates(proposal, step),
            }
        )
    return {"proposal_id": proposal_id, "steps": steps, "events": recent_gate_events(proposal_id)}


async def plan_completion_warnings(proposal_id: str) -> list[str]:
    try:
        state = await get_plan_gates(proposal_id)
    except Exception:
        return []
    warnings: list[str] = []
    for step in state.get("steps", []):
        blockers = step.get("blocking_gates") or []
        if blockers and not step.get("ready_for_validation"):
            names = ", ".join(str(g.get("name") or "gate") for g in blockers)
            warnings.append(f"{step.get('name') or step.get('plan_step_id')} is not ready for validation ({names})")
    return warnings


def plan_completion_warnings_sync(proposal_id: str) -> list[str]:
    """Synchronous conservative completion warnings for guardrails."""
    proposal = next((p for p in read_proposals() if p.get("id") == proposal_id), None)
    if proposal is None:
        return []
    warnings: list[str] = []
    for step in proposal.get("steps", []):
        if step.get("ready_for_validation"):
            continue
        gates = _gate_map(step)
        if step_requires_review_gate(step) and "analysis_review" not in gates:
            warnings.append(f"{step.get('name') or _step_identity(step)} is not ready for validation (analysis_review)")
            continue
        blockers = [
            gate
            for gate in gates.values()
            if gate.get("required")
            and not gate.get("accepted")
            and gate.get("status") in {"fail", "unknown"}
        ]
        if blockers:
            names = ", ".join(str(g.get("name") or "gate") for g in blockers)
            warnings.append(f"{step.get('name') or _step_identity(step)} is not ready for validation ({names})")
    return warnings


class GateRiskAcceptanceGuardrail:
    """Require user approval before an agent accepts validation risk."""

    id = "gate_risk_acceptance"
    phase = "pre"
    mode = "user_approval"

    def evaluate(self, tool_call: dict[str, Any], state: AgentState) -> GuardrailVerdict | None:
        if tool_call.get("tool_name") != "accept_gate_risk":
            return None
        tool_input = tool_call.get("tool_input", {})
        gate_name = tool_input.get("gate_name", "gate")
        step = tool_input.get("plan_step_id", "step")
        rationale = tool_input.get("rationale", "")
        return GuardrailVerdict(
            tool_call_id=tool_call.get("call_id", ""),
            guardrail_id=self.id,
            message=(
                f"The agent wants to accept validation risk for `{gate_name}` on `{step}`.\n\n"
                f"Rationale: {rationale or '(none provided)'}\n\n"
                "Approve only if you explicitly want to proceed despite the unresolved gate."
            ),
            mode=self.mode,
            phase=self.phase,
            severity="warning",
        )
