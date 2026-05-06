---
name: notebook_report
description: Create structured Jupyter notebook reports with narrative, code, and visualizations
tags: [notebooks, reporting, visualization]
---

When asked to create a report or analysis notebook, follow this structure:

## Notebook structure

1. **Title cell** (markdown): Report title, date, and one-line summary of the objective.

2. **Setup cell** (code): Import libraries (pandas, matplotlib/seaborn, etc.) and configure display settings. Use `%matplotlib inline`.

3. **Data loading cell** (code): Load the dataset(s) and show shape/head.

4. **Analysis sections**: For each question or topic:
   - **Markdown cell**: State what you're investigating and why
   - **Code cell**: Perform the analysis
   - **Markdown cell**: Interpret the results

5. **Visualizations**: Create charts where they add clarity. Always include:
   - Descriptive title
   - Labeled axes
   - Appropriate chart type (bar for comparisons, line for trends, scatter for relationships)

6. **Summary cell** (markdown): Key findings as bullet points, with any recommended next steps.

## Guidelines

- Keep code cells focused — one logical step per cell
- Use markdown headers (##) to create a scannable table of contents
- Round numbers for display and use consistent formatting
- If a finding is surprising, call it out explicitly
