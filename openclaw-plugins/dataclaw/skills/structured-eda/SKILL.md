---
name: structured_eda
description: Run goal-directed exploratory data analysis tailored to the user's question, domain, unit of observation, problem type, data types, quality risks, and relationship/correlation structure.
tags: [data, analysis, eda, exploratory-analysis, data-quality, profiling]
---

## When to use

Use this skill when the user asks to explore, understand, profile, audit, or prepare a dataset before modeling, dashboarding, reporting, segmentation, forecasting, survey analysis, or decision support.

Use `structured_eda` instead of a generic profile when the analysis needs judgment: the goal, domain, data grain, data types, or downstream use should change what gets checked and how results are interpreted.

If the user only asks for a quick profile, run the compact version: shape, schema, missingness, duplicates, key distributions, obvious quality flags, and 3-5 first findings.

## The problem this solves

"Understand this dataset well enough to choose the right next analysis."

EDA is not one universal checklist. A churn dataset, clinical table, public survey, time-series log, finance ledger, text corpus, and geospatial file need different checks. The user's goal is essential: prediction, explanation, monitoring, causal investigation, dashboarding, data-quality audit, or research readout each changes the EDA.

## First questions (in order)

Ask only what materially changes the EDA. If the user's request already answers these, state your reading in one line and proceed.

1. What decision, question, or deliverable should this EDA support?
2. What is one row: customer, order, patient visit, survey respondent, transaction, event, document, time period, location, or something else?
3. Is there a target, outcome, KPI, segment, time period, or comparison group that matters?
4. Are there domain rules or known caveats: valid ranges, impossible values, regulatory constraints, sampling design, event definitions, leakage risks?
5. What should the output become: notebook, dashboard, model-readiness report, data-quality audit, or research summary?

If the goal is missing, ask: "What question or decision should this EDA support?" Do not start full structured EDA without either a user-provided goal or an explicit goal-discovery scope. If the user asked for open-ended exploration, a quick profile, or cannot provide a goal yet, proceed with a **goal-discovery EDA** and explicitly label the provisional goal as: "understand data structure, quality, and candidate analysis directions."

## Choose the EDA mode

Pick the primary mode from the user goal. Add secondary checks when the data demands it.

| Mode | Use when | Extra focus |
|---|---|---|
| Goal-discovery EDA | User gives a dataset but no clear question | data inventory, data grain, column roles, candidate questions, quality blockers |
| Data-quality EDA | User asks if data is usable/trustworthy | schema validity, missingness patterns, duplicates, impossible values, constraints, key integrity |
| Modeling-readiness EDA | User plans prediction/classification/regression | target distribution, split strategy, leakage, feature availability at prediction time, imbalance, multicollinearity |
| Dashboard/KPI EDA | User wants reporting or monitoring | metric definitions, numerator/denominator, grain, time coverage, dimensions, aggregation risk |
| Survey/research EDA | Data is survey/poll/research responses | sampling frame, weights, nonresponse, Likert handling, multi-select fields, segment Ns, significance/effect sizes |
| Time-series EDA | Rows are time-indexed or event timestamps matter | time grain, gaps, timezone, seasonality, trend, changepoints, autocorrelation, future leakage |
| Event/log/funnel EDA | Rows are user/system events | identity resolution, sessionization, event order, duplicate events, bot/system noise, censoring |
| Text/document EDA | Rows contain free text/documents | document length, language, empty text, duplicates, label quality, PII, topic/entity coverage |
| Geospatial EDA | Rows contain location/geometry | coordinate validity, CRS, spatial granularity, joins, area/population normalization |
| Causal/experiment EDA | User asks "impact", "effect", or A/B test | treatment/control balance, assignment, pre-periods, confounders, sample ratio mismatch, interference |

## Data-type routing

Assign semantic roles before analysis. Do not treat a column as numeric just because its dtype is numeric.

| Data type / role | Checks |
|---|---|
| Identifier/key | uniqueness, duplicates, joinability, accidental reuse; never use as a numeric measure |
| Numeric continuous | range, units, missingness, skew, zero/negative validity, outliers, transformations if needed |
| Counts | non-negative constraint, zero inflation, exposure/denominator, long tail |
| Money | currency, time period, inflation/price basis, negative values, refunds, outliers |
| Rates/percentages | valid bounds, denominator, small-denominator instability |
| Categorical nominal | cardinality, rare levels, spelling/standardization, imbalance, unknown/other buckets |
| Ordinal/Likert | preserve order; do not treat as interval unless justified |
| Boolean | prevalence, missing vs false, inconsistent encodings |
| Datetime | parse failures, min/max, timezone, grain, gaps, seasonality, event order |
| Free text | empty strings, length, language, duplicates, sensitive data, label quality |
| Target/outcome | distribution, imbalance, missing target, censoring, leakage through derived fields |
| Multi-label/multi-select | delimiter, multiple response handling, denominator definition |
| Geographic | coordinate validity, boundary level, CRS, spatial duplicates, normalization |

