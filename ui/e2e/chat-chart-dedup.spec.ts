import { expect, test, type Page } from '@playwright/test'

async function openMockSession(page: Page, sessionId: string, messages: Record<string, unknown>[]) {
  const session = { id: sessionId, title: 'Chart analysis', createdAt: '2026-07-22T00:00:00Z' }
  const sse = [
    { type: 'MESSAGES_SNAPSHOT', messages },
    { type: 'RUN_FINISHED', threadId: sessionId, runId: `run-${sessionId}` },
  ].map(event => `data: ${JSON.stringify(event)}\n\n`).join('')

  await page.route('**/api/plugins', route => route.fulfill({ contentType: 'application/json', body: '[]' }))
  await page.route('**/api/data/datasets', route => route.fulfill({ contentType: 'application/json', body: '[]' }))
  await page.route('**/api/chat/sessions?*', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify([session]) }))
  await page.route('**/api/chat/sessions', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify([session]) }))
  await page.route(`**/api/chat/sessions/${sessionId}`, route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({ ...session, messages: [], visualArtifacts: [] }),
  }))
  await page.route('**/api/agent', route => route.fulfill({ contentType: 'text/event-stream', body: sse }))
  await page.route('**/api/guardrails/config/session/**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ disabled: [] }) }))
  await page.route('**/api/guardrails', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ guardrails: [] }) }))
  await page.route('**/api/tools', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ tools: [] }) }))
  await page.route('**/api/skills', route => route.fulfill({ contentType: 'application/json', body: '[]' }))
  await page.route('**/api/subagents/', route => route.fulfill({ contentType: 'application/json', body: '[]' }))

  await page.goto(`/chat?session=${sessionId}`)
}

test('renders a repeated notebook chart only once and keeps its latest caption', async ({ page }) => {
  const sessionId = 'session-chart-dedup'
  const figure = {
    data: [{ type: 'bar', x: ['A', 'B'], y: [1, 2] }],
    layout: { title: 'Repeated chart' },
  }
  const executed = JSON.stringify({ cell_index: 8, outputs: [{ type: 'plotly', figure }] })
  const displayed = JSON.stringify({
    cell_index: 8,
    caption: 'Latest evidence caption',
    outputs: [{ type: 'plotly', figure }],
  })
  const messages = [
    { id: 'user-chart', role: 'user', content: 'Show the chart' },
    {
      id: 'assistant-tools',
      role: 'assistant',
      content: '',
      toolCalls: [
        { id: 'call-execute', type: 'function', function: { name: 'execute_cell', arguments: JSON.stringify({ cell_index: 8 }) } },
        { id: 'call-display', type: 'function', function: { name: 'display_cell_output', arguments: JSON.stringify({ cell_index: 8 }) } },
      ],
    },
    { id: 'result-execute', role: 'tool', toolCallId: 'call-execute', content: executed },
    { id: 'result-display', role: 'tool', toolCallId: 'call-display', content: displayed },
  ]
  await openMockSession(page, sessionId, messages)

  await expect(page.locator('.chat-cell-output__plot')).toHaveCount(1)
  await expect(page.getByText('Latest evidence caption')).toBeVisible()
})

test('keeps charts with identical traces but different semantic layouts', async ({ page }) => {
  const sessionId = 'session-chart-layout-collision'
  const data = [{ type: 'scatter', mode: 'lines', x: [1, 2, 3], y: [10, 20, 30] }]
  const overview = {
    data,
    layout: {
      title: 'Full trend',
      xaxis: { range: [1, 3] },
      annotations: [{ x: 2, y: 20, text: 'Midpoint', showarrow: true }],
    },
    config: { displayModeBar: false },
  }
  const focused = {
    data,
    layout: {
      title: 'Focused trend',
      xaxis: { range: [1.5, 2.5] },
      annotations: [{ x: 2, y: 20, text: 'Decision point', showarrow: false }],
    },
    config: { displayModeBar: false },
  }
  const messages = [
    { id: 'user-layouts', role: 'user', content: 'Show both chart views' },
    {
      id: 'assistant-layout-tools',
      role: 'assistant',
      content: '',
      toolCalls: [
        { id: 'call-overview', type: 'function', function: { name: 'display_cell_output', arguments: JSON.stringify({ cell_index: 8 }) } },
        { id: 'call-focused', type: 'function', function: { name: 'display_cell_output', arguments: JSON.stringify({ cell_index: 8 }) } },
      ],
    },
    {
      id: 'result-overview',
      role: 'tool',
      toolCallId: 'call-overview',
      content: JSON.stringify({ cell_index: 8, outputs: [{ type: 'plotly', figure: overview }] }),
    },
    {
      id: 'result-focused',
      role: 'tool',
      toolCallId: 'call-focused',
      content: JSON.stringify({ cell_index: 8, outputs: [{ type: 'plotly', figure: focused }] }),
    },
  ]

  await openMockSession(page, sessionId, messages)

  await expect(page.locator('.chat-cell-output__plot')).toHaveCount(2)
})

test('interleaves chart and table outputs with working steps in execution order', async ({ page }) => {
  const sessionId = 'session-output-execution-order'
  const figure = {
    data: [{ type: 'bar', x: ['A', 'B'], y: [1, 2] }],
    layout: { title: 'Execution-order chart' },
  }
  const table = '<table><thead><tr><th>Team</th><th>Score</th></tr></thead><tbody><tr><td>A</td><td>1</td></tr></tbody></table>'
  const messages = [
    { id: 'user-order', role: 'user', content: 'Run the analysis in order' },
    {
      id: 'assistant-order-tools',
      role: 'assistant',
      content: 'Analysis complete.',
      toolCalls: [
        { id: 'call-query', type: 'function', function: { name: 'data_query_data', arguments: JSON.stringify({ dataset_id: 'sample', sql: 'select 1' }) } },
        { id: 'call-chart', type: 'function', function: { name: 'display_cell_output', arguments: JSON.stringify({ cell_index: 2 }) } },
        { id: 'call-edit', type: 'function', function: { name: 'edit_cell_source', arguments: JSON.stringify({ cell_index: 3, old_string: 'before', new_string: 'after' }) } },
        { id: 'call-table', type: 'function', function: { name: 'execute_cell', arguments: JSON.stringify({ cell_index: 4 }) } },
      ],
    },
    { id: 'result-query', role: 'tool', toolCallId: 'call-query', content: JSON.stringify({ rows: [{ value: 1 }] }) },
    {
      id: 'result-chart',
      role: 'tool',
      toolCallId: 'call-chart',
      content: JSON.stringify({ cell_index: 2, outputs: [{ type: 'plotly', figure }] }),
    },
    { id: 'result-edit', role: 'tool', toolCallId: 'call-edit', content: JSON.stringify({ ok: true }) },
    {
      id: 'result-table',
      role: 'tool',
      toolCallId: 'call-table',
      content: JSON.stringify({ cell_index: 4, outputs: [{ type: 'html', text: table }] }),
    },
  ]

  await openMockSession(page, sessionId, messages)
  await page.locator('.chat-turn__header').click()

  const executionOrder = await page.locator('.chat-turn').evaluate(turn =>
    Array.from(turn.querySelectorAll('.chat-step, .chat-evidence')).map(element =>
      element.classList.contains('chat-evidence')
        ? element.id
        : element.querySelector('.chat-step__label')?.textContent?.trim(),
    ),
  )
  expect(executionOrder).toEqual([
    'Queried sample — select 1',
    'output-call-chart',
    'Edited cell [3] — replaced before',
    'output-call-table',
  ])
})
