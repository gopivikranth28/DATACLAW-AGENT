import { expect, test } from '@playwright/test'

test('shows a persisted max-turn notice without duplicating the live event', async ({ page }) => {
  const sessionId = 'session-turn-limit'
  const noticeId = 'run-notice-turn-limit'
  const notice = 'The configured limit of 30 agent turns was reached before the task finished. Your progress has been saved. Send "Continue from where you stopped" to resume.'
  const session = { id: sessionId, title: 'Long analysis', createdAt: '2026-07-22T00:00:00Z' }
  const sse = [
    {
      type: 'MESSAGES_SNAPSHOT',
      messages: [{
        id: noticeId,
        role: 'system',
        content: `[RUN_NOTICE:max_turns:30]\n${notice}`,
      }],
    },
    {
      type: 'CUSTOM',
      name: 'agent:max_turns_reached',
      value: { messageId: noticeId, reason: 'max_turns', maxTurns: 30, message: notice },
    },
    { type: 'RUN_FINISHED', threadId: sessionId, runId: 'run-turn-limit' },
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

  await expect(page.getByText('Agent stopped after reaching 30 turns')).toBeVisible()
  await expect(page.getByText('Your progress has been saved.', { exact: false })).toBeVisible()
  await expect(page.getByText('Agent stopped after reaching 30 turns')).toHaveCount(1)
})
