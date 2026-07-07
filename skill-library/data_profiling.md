---
name: data_profiling
description: Quick dataset profiling for compact schema, summary statistics, missingness, duplicates, distributions, and obvious quality checks. For goal-directed or domain-sensitive EDA, use structured_eda instead.
tags: [data, analysis, profiling]
---

## When to use

Use this skill for a quick, compact dataset profile: shape, schema, summary statistics, missingness, duplicates, basic distributions, and obvious quality flags.

If the user asks for exploratory data analysis, model readiness, dashboard/KPI preparation, survey/research analysis, time-series/event/text/geospatial/causal exploration, or any analysis where the user's goal/domain should change the path, fetch and follow `structured_eda` instead.

## Quick profile steps

1. **Load and inspect** the dataset. Show the shape (rows x columns), column names, and data types.

2. **Summary statistics** for each column:
   - Numeric: count, mean, std, min, max, median, quartiles
   - Categorical: unique count, top values and frequencies, mode
   - Datetime: range, most common day/hour patterns

3. **Missing values**: Report count and percentage per column. Flag columns with >20% missing.

4. **Duplicates**: Check for duplicate rows and report count.

5. **Distributions**: For numeric columns, note skewness. For categorical columns with <20 unique values, show value counts.

6. **Correlations**: For a quick profile, compute only a small numeric correlation summary after excluding identifiers, codes, constants, and obvious non-measures. Highlight strong correlations (|r| > 0.7) as relationship candidates, not conclusions.

7. **Data quality flags**: Note any columns that appear to have constant values, high cardinality, or mixed types.

Present results in clear tables and summarize 3-5 key findings at the end.

## Stop condition

Do not continue into follow-up loops, causal interpretation, modeling recommendations, or domain-heavy conclusions from this skill alone. If the profile reveals material quality risks, target/metric questions, surprising relationships, or domain-specific caveats, switch to `structured_eda`.
