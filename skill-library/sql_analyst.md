---
name: sql_analyst
description: Write and optimize SQL queries against registered datasets using DuckDB
tags: [data, sql, analysis]
---

When the user asks a data question, answer it with SQL using the available DuckDB query tools.

## Approach

1. **Understand the question**: Clarify what metrics, filters, or groupings the user needs.

2. **Explore the data first**: List available datasets and preview the relevant table(s) to understand schema and sample values before writing queries.

3. **Write clear SQL**: Use DuckDB SQL syntax. Prefer CTEs over subqueries for readability. Always alias columns with descriptive names.

4. **Iterate**: Run the query, check the results, and refine if needed. If results look unexpected, investigate before presenting.

5. **Explain your findings**: After running the query, summarize what the results mean in plain language. Don't just dump a table.

## Best practices

- Use `LIMIT` during exploration to avoid slow queries on large tables
- Use `COUNT(DISTINCT ...)` to understand cardinality before grouping
- Format numbers for readability (round percentages, use commas for large numbers)
- When comparing time periods, always make the comparison explicit (e.g., "vs previous month")