## Analytical sequence

1. **Restate the goal and assumptions.** Name the EDA mode, user goal, expected artifact, and provisional assumptions. If the goal is vague, say you are running goal-discovery EDA.
2. **Load and inventory the data.** Show dataset name/id, row count, column count, source, time coverage if available, and sample rows. Use DataClaw dataset tools for quick inspection and a notebook for durable work.
3. **Define the unit of observation.** State what one row represents. Identify primary keys, natural keys, duplicated entities, and whether the data grain matches the user's goal.
4. **Build a column role map.** For each important column, assign semantic role: id, dimension, measure, target, timestamp, text, geography, weight, grouping, or derived field.
5. **Audit data quality.** Missingness counts and rates, duplicate rows/entities, mixed types, parse failures, impossible values, invalid categories, out-of-range values, and columns with too little variation.
6. **Run goal-specific checks.** Based on the EDA mode, inspect target/KPI/segment/time variables first. Do not spend equal time on irrelevant columns.
7. **Univariate analysis.** For key columns, inspect distributions with appropriate summaries: median/IQR for skew, mean/std where useful, frequency tables for categories, min/max for ranges, and time coverage for dates.
8. **Relationship analysis.** Use bivariate and multivariate checks guided by the goal:
   - numeric vs numeric: scatter, correlation, trend, nonlinearity, outliers
   - categorical vs numeric: grouped distribution, median/mean with sample sizes
   - categorical vs categorical: contingency table, proportions, chi-square only if appropriate
   - time vs metric: trend, seasonality, gaps, changepoints
   - segment vs outcome: effect size and uncertainty, not just sorted averages
9. **Correlation audit.** Compute correlations only for variables where correlation is meaningful. Exclude ids, codes, leakage fields, constants, and arbitrary labels. Prefer:
   - Pearson for roughly linear continuous relationships
   - Spearman for monotonic or ordinal relationships
   - Cramer's V or normalized contingency summaries for categorical relationships
   Always state correlation is not causation and flag likely confounding.
10. **Outlier and anomaly review.** Separate data errors from real extreme values. Do not drop outliers without a domain reason and a before/after note.
11. **Domain and problem review.** Ask: do findings make sense in the domain? Are there missing constraints, denominators, sampling caveats, time effects, or operational definitions that could change interpretation?
12. **Loop on emerging insights.** When a finding changes the likely problem, data grain, quality risk, target definition, segmentation, correlation story, or domain interpretation, run a focused follow-up loop before finalizing. Keep loops small and documented.
13. **Readiness verdict.** State what the data is ready for and what it is not ready for: dashboarding, modeling, causal claims, survey readout, segmentation, forecasting, or further cleaning.
14. **Summarize first findings.** Provide 3-7 findings, each with evidence and caveat. Include recommended next steps.

## Insight loop behavior

EDA is iterative. Treat every material surprise as a candidate insight, then decide whether it deserves another loop.

Use this loop:

1. **Observe.** Name the new pattern, anomaly, data-quality issue, segment difference, correlation, or domain inconsistency.
2. **Interpret.** Explain why it might matter for the user's goal. Is it a real signal, data artifact, leakage risk, denominator issue, or domain constraint?
3. **Branch.** Choose one focused follow-up check that can confirm, weaken, or reframe the insight.
4. **Validate.** Run the smallest useful query, summary, or chart. Compare across segments, time, missingness groups, or relevant controls when needed.
5. **Decide.** Mark the insight as confirmed, weakened, unresolved, or blocked by missing domain/user input.
6. **Update.** Revise the EDA mode, assumptions, column roles, readiness verdict, or next-step recommendation if the insight changes them.

Trigger a loop when you see:

- unexpected missingness, duplicates, parse failures, or impossible values
- a possible mismatch between row grain and the user's goal
- a new segment, subgroup, time period, or geography that behaves differently
- target imbalance, label-quality issues, or possible leakage
- a correlation that may be outlier-driven, nonlinear, confounded, or segment-specific
- a reversal such as Simpson's paradox after segmenting
- an outlier cluster that may represent a real population, process issue, or data error
- a metric denominator, unit, or aggregation definition that changes interpretation
- domain evidence that makes a statistically interesting result implausible or risky

