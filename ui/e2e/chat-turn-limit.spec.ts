import { expect, test, type Page } from '@playwright/test'

async function openMockRun(
  page: Page,
  session: { id: string; title: string; createdAt: string },
  sse: string,
  agentRequests: Record<string, unknown>[] = [],
) {
  await page.route('**/api/plugins', route => route.fulfill({ contentType: 'application/json', body: '[]' }))
  await page.route('**/api/data/datasets', route => route.fulfill({ contentType: 'application/json', body: '[]' }))
  await page.route('**/api/chat/sessions?*', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify([session]) }))
  await page.route('**/api/chat/sessions', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify([session]) }))
  await page.route(`**/api/chat/sessions/${session.id}`, route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({ ...session, messages: [], visualArtifacts: [] }),
  }))
  await page.route('**/api/agent', route => {
    const body = route.request().postDataJSON()
    if (body && typeof body === 'object') agentRequests.push(body as Record<string, unknown>)
    return route.fulfill({ contentType: 'text/event-stream', body: sse })
  })
  await page.route('**/api/guardrails/config/session/**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ disabled: [] }) }))
  await page.route('**/api/guardrails', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ guardrails: [] }) }))
  await page.route('**/api/tools', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ tools: [] }) }))
  await page.route('**/api/skills', route => route.fulfill({ contentType: 'application/json', body: '[]' }))
  await page.route('**/api/subagents/', route => route.fulfill({ contentType: 'application/json', body: '[]' }))

  await page.goto(`/chat?session=${session.id}`)
}

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
  const agentRequests: Record<string, unknown>[] = []
  await openMockRun(page, session, sse, agentRequests)

  await expect(page.getByText('Agent stopped after reaching 30 turns')).toBeVisible()
  await expect(page.getByText('Your progress has been saved.', { exact: false })).toBeVisible()
  await expect(page.getByText('Agent stopped after reaching 30 turns')).toHaveCount(1)
  await expect(page.getByText('Action-round limit reached after 30 turns.', { exact: false })).toBeVisible()

  const initialRequestCount = agentRequests.length
  await page.getByRole('button', { name: 'Resume work' }).click()
  await expect.poll(() => agentRequests.length).toBe(initialRequestCount + 1)
  expect(agentRequests.at(-1)?.messages).toEqual([{
    role: 'user',
    content: 'Continue from where you stopped. Review the saved progress and complete the remaining work.',
  }])
})

test('offers resume when compaction is the last checkpoint without a completed response', async ({ page }) => {
  const session = { id: 'session-compaction-resume', title: 'Compacted analysis', createdAt: '2026-07-22T00:00:00Z' }
  const sse = [
    {
      type: 'MESSAGES_SNAPSHOT',
      messages: [
        { id: 'user-compaction', role: 'user', content: 'Finish the long analysis.' },
        {
          id: 'compaction-last-checkpoint',
          role: 'system',
          content: '[COMPACTION:24:8]\nThe analysis has loaded the data and completed profiling. Modeling remains.',
        },
      ],
    },
    { type: 'RUN_FINISHED', threadId: session.id, runId: 'run-compaction-resume' },
  ].map(event => `data: ${JSON.stringify(event)}\n\n`).join('')

  await openMockRun(page, session, sse)

  await expect(page.getByText('Compacted conversation has unfinished work.', { exact: false })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Resume work' })).toBeVisible()
})

test('does not offer resume after a completed assistant response', async ({ page }) => {
  const session = { id: 'session-complete-no-resume', title: 'Completed analysis', createdAt: '2026-07-22T00:00:00Z' }
  const sse = [
    {
      type: 'MESSAGES_SNAPSHOT',
      messages: [
        { id: 'user-complete', role: 'user', content: 'Summarize the result.' },
        { id: 'assistant-complete', role: 'assistant', content: 'The analysis is complete.' },
      ],
    },
    { type: 'RUN_FINISHED', threadId: session.id, runId: 'run-complete-no-resume' },
  ].map(event => `data: ${JSON.stringify(event)}\n\n`).join('')

  await openMockRun(page, session, sse)

  await expect(page.getByText('The analysis is complete.')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Resume work' })).toHaveCount(0)
})
