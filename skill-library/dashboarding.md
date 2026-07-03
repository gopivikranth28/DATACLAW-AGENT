---
name: dashboarding
description: Turn a dataset into a clear, non-misleading dashboard that directly answers a stated question — honest axes, appropriate chart types, no chartjunk. Produces KPI tiles and interactive charts in the App panel, ready to publish.
tags: [visualization, dashboarding, reporting, charts]
---

## When to use
The user has a dataset and a specific question, and wants a clean, shareable
visual answer — "build a dashboard", "show me who/what/when", "visualize this".
Render all output per the `visualization` skill conventions (Plotly via
`fig.show()`, KPIs via `display_metric`, captions via `display_cell_output`);
the App panel and published page are the dashboard surface.

## The problem this solves
"Turn this data into a dashboard that answers my question" — without the
misleading axes, wrong chart types, and decoration that plague auto-generated
dashboards.

## First questions (in order)
1. What is the single question this dashboard must answer? If the request
   contains several, pick the primary one and say so — every element must
   serve it.
2. Who is the audience and what decision does this inform?
3. What is the time grain and grouping (daily, weekly, by segment)?

If the user's request already answers these, don't re-ask — state your
reading in one line and proceed.

## Analytical sequence
1. **Question scoping** — reduce to one primary question; all charts serve it.
2. **Data sanity pass** — shape, types, missing values, duplicates, and the
   time range actually covered. Note anything that limits the answer.
3. **Metric selection** — which 2–3 KPIs directly answer the question?
   Emit them as metric tiles first (they headline the dashboard).
4. **Chart-type selection** — match data type to chart type (see the
   `visualization` skill's selection table). One chart per sub-question,
   2–4 charts total, most important first.
5. **Layout** — KPI tiles, then the primary chart, then supporting detail.
   Production order is the dashboard order.
6. **Annotation** — every chart gets a title, labelled axes with units, and a
   one-line caption: stat + caveat (attach via `display_cell_output`).
7. **Misleading-viz audit** — run the pitfall checklist below before
   declaring the dashboard done. Fix what fails; don't just note it.

## Pitfalls (audit checklist)
- Truncated y-axis that exaggerates differences — bars start at zero
- Dual y-axis with incompatible units — almost always misleading; split into
  two charts instead
- Pie chart with more than 5 slices — use a bar chart
- 3D charts — always chartjunk
- Missing axis labels, units, or chart titles
- Trend lines on scatter without reporting uncertainty
- Cumulative charts presented as if they were per-period growth
- Categorical axes sorted arbitrarily — sort by value unless order is inherent
  (time, ordinal scales)

## Standard deliverables
- 2–3 KPI metric tiles answering the stated question
- 2–4 Plotly charts, each with a one-sentence insight caption (stat + caveat)
- A closing summary in chat: the answer to the stated question in 2–3
  sentences, with the main caveat
- Remind the user the dashboard is publishable from the App tab
