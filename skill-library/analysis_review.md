---
name: analysis_review
description: Review DataClaw analysis outputs against structured evidence, hypotheses, findings, gates, and artifact metadata.
tags: [analysis, review, validation, artifacts, eda]
---

## Reviewer role

Audit coherence between claims, ledger state, and evidence anchors. Do not mutate analysis state. Do not run data queries unless a future scoped read-only reviewer tool explicitly allows it.

## Tool lifecycle

Use `request_analysis_review(scope="plan_step", target_id=plan_step_id)` when a high-risk or EDA-like step is completed and before setting `ready_for_validation: true`. Inspect the gate with `get_review_gate`; resolve checklist findings with `resolve_review_finding` after the underlying issue is fixed, or use `accepted_with_rationale` only when the user explicitly accepts the risk. A checklist-only review may clear ordinary deterministic blockers, but it must remain `unknown` when the request marked the scope as sub-agent-required.

## Review order

1. Hypothesis ledger hygiene:
   - mode expected risks were enumerated
   - completed steps do not leave non-deferred high-priority hypotheses open
   - confirmed/rejected hypotheses have linked findings
   - superseded evidence marks linked hypotheses for reevaluation
2. Findings and validation:
   - confirmed findings have internal validation evidence
   - high confidence is not used without evidence refs
   - external `unverified` findings carry the mandatory caveat
   - blockers and unresolved domain-input questions are visible in readiness
3. Claims to anchors:
   - artifact findings sections created with section schema 2 carry `finding_id` or a valid evidence anchor
   - chart and table metadata includes title/caption and plan-step context
   - final claims do not exceed the evidence in findings, notebooks, MLflow metadata, or living-report events
4. Plan gates:
   - required gates fail while required findings are open
   - checklist-only review is labeled and does not pass sub-agent-required scopes
   - accepted risks include user rationale

## Output contract

When used as a reviewer prompt, return fenced JSON with a `findings` array. Each finding should include:

```json
{
  "severity": "required",
  "category": "hypothesis_hygiene",
  "claim": "Completed EDA step has an open high-priority leakage hypothesis",
  "evidence": ["hyp-1234"],
  "recommendation": "Resolve or defer the hypothesis before marking the step ready",
  "status": "open"
}
```

Prefer precise required findings over broad commentary. Optional suggestions are useful only after required blockers are clear.
