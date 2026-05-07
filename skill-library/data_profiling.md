---
name: data_profiling
description: Comprehensive dataset profiling with statistics, distributions, and quality checks
tags: [data, analysis, profiling]
---

When asked to profile a dataset, follow these steps:

1. **Load and inspect** the dataset. Show the shape (rows x columns), column names, and data types.

2. **Summary statistics** for each column:
   - Numeric: count, mean, std, min, max, median, quartiles
   - Categorical: unique count, top values and frequencies, mode
   - Datetime: range, most common day/hour patterns

3. **Missing values**: Report count and percentage per column. Flag columns with >20% missing.

4. **Duplicates**: Check for duplicate rows and report count.

5. **Distributions**: For numeric columns, note skewness. For categorical columns with <20 unique values, show value counts.

6. **Correlations**: Compute pairwise correlations for numeric columns. Highlight strong correlations (|r| > 0.7).

7. **Data quality flags**: Note any columns that appear to have constant values, high cardinality, or mixed types.

Present results in clear tables and summarize key findings at the end.
