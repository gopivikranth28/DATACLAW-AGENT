# Structured EDA Smoke Example

This is a tiny fixture for reviewing the `structured_eda` skill behavior before building a full notebook example.

## User Goal

"Explore this customer event dataset to understand whether it is ready for a churn-risk model."

## Expected Skill Behavior

- Fetch `structured_eda`, not `data_profiling`, because the user has a modeling-readiness goal.
- Identify the unit of observation as an account-month event record, not a unique customer row.
- Select **Modeling-readiness EDA** as the primary mode, with event/log checks as secondary.
- Treat `customer_id` and `account_id` as identifiers, not numeric variables.
- Treat `churned_next_month` as the target and inspect class balance.
- Flag possible leakage: `support_refund_after_cancel` appears to happen after churn/cancellation.
- Trigger one insight loop around the suspicious leakage field:
  - observe: refund-after-cancel is strongly associated with churn
  - interpret: likely future information
  - branch: compare event timing and field definition
  - decide: exclude from modeling until confirmed safe
- Produce a readiness verdict: usable for exploratory modeling only after leakage review, duplicate entity handling, and missing `last_login_at` review.

## Files

- `customer_events_sample.csv` - small synthetic dataset with deliberate issues.
- `expected_behavior.md` - expected findings and loop behavior.

This fixture is intentionally small. It validates skill routing and judgment, not statistical significance.
