import { expect, test } from '@playwright/test'

test('renders a repeated notebook chart only once and keeps its latest caption', async ({ page }) => {
  const sessionId = 'session-chart-dedup'
  const session = { id: sessionId, title: 'Chart analysis', createdAt: '2026-07-22T00:00:00Z' }
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
  const sse = [
    { type: 'MESSAGES_SNAPSHOT', messages },
    { type: 'RUN_FINISHED', threadId: sessionId, runId: 'run-chart-dedup' },
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

  await expect(page.locator('.chat-cell-output__plot')).toHaveCount(1)
  await expect(page.getByText('Latest evidence caption')).toBeVisible()
})
