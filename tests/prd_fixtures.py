"""Shared PRD acceptance fixtures (structured-EDA PRD, FR-38).

The three portfolio-wide acceptance helpers, implemented once and reusable by
CI suites and the evals/ harness:

- ``assert_openclaw_tool_aliases`` — the OpenClaw manifest generated from the
  live tool registry carries every canonical structured-EDA tool with a
  byte-identical parameter schema.
- ``assert_plan_step_identity`` — persisted evidence uses stable
  ``plan_step_id`` values (``step-<hex8>``); names are display-only.
- ``assert_preview_cap`` — inline evidence obeys the shared 20-row / 50-KiB
  preview caps.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

# The 13 canonical structured-EDA tool names (PRD Convergence checklist):
# 8 EDA ledger tools + 4 review lifecycle tools + the plans escape hatch.
CANONICAL_STRUCTURED_EDA_TOOLS = [
    "propose_eda_hypotheses",
    "update_eda_hypothesis",
    "list_eda_hypotheses",
    "record_eda_finding",
    "supersede_eda_finding",
    "list_eda_findings",
    "read_eda_finding",
    "summarize_eda_readiness",
    "request_analysis_review",
    "list_review_findings",
    "resolve_review_finding",
    "get_review_gate",
    "accept_gate_risk",
]

PLAN_STEP_ID_RE = re.compile(r"^step-[0-9a-f]{8}$")

_MANIFEST_LINE_RE = re.compile(
    r'^\s*\{ name: ("(?:[^"\\]|\\.)*"), description: ("(?:[^"\\]|\\.)*"), parameters: (\{.*\}) \},$'
)


def assert_openclaw_tool_aliases(
    tool_definitions: list[dict[str, Any]],
    plugin_dir: Path | str,
) -> None:
    """Run the live manifest generator and assert canonical-tool schema identity.

    ``tool_definitions`` is the live registry listing (e.g. ``GET /api/tools``
    ``tools``); ``plugin_dir`` is a scratch directory standing in for the
    OpenClaw plugin checkout.
    """
    from dataclaw_openclaw.openclaw_install_service import write_tool_manifest

    by_name = {str(t.get("name") or ""): t for t in tool_definitions}
    missing = [name for name in CANONICAL_STRUCTURED_EDA_TOOLS if name not in by_name]
    assert not missing, f"canonical tools missing from the live registry: {missing}"

    tools = [
        {
            "name": str(t.get("name") or ""),
            "description": str(t.get("description") or ""),
            "parameters": t.get("parameters") or {"type": "object", "properties": {}},
        }
        for t in tool_definitions
    ]
    ok, message = write_tool_manifest(Path(plugin_dir), tools)
    assert ok, message

    generated = Path(plugin_dir) / "src" / "tools" / "tool-manifest.generated.ts"
    assert generated.is_file(), f"manifest not written: {generated}"
    manifest_schemas: dict[str, Any] = {}
    for line in generated.read_text(encoding="utf-8").splitlines():
        match = _MANIFEST_LINE_RE.match(line)
        if match:
            manifest_schemas[json.loads(match.group(1))] = json.loads(match.group(3))

    for name in CANONICAL_STRUCTURED_EDA_TOOLS:
        assert name in manifest_schemas, f"{name} missing from the generated OpenClaw manifest"
        live = by_name[name].get("parameters") or {"type": "object", "properties": {}}
        assert manifest_schemas[name] == live, (
            f"OpenClaw manifest schema for {name} drifted from the live registry"
        )


def assert_plan_step_identity(records: list[dict[str, Any]], *, field: str = "plan_step_id") -> None:
    """Persisted evidence is attributed by stable step id, never by step name."""
    for record in records:
        value = str(record.get(field) or "")
        assert value == "" or PLAN_STEP_ID_RE.fullmatch(value), (
            f"record {record.get('finding_id') or record.get('hypothesis_id') or record} "
            f"carries a non-stable {field}: {value!r}"
        )


def assert_preview_cap(evidence: list[dict[str, Any]]) -> None:
    """Inline evidence anchors obey the shared 20-row / 50-KiB preview caps."""
    from dataclaw_eda.evidence import TABLE_PREVIEW_MAX_BYTES, TABLE_PREVIEW_MAX_ROWS

    for anchor in evidence:
        if not isinstance(anchor, dict) or anchor.get("kind") != "inline_summary":
            continue
        summary = anchor.get("summary")
        if isinstance(summary, list):
            assert len(summary) <= TABLE_PREVIEW_MAX_ROWS, (
                f"inline summary exceeds {TABLE_PREVIEW_MAX_ROWS} rows: {len(summary)}"
            )
        encoded = json.dumps(summary, default=str).encode("utf-8")
        assert len(encoded) <= TABLE_PREVIEW_MAX_BYTES + 1024, (
            f"inline summary exceeds the {TABLE_PREVIEW_MAX_BYTES}-byte cap: {len(encoded)}"
        )
