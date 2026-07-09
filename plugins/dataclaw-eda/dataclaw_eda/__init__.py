"""dataclaw-eda - structured exploratory analysis ledger plugin."""

from __future__ import annotations

from dataclaw.plugins.base import PluginContext, PluginUIManifest
from dataclaw.providers.tool.implementations.python_tool import PythonTool

from dataclaw_eda import tools
from dataclaw_eda.hooks import eda_context_hook, eda_evidence_hook
from dataclaw_eda.router import router as eda_router


class EdaPlugin:
    name = "dataclaw-eda"
    depends_on = ["dataclaw-plans", "dataclaw-notebooks", "dataclaw-artifacts"]

    def register(self, ctx: PluginContext) -> None:
        ctx.include_api_router(eda_router, prefix="/eda", tags=["eda"])
        ctx.hooks.register("preToolCallHook", eda_context_hook)
        ctx.hooks.register("postToolCallHook", eda_evidence_hook)

        for name, description, fn, parameters in _tool_defs():
            ctx.tool_registry.register_tool(
                PythonTool(name=name, description=description, fn=fn, parameters=parameters)
            )

    def ui_manifest(self) -> PluginUIManifest:
        return PluginUIManifest(id="eda", label="EDA", icon="", pages=[])


def _tool_defs():
    selection_schema = {
        "type": "object",
        "properties": {
            "screened_n": {"type": "integer", "minimum": 0},
            "selection_rule": {"type": "string"},
            "correction": {"type": "string", "enum": ["none", "fdr_bh", "bonferroni", "holdout_confirmed"], "default": "none"},
        },
        "required": ["screened_n", "selection_rule", "correction"],
    }
    hypothesis_item = {
        "type": "object",
        "properties": {
            "statement": {"type": "string"},
            "rationale": {"type": "string"},
            "source": {
                "type": "string",
                "enum": ["user_goal", "mode_expected_risk", "domain_prior", "data_signal", "prior_finding", "reviewer"],
            },
            "priority": {"type": "string", "enum": ["high", "medium", "low"], "default": "medium"},
            "covers_checks": {"type": "array", "items": {"type": "string"}, "default": []},
            "selection": selection_schema,
        },
        "required": ["statement", "rationale", "source"],
    }
    evidence_schema = {
        "description": "Evidence anchors: notebook_cell, artifact_section, dataset_profile, inline_summary, query_card, or interpretive_note",
        "oneOf": [{"type": "object"}, {"type": "array", "items": {"type": "object"}}, {"type": "string"}],
    }
    validation_schema = {
        "type": "object",
        "properties": {
            "internal": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": ["validated", "failed", "not_checked"], "default": "not_checked"},
                    "method": {"type": "string", "default": ""},
                    "evidence_refs": {"type": "array", "items": {"type": "string"}, "default": []},
                },
            },
            "external": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": ["validated", "unverified", "implausible", "not_checked"], "default": "not_checked"},
                    "basis": {"type": "string", "enum": ["domain_prior", "reference_lookup", "user_confirmation", "none"], "default": "none"},
                    "note": {"type": "string", "default": ""},
                },
            },
        },
    }
    return [
        (
            "propose_eda_hypotheses",
            "Record a prioritized batch of structured EDA hypotheses in the ledger",
            tools.propose_eda_hypotheses,
            {
                "type": "object",
                "properties": {
                    "hypotheses": {"type": "array", "items": hypothesis_item, "maxItems": 7},
                    "dataset_id": {"type": "string"},
                    "version_id": {"type": "string"},
                },
                "required": ["hypotheses"],
            },
        ),
        (
            "update_eda_hypothesis",
            "Append a disposition/status transition for an EDA hypothesis",
            tools.update_eda_hypothesis,
            {
                "type": "object",
                "properties": {
                    "hypothesis_id": {"type": "string"},
                    "status": {"type": "string", "enum": ["open", "testing", "confirmed", "rejected", "unresolved_needs_domain_input", "out_of_scope"]},
                    "disposition_reason": {"type": "string", "default": ""},
                    "linked_finding_ids": {"type": "array", "items": {"type": "string"}, "default": []},
                    "priority": {"type": "string", "enum": ["high", "medium", "low"]},
                    "loop_index": {"type": "integer", "minimum": 1},
                },
                "required": ["hypothesis_id", "status"],
            },
        ),
        (
            "list_eda_hypotheses",
            "List EDA hypotheses by dataset, plan step, status, source, or priority",
            tools.list_eda_hypotheses,
            {
                "type": "object",
                "properties": {
                    "dataset_id": {"type": "string"},
                    "plan_step_id": {"type": "string"},
                    "status": {"type": "string"},
                    "source": {"type": "string"},
                    "priority": {"type": "string"},
                },
            },
        ),
        (
            "record_eda_finding",
            "Record a structured EDA finding with evidence, validation, and optional hypothesis disposition",
            tools.record_eda_finding,
            {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "finding_type": {"type": "string", "enum": ["distribution", "missingness", "outlier", "segment_difference", "correlation_candidate", "leakage_risk", "readiness", "rejected_hypothesis", "data_quality", "caveat"]},
                    "summary": {"type": "string"},
                    "evidence": evidence_schema,
                    "dataset_id": {"type": "string"},
                    "version_id": {"type": "string"},
                    "severity": {"type": "string", "enum": ["info", "warning", "blocker"], "default": "info"},
                    "caveat": {"type": "string", "default": ""},
                    "next_action": {"type": "string", "default": ""},
                    "confidence": {"type": "string", "enum": ["low", "medium", "high"], "default": "medium"},
                    "hypothesis_id": {"type": "string"},
                    "hypothesis_status": {"type": "string", "enum": ["open", "testing", "confirmed", "rejected", "unresolved_needs_domain_input", "out_of_scope"]},
                    "disposition": {"type": "string", "enum": ["confirmed", "weakened", "rejected", "unresolved", "blocked"], "default": "unresolved"},
                    "validation": validation_schema,
                    "covers_checks": {"type": "array", "items": {"type": "string"}, "default": []},
                    "loop_index": {"type": "integer", "minimum": 1},
                    "selection": selection_schema,
                },
                "required": ["title", "finding_type", "summary", "evidence", "dataset_id"],
            },
        ),
        (
            "supersede_eda_finding",
            "Supersede an EDA finding without deleting history",
            tools.supersede_eda_finding,
            {
                "type": "object",
                "properties": {
                    "finding_id": {"type": "string"},
                    "reason": {"type": "string"},
                    "replacement_id": {"type": "string"},
                },
                "required": ["finding_id", "reason"],
            },
        ),
        (
            "list_eda_findings",
            "List EDA findings by dataset, plan step, status, severity, type, or hypothesis",
            tools.list_eda_findings,
            {
                "type": "object",
                "properties": {
                    "dataset_id": {"type": "string"},
                    "plan_step_id": {"type": "string"},
                    "status": {"type": "string"},
                    "severity": {"type": "string"},
                    "finding_type": {"type": "string"},
                    "hypothesis_id": {"type": "string"},
                },
            },
        ),
        (
            "read_eda_finding",
            "Read one EDA finding with full evidence and validation metadata",
            tools.read_eda_finding,
            {"type": "object", "properties": {"finding_id": {"type": "string"}}, "required": ["finding_id"]},
        ),
        (
            "summarize_eda_readiness",
            "Evaluate and persist an EDA readiness verdict for a dataset and purpose",
            tools.summarize_eda_readiness,
            {
                "type": "object",
                "properties": {
                    "dataset_id": {"type": "string"},
                    "version_id": {"type": "string"},
                    "purpose": {"type": "string", "enum": ["query", "dashboard", "modeling"], "default": "dashboard"},
                    "required_checks": {"type": "array", "items": {"type": "string"}, "default": []},
                    "mode": {"type": "string"},
                    "loop_index": {"type": "integer", "minimum": 1},
                },
                "required": ["dataset_id"],
            },
        ),
    ]
