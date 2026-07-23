import { expect, test } from '@playwright/test'

test('shows report phases and real output activity while a tool is running', async ({ page }) => {
  const sessionId = 'session-tool-progress'
  const callId = 'call-report-progress'
  const session = { id: sessionId, title: 'Report progress', createdAt: '2026-07-22T00:00:00Z' }
  const args = JSON.stringify({
    title: 'Formula One trends',
    report_goal: 'Explain the major trends.',
    insights: [{ title: 'Finding one' }, { title: 'Finding two' }],
    visual_author: { timeout_seconds: 900, max_repair_passes: 3 },
  })
  const sse = [
    { type: 'MESSAGES_SNAPSHOT', messages: [] },
    { type: 'RUN_STARTED', threadId: sessionId, runId: 'run-tool-progress' },
    { type: 'TOOL_CALL_START', toolCallId: callId, toolCallName: 'report_design_report' },
    { type: 'TOOL_CALL_ARGS', toolCallId: callId, delta: args },
    { type: 'TOOL_CALL_END', toolCallId: callId },
    {
      type: 'CUSTOM',
      name: 'tool:progress',
      value: {
        toolCallId: callId,
        toolName: 'report_design_report',
        phase: 'drafting',
        label: 'Drafting the report document',
        activity: 'receiving',
        attempt: 1,
        maxAttempts: 4,
        elapsedMs: 292000,
        outputChars: 84000,
        lastOutputAt: new Date().toISOString(),
        timeoutSeconds: 900,
        startedAt: new Date(Date.now() - 292000).toISOString(),
      },
    },
  ].map(event => `data: ${JSON.stringify(event)}\n\n`).join('')

  await page.route('**/api/plugins', route => route.fulfill({ contentType: 'application/json', body: '[]' }))
  await page.route('**/api/data/datasets', route => route.fulfill({ contentType: 'application/json', body: '[]' }))
  await page.route('**/api/chat/sessions?*', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify([session]) }))
  await page.route('**/api/chat/sessions', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify([session]) }))
  await page.route(`**/api/chat/sessions/${sessionId}`, route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({ ...session, messages: [], visualArtifacts: [] }),
  }))
  await page.route(`**/api/agent/status/${sessionId}`, route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({ running: true, status: 'running', healthy: true, task_status: 'running' }),
  }))
  await page.route('**/api/agent', route => route.fulfill({ contentType: 'text/event-stream', body: sse }))
  await page.route('**/api/guardrails/config/session/**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ disabled: [] }) }))
  await page.route('**/api/guardrails', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ guardrails: [] }) }))
  await page.route('**/api/tools', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ tools: [] }) }))
  await page.route('**/api/skills', route => route.fulfill({ contentType: 'application/json', body: '[]' }))
  await page.route('**/api/subagents/', route => route.fulfill({ contentType: 'application/json', body: '[]' }))

  await page.goto(`/chat?session=${sessionId}`)

  await expect(page.getByText(/Drafting the report document: Formula One trends/)).toBeVisible()
  await expect(page.getByText(/pass 1\/4 · receiving output · 84k chars/)).toBeVisible()
  await expect(page.getByText(/^Designed report/)).toHaveCount(0)
})
