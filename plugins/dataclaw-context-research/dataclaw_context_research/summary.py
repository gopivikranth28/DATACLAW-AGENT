"""Deterministic summaries for external context findings."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any


def summarize_findings(findings: list[dict[str, Any]]) -> dict[str, Any]:
    by_source = Counter(f.get("source_type", "unknown") for f in findings)
    by_evidence = Counter(f.get("evidence_level", "unverified") for f in findings)
    themes = _theme_findings(findings)
    caveats = []
    if not findings:
        caveats.append("No external context findings are currently saved.")
    return {
        "count": len(findings),
        "source_types": dict(by_source),
        "evidence_levels": dict(by_evidence),
        "themes": themes,
        "caveats": caveats,
        "sources": [
            {
                "id": f.get("id"),
                "title": f.get("title"),
                "url": f.get("url"),
                "evidence_level": f.get("evidence_level"),
                "source_type": f.get("source_type"),
            }
            for f in findings
        ],
    }


def external_context_markdown(findings: list[dict[str, Any]]) -> str:
    summary = summarize_findings(findings)
    source_lines = []
    for finding in findings:
        source_lines.append(
            f"- [{_escape_md(finding.get('title', 'Untitled'))}]({finding.get('url', '')}) "
            f"- {finding.get('source_type', 'unknown')}, evidence: `{finding.get('evidence_level', 'unverified')}`"
        )
    theme_lines = []
    for theme, items in summary["themes"].items():
        theme_lines.append(f"## {theme}\n")
        for item in items:
            theme_lines.append(f"- {item}")
        theme_lines.append("")
    caveats = "\n".join(f"- {c}" for c in summary["caveats"]) or "- No caveats recorded."
    return f"""---
title: "External Context"
kind: "external_context"
tags:
  - "context-research"
  - "external"
---

# External Context

These notes collect cited technical context for the dataset/problem. Findings should be verified before they influence analysis decisions.

## Evidence Summary

- Findings: `{summary['count']}`
- Source types: `{summary['source_types']}`
- Evidence levels: `{summary['evidence_levels']}`

## Caveats

{caveats}

{chr(10).join(theme_lines).rstrip()}

## Sources

{chr(10).join(source_lines) if source_lines else "- No sources saved."}
"""


def _theme_findings(findings: list[dict[str, Any]]) -> dict[str, list[str]]:
    themes: dict[str, list[str]] = defaultdict(list)
    for finding in findings:
        text = " ".join([
            str(finding.get("title", "")),
            str(finding.get("snippet", "")),
        ]).lower()
        label = "Technical Context"
        if any(word in text for word in ("privacy", "bias", "ethical", "fairness")):
            label = "Bias / Privacy / Ethics Considerations"
        elif any(word in text for word in ("missing", "quality", "dirty", "null", "outlier")):
            label = "Data Quality Risks"
        elif any(word in text for word in ("model", "feature", "method", "forecast", "predict")):
            label = "Suggested Methods"
        elif any(word in text for word in ("pitfall", "leak", "mistake", "warning")):
            label = "Common Pitfalls"
        themes[label].append(
            f"{finding.get('title', 'Untitled')} ({finding.get('source_type', 'unknown')}, evidence: {finding.get('evidence_level', 'unverified')})"
        )
    return dict(themes)


def _escape_md(value: str) -> str:
    return str(value).replace("[", "\\[").replace("]", "\\]")
