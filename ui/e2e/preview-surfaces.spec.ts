import { expect, test } from '@playwright/test'

test('renders app report previews through the workspace document endpoint', async ({ page }) => {
  const previewRequests: string[] = []

  await page.route('**/api/chat/sessions/session-report-preview', async route => {
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        id: 'session-report-preview',
        title: 'Structured EDA Review',
        createdAt: '2026-07-09T00:00:00Z',
        visualArtifacts: [{
          id: 'report-artifact',
          kind: 'report',
          html_path: 'reports/structured eda report.html',
          title: 'Structured EDA Report',
          updated_at: 'cache-v2',
        }],
      }),
    })
  })

  await page.route('**/api/workspace/preview/document?**', async route => {
    previewRequests.push(route.request().url())
    await route.fulfill({
      contentType: 'text/html',
      body: '<!doctype html><html><body><main>Report preview loaded</main></body></html>',
    })
  })

  await page.goto('/app/session-report-preview')

  await expect(page.getByText('Structured EDA Review')).toBeVisible()
  await expect(page.getByText('Structured EDA Report')).toBeVisible()
  await expect(page.frameLocator('[data-testid="report-preview-frame"]').getByText('Report preview loaded')).toBeVisible()
  await expect.poll(() => previewRequests.length).toBe(1)

  const previewUrl = new URL(previewRequests[0])
  expect(previewUrl.pathname).toBe('/api/workspace/preview/document')
  expect(previewUrl.searchParams.get('path')).toBe('reports/structured eda report.html')
  expect(previewUrl.searchParams.get('v')).toBe('cache-v2')
})

test('renders the chat artifact sidebar living report preview', async ({ page }) => {
  const artifactRequests: string[] = []
  const runId = 'run-artifact-preview'
  const threadId = 'session-artifact-preview'
  const sse = [
    { type: 'RUN_STARTED', threadId, runId },
    { type: 'MESSAGES_SNAPSHOT', messages: [] },
    { type: 'RUN_FINISHED', threadId, runId },
  ].map(event => `data: ${JSON.stringify(event)}\n\n`).join('')

  await page.route('**/api/plugins', async route => {
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify([{ id: 'artifacts', name: 'Artifacts', label: 'Artifacts', icon: '', pages: [], config_schema: null }]),
    })
  })
  await page.route('**/api/chat/sessions?*', async route => {
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify([{ id: threadId, title: 'Artifact Preview Session', createdAt: '2026-07-09T00:00:00Z' }]),
    })
  })
  await page.route('**/api/chat/sessions', async route => {
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify([{ id: threadId, title: 'Artifact Preview Session', createdAt: '2026-07-09T00:00:00Z' }]),
    })
  })
  await page.route(`**/api/chat/sessions/${threadId}`, async route => {
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        id: threadId,
        title: 'Artifact Preview Session',
        createdAt: '2026-07-09T00:00:00Z',
        messages: [],
        visualArtifacts: [],
      }),
    })
  })
  await page.route('**/api/agent', async route => {
    await route.fulfill({
      contentType: 'text/event-stream',
      body: sse,
    })
  })
  await page.route('**/api/guardrails/config/session/**', async route => {
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ disabled: [] }) })
  })
  await page.route('**/api/guardrails', async route => {
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ guardrails: [] }) })
  })
  await page.route('**/api/tools', async route => {
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ tools: [] }) })
  })
  await page.route('**/api/skills', async route => {
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify([]) })
  })
  await page.route('**/api/subagents/', async route => {
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify([]) })
  })
  await page.route('**/api/artifacts?**', async route => {
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        artifacts: [{
          artifact_id: 'live-session-artifact',
          kind: 'living_report',
          title: 'Session living report',
          session_id: threadId,
          latest_version: 0,
          versions: [],
          updated_at: '2026-07-09T00:00:00Z',
          url: `/api/artifacts/live-session-artifact/living?session_id=${threadId}`,
        }],
      }),
    })
  })
  await page.route('**/api/artifacts/live-session-artifact/living?**', async route => {
    artifactRequests.push(route.request().url())
    await route.fulfill({
      contentType: 'text/html',
      body: '<!doctype html><html><body><main>Living report loaded</main></body></html>',
    })
  })

  await page.goto(`/chat?session=${threadId}`)
  await page.getByText('Artifacts').click()

  await expect(page.getByText('Session living report · live')).toBeVisible()
  await expect(page.frameLocator('[data-testid="living-report-preview-frame"]').getByText('Living report loaded')).toBeVisible()
  await expect.poll(() => artifactRequests.length).toBe(1)

  const artifactUrl = new URL(artifactRequests[0])
  expect(artifactUrl.pathname).toBe('/api/artifacts/live-session-artifact/living')
  expect(artifactUrl.searchParams.get('session_id')).toBe(threadId)
})
