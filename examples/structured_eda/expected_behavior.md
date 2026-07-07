# Expected Structured EDA Behavior

## EDA Mode

Primary mode: Modeling-readiness EDA.

Secondary mode: Event/log EDA, because the rows are monthly customer/account event records.

## Required Checks

- State the goal: assess readiness for a churn-risk model.
- State the unit of observation: account-month event record.
- Build a role map:
  - identifiers: `customer_id`, `account_id`
  - timestamp/month: `event_month`, `last_login_at`
  - measures: `monthly_revenue`, `tickets_30d`
  - categorical dimension: `plan`
  - possible leakage field: `support_refund_after_cancel`
  - target: `churned_next_month`
- Flag duplicated entity/month row for customer/account 105.
- Flag negative `monthly_revenue` as a domain issue needing explanation.
- Flag missing `last_login_at` values and compare missingness to churn.
- Inspect target balance before any modeling.

## Expected Insight Loop

Insight: `support_refund_after_cancel` is associated with churn.

Interpretation: the field name suggests it may be recorded after cancellation, so it may leak future information into a churn model.

Follow-up check: inspect timing/definition and compare whether the value could be known before the prediction point.

Decision: unresolved or likely leakage until a domain owner confirms the field timing. Exclude from modeling-readiness recommendations by default.

## Readiness Verdict

Not ready for a defensible churn model yet.

Ready for exploratory modeling only after:

- leakage review for `support_refund_after_cancel`
- duplicate account-month handling
- explanation or cleaning rule for negative revenue
- missing-login interpretation
- explicit train/test split plan by time or account