Looping rules:

- One loop = one follow-up question, one check, one interpretation, one decision.
- Default to at most 3 insight loops in one EDA pass. Go deeper only if the user approves, the finding blocks the stated goal, or the loop is required to avoid a materially wrong conclusion.
- Do not chase every curiosity. Prioritize loops that can change the user's answer, artifact, or readiness verdict.
- If a loop reveals a different primary goal, state the pivot and continue under the new EDA mode.
- If two plausible branches require a domain choice, ask the user instead of silently choosing.
- Stop looping when new checks no longer change the conclusions, when the remaining questions require user/domain input, or when the agreed scope is complete.
- Keep an insight log in the notebook/report: insight, evidence, follow-up check, decision, caveat.

## Correlation and relationship rules

- Never lead with a correlation matrix unless the user goal is relationship exploration and the variables make sense for correlation.
- Do not correlate ids, postal codes, account numbers, encoded categories, or timestamps represented as integers.
- Use plots to check whether a correlation is driven by outliers, nonlinear structure, clusters, or segment mix.
- For many variables, show only the most relevant relationships and explain the selection rule.
- For modeling EDA, flag high feature-feature correlation as multicollinearity risk, but separately check target leakage.
- For causal questions, correlation is only descriptive. Do not imply effect without design evidence.
- For time series, check autocorrelation and shared trends before claiming one metric relates to another.
- For surveys, report segment Ns and uncertainty before claiming one group differs from another.

## Domain-sensitive checks

- **Business/KPI data:** confirm metric definitions, numerator/denominator, time grain, fiscal calendar, segment definitions, and whether records are events or entities.
- **Healthcare/clinical:** protect sensitive fields, inspect coding systems, impossible physiological values, censoring, repeated visits, cohort definition, and confounding.
- **Finance/accounting:** check currency, sign conventions, refunds/reversals, time periods, leakage from future outcomes, and extreme-value handling.
- **Marketing/product:** distinguish users, accounts, sessions, events, and campaigns; check attribution windows, bot/internal traffic, cohorts, and survivorship bias.
- **Operations/supply chain:** inspect units, locations, lead times, stockouts, seasonality, capacity limits, and censored demand.
- **Public/social science data:** inspect sampling frame, weights, geography, demographic coverage, coding changes, and small subgroup sizes.
- **Machine-learning datasets:** inspect target definition, train/test split feasibility, leakage, class imbalance, label quality, and feature availability at prediction time.

## Output and visualization rules

Fetch the `visualization` skill before producing the first final chart or report artifact. Follow its conventions for final visual output: Plotly charts via `fig.show()`, metric tiles for headline checks, and report sections when producing a polished artifact or living-report entry.

Use visuals that match the goal:

- Missingness: sorted bar chart or heatmap when patterns matter.
- Numeric distribution: histogram/box/violin, with log scale only when explained.
- Categorical distribution: sorted bar chart; group rare levels when needed.
- Time: line chart with gaps and time grain clearly labelled.
- Relationship: scatter, grouped box/violin, faceted bars, or heatmap depending on data types.
- Correlation: small, relevant matrix or ranked relationship table, not a giant unreadable heatmap.

Every chart must have a title, labelled axes with units, sample size when relevant, and a one-line interpretation plus caveat.

## Standard deliverables

- EDA objective and assumptions.
- Unit-of-observation statement.
- Column role map for important fields.
- Data-quality table: missingness, duplicates, invalid values, parse/type issues.
- Goal-specific findings and plots.
- Insight log showing material discoveries, follow-up loops, decisions, and caveats.
- Relationship/correlation audit, with exclusions and caveats.
- Domain caveats and interpretation risks.
- Readiness verdict: what analysis is safe next, what is blocked, and what must be cleaned or clarified.
- Recommended next actions.

## Pitfalls to avoid

- Running the same EDA template for every dataset.
- Treating EDA as a single linear pass when new findings should change the route.
- Skipping the user's goal or failing to ask for it when it matters.
- Treating numeric-looking ids/codes as continuous variables.
- Treating correlation as causation.
- Missing target leakage or future information before modeling.
- Reporting means on skewed data without medians/quantiles.
- Treating Likert or ordinal fields as interval without justification.
- Ignoring small segment sizes, missing denominators, or sampling weights.
- Dropping outliers silently.
- Assuming missingness is random without evidence.
- Ignoring time, geography, domain constraints, or data grain.
- Producing a wall of charts without a readiness verdict.
