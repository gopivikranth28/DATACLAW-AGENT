---
name: insight_validation
description: Validate EDA insights on internal recomputation and external plausibility before recording a confirmed finding.
tags: [data, analysis, validation, eda]
---

## When to use

Use this skill inside a structured EDA insight loop before calling `record_eda_finding` with a confirmed disposition or high confidence.

## Validation protocol

One loop validates one claim. Keep the validation focused enough that the evidence can be cited from one or two notebook cells or structured anchors.

1. Restate the candidate insight and the unit of observation.
2. Internal validation: recompute on an independent slice, denominator/grain check, segment/time/missingness cohort, or contradiction scan against `list_eda_findings` and `list_eda_hypotheses`.
3. External validation: compare magnitude and direction against domain priors, known valid ranges, operational definitions, sampling design, user confirmation, or a reference lookup when available.
4. Decide the disposition:
   - `confirmed`: internal status is `validated` and evidence refs are present.
   - `weakened`: the pattern exists but is smaller, segment-specific, denominator-sensitive, or caveated.
   - `rejected`: the follow-up check rules out the hypothesis; record it as a `rejected_hypothesis` finding.
   - `unresolved`: the evidence is insufficient but not blocked by a user/domain dependency.
   - `blocked`: missing domain definition, unavailable data, stale evidence, or required user input prevents a decision.
5. If external validation is unavailable, set `validation.external.status` to `unverified`; the EDA tool will cap confidence and add the mandatory caveat.

## Tool payload shape

Record both axes in the finding:

```json
{
  "validation": {
    "internal": {
      "status": "validated",
      "method": "recomputed by segment and checked denominator grain",
      "evidence_refs": ["notebook_cell:abc123"]
    },
    "external": {
      "status": "unverified",
      "basis": "none",
      "note": "No deployment-domain source available in this session"
    }
  }
}
```

High confidence requires internal `validated` plus non-empty `evidence_refs`. Do not self-certify correctness; validation raises the confidence floor but does not prove truth.
