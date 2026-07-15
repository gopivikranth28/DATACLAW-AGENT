import { expect, test } from '@playwright/test'

test('opens session experiments from the right rail', async ({ page }) => {
  const sessionId = 'session-experiments'
  const projectSession = { id: 'session-project-only', title: 'Project-only session', projectId: 'project-eda', createdAt: '2026-07-14T00:00:00Z' }
  const sse = [
    { type: 'RUN_STARTED', threadId: sessionId, runId: 'run-experiments' },
    { type: 'MESSAGES_SNAPSHOT', messages: [] },
    { type: 'RUN_FINISHED', threadId: sessionId, runId: 'run-experiments' },
  ].map(event => `data: ${JSON.stringify(event)}\n\n`).join('')

  await page.route('**/api/plugins', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify([{ id: 'data', name: 'Data', label: 'Data', icon: '', pages: [], config_schema: null }]) }))
  await page.route('**/api/data/datasets', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify([{ id: 'fifa-snapshot', name: 'FIFA Snapshot', type: 'local_file', description: 'Tournament data' }]) }))
  await page.route('**/api/chat/sessions?*', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify([{ id: sessionId, title: 'Experiment session', createdAt: '2026-07-14T00:00:00Z' }, projectSession]) }))
  await page.route('**/api/chat/sessions', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify([{ id: sessionId, title: 'Experiment session', createdAt: '2026-07-14T00:00:00Z' }, projectSession]) }))
  await page.route(`**/api/chat/sessions/${sessionId}`, route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({ id: sessionId, title: 'Experiment session', createdAt: '2026-07-14T00:00:00Z', messages: [], visualArtifacts: [] }),
  }))
  await page.route('**/api/mlflow/runs?**', route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({ runs: [{ run_id: 'a1b2c3d4e5', status: 'FINISHED', start_time: 1_784_398_400_000, tags: { 'mlflow.runName': 'Baseline forecast' }, metrics: { accuracy: 0.9182 }, params: { model: 'baseline' }, artifacts: [{ name: 'metrics.json' }] }] }),
  }))
  await page.route('**/api/agent', route => route.fulfill({ contentType: 'text/event-stream', body: sse }))
  await page.route('**/api/guardrails/config/session/**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ disabled: [] }) }))
  await page.route('**/api/guardrails', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ guardrails: [] }) }))
  await page.route('**/api/tools', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ tools: [] }) }))
  await page.route('**/api/skills', route => route.fulfill({ contentType: 'application/json', body: '[]' }))
  await page.route('**/api/subagents/', route => route.fulfill({ contentType: 'application/json', body: '[]' }))

  await page.goto(`/chat?session=${sessionId}`)
  await expect(page.getByRole('button', { name: 'Datasets' })).toBeVisible()
  expect(await page.locator('nav[aria-label="Session panel"] button').evaluateAll(buttons => buttons.map(button => button.getAttribute('aria-label')))).toEqual([
    'Plans', 'Files', 'Reports', 'Datasets', 'Experiments', 'Scope',
  ])
  await page.getByRole('button', { name: 'Datasets' }).click()
  await expect(page.getByText('FIFA Snapshot')).toBeVisible()
  await page.getByRole('button', { name: 'Experiments' }).click()

  await expect(page.getByText('MLflow runs')).toBeVisible()
  await expect(page.getByText('Baseline forecast')).toBeVisible()
  await expect(page.getByText('accuracy: 0.9182')).toBeVisible()

  await page.getByRole('button', { name: 'Back to sessions' }).click()
  await expect(page.getByRole('heading', { name: 'Independent chats' })).toBeVisible()
  await expect(page.getByText('Experiment session')).toBeVisible()
  await expect(page.getByText('Project-only session')).toHaveCount(0)
  await expect(page.locator('nav[aria-label="Session panel"]')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Back to sessions' })).toHaveCount(0)
})

test('uses the focused chat surface for a project session', async ({ page }) => {
  const projectId = 'project-eda'
  const sessionId = 'project-session'
  const project = { id: projectId, name: 'EDA Workspace', description: 'World Cup analysis', directory: '/work/eda', created_at: '2026-07-14T00:00:00Z', dataset_ids: [] }
  const sse = [
    { type: 'RUN_STARTED', threadId: sessionId, runId: 'run-project-session' },
    { type: 'MESSAGES_SNAPSHOT', messages: [] },
    { type: 'RUN_FINISHED', threadId: sessionId, runId: 'run-project-session' },
  ].map(event => `data: ${JSON.stringify(event)}\n\n`).join('')

  await page.route('**/api/plugins', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify([{ id: 'projects', name: 'Projects', label: 'Projects', icon: '', pages: [], config_schema: null }]) }))
  await page.route('**/api/projects/', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify([project]) }))
  await page.route(`**/api/projects/${projectId}`, route => route.fulfill({ contentType: 'application/json', body: JSON.stringify(project) }))
  await page.route(`**/api/chat/sessions?project_id=${projectId}`, route => route.fulfill({ contentType: 'application/json', body: JSON.stringify([{ id: sessionId, title: 'Project analysis', projectId, createdAt: '2026-07-14T00:00:00Z' }]) }))
  await page.route(`**/api/chat/sessions/${sessionId}`, route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({ id: sessionId, title: 'Project analysis', projectId, createdAt: '2026-07-14T00:00:00Z', messages: [], visualArtifacts: [] }),
  }))
  // Mirror a long-running backend that has not yet picked up the new
  // session-files endpoint: the chat route falls through to the SPA and
  // returns HTML. The Files rail must still show the existing project workspace.
  await page.route(`**/api/chat/sessions/${sessionId}/files`, route => route.fulfill({
    contentType: 'text/html',
    body: '<!doctype html><html><body>Dataclaw</body></html>',
  }))
  await page.route(`**/api/projects/${projectId}/files`, route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({ project: [{ name: 'shared-data.csv', path: '/work/eda/shared-data.csv', is_dir: false, size: 12 }] }),
  }))
  await page.route('**/api/agent', route => route.fulfill({ contentType: 'text/event-stream', body: sse }))
  await page.route('**/api/guardrails/config/session/**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ disabled: [] }) }))
  await page.route('**/api/guardrails', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ guardrails: [] }) }))
  await page.route('**/api/tools', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ tools: [] }) }))
  await page.route('**/api/skills', route => route.fulfill({ contentType: 'application/json', body: '[]' }))
  await page.route('**/api/subagents/', route => route.fulfill({ contentType: 'application/json', body: '[]' }))

  await page.goto(`/projects/${projectId}?tab=chat&session=${sessionId}`)

  await expect(page.getByRole('button', { name: 'Back to sessions' })).toBeVisible()
  await expect(page.getByText('PROJECT', { exact: true })).toBeVisible()
  await expect(page.getByRole('main').getByText('EDA Workspace', { exact: true })).toBeVisible()
  await expect(page.getByRole('tab', { name: 'Sessions' })).toHaveCount(0)
  await expect(page.getByRole('tab', { name: 'Data Sources' })).toHaveCount(0)

  await page.getByRole('button', { name: 'Files' }).click()
  await expect(page.getByText('shared-data.csv')).toBeVisible()
  await expect(page.getByLabel('Sort files')).toHaveValue('name')
  await expect(page.getByRole('button', { name: 'Folders first' })).toBeVisible()
  await expect(page.getByText('Files unavailable')).toHaveCount(0)

  await page.getByRole('button', { name: 'Back to sessions' }).click()
  await expect(page.getByRole('tab', { name: 'Sessions' })).toBeVisible()
})

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
  await page.getByRole('button', { name: 'Reports' }).click()

  await expect(page.getByText('Session living report · scratch')).toBeVisible()
  await expect(page.getByText('0 published')).toBeVisible()
  await expect(page.getByText('1 scratch')).toBeVisible()
  await expect(page.frameLocator('[data-testid="living-report-preview-frame"]').getByText('Living report loaded')).toBeVisible()
  await expect.poll(() => artifactRequests.length).toBe(1)

  const artifactUrl = new URL(artifactRequests[0])
  expect(artifactUrl.pathname).toBe('/api/artifacts/live-session-artifact/living')
  expect(artifactUrl.searchParams.get('session_id')).toBe(threadId)
})

test('renders a published report tool result in chat', async ({ page }) => {
  const documentRequests: string[] = []
  const runId = 'run-report-publish'
  const threadId = 'session-report-publish'
  const reportPath = 'reports/customer-retention.html'
  const publishedReport = {
    type: 'report_publish',
    published: true,
    publication_status: 'published',
    publish_required: false,
    html_path: reportPath,
    storyboard_path: 'reports/customer-retention.storyboard.json',
    quality: { status: 'pass', rubric_version: 3 },
    runtime_smoke: { status: 'passed' },
    size: 2048,
  }
  const blockedPublish = {
    type: 'report_publish',
    publication_status: 'blocked',
    publish_required: true,
    error: 'Report publish visual-review gate failed: an approved review for this rendered HTML is required before publication.',
  }
  const openingUpdate = {
    type: 'report',
    publication_status: 'draft',
    publish_required: true,
    html_path: reportPath,
    section_type: 'header',
    section: {
      section_id: 'section-report-opening',
      kind: 'header',
      title: 'Customer retention outlook',
      caption: 'The decision context and forecast horizon.',
    },
  }
  const snapshot = {
    type: 'MESSAGES_SNAPSHOT',
    messages: [
      {
        id: 'plan-approved-marker',
        role: 'user',
        content: 'Plan plan-forecast is approved.',
      },
      {
        id: 'assistant-report-publish',
        role: 'assistant',
        content: 'The report is ready.',
        toolCalls: [
          {
            id: 'call-data-query',
            type: 'function',
            function: { name: 'data_query_data', arguments: JSON.stringify({ dataset_id: 'fifa_wc26', sql: 'SELECT team, COUNT(*) AS matches FROM fixtures GROUP BY team' }) },
          },
          {
            id: 'call-cell-error',
            type: 'function',
            function: { name: 'execute_cell', arguments: JSON.stringify({ cell_index: 6 }) },
          },
          {
            id: 'call-cell-edit',
            type: 'function',
            function: { name: 'edit_cell_source', arguments: JSON.stringify({ cell_index: 6, old_string: 'market_value_eur', new_string: 'market_value_eur_m' }) },
          },
          {
            id: 'call-cell-retry',
            type: 'function',
            function: { name: 'execute_cell', arguments: JSON.stringify({ cell_index: 6 }) },
          },
          {
            id: 'call-memory-search',
            type: 'function',
            function: { name: 'search_customer_notes', arguments: JSON.stringify({ search: 'Golden Boot data quality' }) },
          },
          {
            id: 'call-report-opening-1',
            type: 'function',
            function: { name: 'report_add_section', arguments: JSON.stringify({ section_type: 'header', report_path: reportPath, data: { title: 'Customer retention outlook', subtitle: 'The decision context and forecast horizon.' } }) },
          },
          {
            id: 'call-report-opening-2',
            type: 'function',
            function: { name: 'report_add_section', arguments: JSON.stringify({ section_type: 'header', report_path: reportPath, data: { title: 'Customer retention outlook', subtitle: 'The decision context and forecast horizon.' } }) },
          },
          {
            id: 'call-report-publish',
            type: 'function',
            function: { name: 'report_publish', arguments: JSON.stringify({ report_path: reportPath, export_docx: false }) },
          },
          {
            id: 'call-report-publish-duplicate',
            type: 'function',
            function: { name: 'report_publish', arguments: JSON.stringify({ report_path: reportPath, export_docx: false }) },
          },
          {
            id: 'call-report-publish-blocked',
            type: 'function',
            function: { name: 'report_publish', arguments: JSON.stringify({ report_path: reportPath, export_docx: false }) },
          },
        ],
      },
      {
        id: 'tool-data-query',
        role: 'tool',
        toolCallId: 'call-data-query',
        content: JSON.stringify({ rows: [{ team: 'Spain', matches: 6 }] }),
      },
      {
        id: 'tool-cell-error',
        role: 'tool',
        toolCallId: 'call-cell-error',
        content: JSON.stringify({ error: "KeyError: 'market_value_eur'" }),
      },
      {
        id: 'tool-cell-edit',
        role: 'tool',
        toolCallId: 'call-cell-edit',
        content: JSON.stringify({ ok: true }),
      },
      {
        id: 'tool-cell-retry',
        role: 'tool',
        toolCallId: 'call-cell-retry',
        content: JSON.stringify({ outputs: [] }),
      },
      {
        id: 'tool-memory-search',
        role: 'tool',
        toolCallId: 'call-memory-search',
        content: JSON.stringify({ matches: [] }),
      },
      {
        id: 'tool-report-opening-1',
        role: 'tool',
        toolCallId: 'call-report-opening-1',
        content: JSON.stringify(openingUpdate),
      },
      {
        id: 'tool-report-opening-2',
        role: 'tool',
        toolCallId: 'call-report-opening-2',
        content: JSON.stringify(openingUpdate),
      },
      {
        id: 'tool-report-publish',
        role: 'tool',
        toolCallId: 'call-report-publish',
        content: JSON.stringify(publishedReport),
      },
      {
        id: 'tool-report-publish-duplicate',
        role: 'tool',
        toolCallId: 'call-report-publish-duplicate',
        content: JSON.stringify(publishedReport),
      },
      {
        id: 'tool-report-publish-blocked',
        role: 'tool',
        toolCallId: 'call-report-publish-blocked',
        content: JSON.stringify(blockedPublish),
      },
    ],
  }
  const sse = [
    { type: 'RUN_STARTED', threadId, runId },
    snapshot,
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
      body: JSON.stringify([{ id: threadId, title: 'Published report', createdAt: '2026-07-13T00:00:00Z' }]),
    })
  })
  await page.route('**/api/chat/sessions', async route => {
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify([{ id: threadId, title: 'Published report', createdAt: '2026-07-13T00:00:00Z' }]),
    })
  })
  await page.route(`**/api/chat/sessions/${threadId}`, async route => {
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        id: threadId,
        title: 'Published report',
        createdAt: '2026-07-13T00:00:00Z',
        messages: [],
        visualArtifacts: [],
      }),
    })
  })
  await page.route('**/api/agent', async route => {
    await route.fulfill({ contentType: 'text/event-stream', body: sse })
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
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ artifacts: [] }) })
  })
  await page.route('**/api/workspace/preview/document?**', async route => {
    documentRequests.push(route.request().url())
    await route.fulfill({
      contentType: 'text/html',
      body: '<!doctype html><html><body><main>Published report preview</main></body></html>',
    })
  })

  await page.goto(`/chat?session=${threadId}`)

  await expect(page.locator('.chat-system-marker')).toContainText('Plan approved')
  await expect(page.locator('.chat-evidence').getByText('Report published to workspace', { exact: true })).toHaveCount(1)
  await expect(page.getByText('Report publication blocked: reports/customer-retention.html', { exact: false })).toBeVisible()
  await expect(page.getByText('Report publish visual-review gate failed', { exact: false })).toBeVisible()
  await expect(page.getByText('The report is ready.')).toBeVisible()
  await expect(page.getByText('Queried fifa_wc26 — SELECT team, COUNT(*) AS matches FROM fixtures GROUP BY team')).toBeVisible()
  await expect(page.getByText("Ran cell [6] — KeyError: 'market_value_eur'")).toBeVisible()
  await expect(page.getByText('Edited cell [6] — replaced market_value_eur')).toBeVisible()
  await expect(page.getByText('Searched customer notes — Golden Boot data quality')).toBeVisible()
  const openingStep = page.getByText('Set the report opening: Customer retention outlook — The decision context and forecast horizon. — consolidated 2 identical updates')
  await expect(openingStep).toBeVisible()
  await openingStep.click()
  await expect(page.getByText('What changed: Set the report opening: Customer retention outlook — The decision context and forecast horizon.')).toBeVisible()
  await expect(page.getByText('Report updated:')).toHaveCount(0)
  await expect(page.getByText('1 error fixed')).toBeVisible()
  await expect(page.getByText(/1 error$/)).toBeVisible()
  await expect(page.getByText('Ran a tool')).toHaveCount(0)
  await expect(page.locator('.chat-evidence__gutter')).toHaveCount(0)
  const [turnBox, evidenceBox, narrativeBox, composerBox] = await Promise.all([
    page.locator('.chat-turn__header').boundingBox(),
    page.locator('.chat-evidence__body').boundingBox(),
    page.getByText('The report is ready.').boundingBox(),
    page.getByPlaceholder('Send a message...').boundingBox(),
  ])
  expect(turnBox?.x).toBe(evidenceBox?.x)
  expect(evidenceBox?.x).toBe(narrativeBox?.x)
  expect(narrativeBox?.x).toBe(composerBox?.x)
  await expect(page.getByText('Report: customer-retention.html')).toBeVisible()
  await expect(page.getByText('Published to workspace', { exact: true })).toBeVisible()
  await expect(page.getByText('(2.0KB)')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Show full report' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Print' })).toBeVisible()
  await expect(page.getByRole('button', { name: /Open$/ })).toBeVisible()
  await expect(page.locator('[data-testid="inline-report-preview-frame"]')).toHaveCount(0)
  await page.getByRole('button', { name: 'Show full report' }).click()
  await expect(page.frameLocator('[data-testid="inline-report-preview-frame"]').getByText('Published report preview')).toBeVisible()
  await expect.poll(() => documentRequests.length).toBe(1)

  const documentUrl = new URL(documentRequests[0])
  expect(documentUrl.pathname).toBe('/api/workspace/preview/document')
  expect(documentUrl.searchParams.get('path')).toBe(reportPath)
  expect(documentUrl.searchParams.get('v')).toBe('2048')
})

test('surfaces report trust signals and visual review evidence in chat', async ({ page }) => {
  const runId = 'run-report-trust'
  const threadId = 'session-report-trust'
  const reportPath = 'reports/freeform-craft.html'
  const pngBase64 = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='
  const publishedReport = {
    type: 'report_publish',
    published: true,
    publication_status: 'published',
    publish_required: false,
    html_path: reportPath,
    storyboard_path: 'reports/freeform-craft.storyboard.json',
    receipt_path: 'reports/freeform-craft.publish.json',
    quality: {
      status: 'warn',
      rubric_version: 8,
      warnings: [
        { code: 'missing_table_caption', severity: 'warn', message: 'Table section is missing a caption.' },
        { code: 'unsourced_claim', severity: 'warn', message: 'A finding has no evidence reference.' },
      ],
    },
    runtime_smoke: { status: 'skipped', reason: 'Browser smoke exceeded the 20-second publish budget.' },
    visual_review: { required: true, status: 'approved', reviewer: 'Nandini' },
    fact_verification: { status: 'pass', fact_count: 2, bound_fact_count: 2, binding_count: 2 },
    docx_export: { requested: true, status: 'failed', error: 'RuntimeError: converter unavailable' },
    size: 4096,
  }
  const lowConfidenceBuild = {
    type: 'report_build',
    publication_status: 'designed',
    publish_required: true,
    html_path: 'reports/legacy-page.html',
    storyboard_path: 'reports/legacy-page.storyboard.json',
    normalization: { mode: 'preserved_low_confidence', confidence: 0.37 },
    quality: { status: 'warn', rubric_version: 8, warnings: [] },
    size: 1024,
  }
  const visualReview = {
    type: 'report_visual_review',
    review_path: 'reports/freeform-craft.visual-review.json',
    decision: 'approved',
    reviewer: 'Nandini',
    capture_reused: true,
    approved: true,
    runtime_smoke: {
      status: 'passed',
      checks: [],
      semantic_visual: { visual_semantic_schema: 1, status: 'pass', findings: [] },
      screenshots: [
        { kind: 'full_page', viewport: 'desktop', path: 'reports/freeform-craft.visual-review/desktop-full-page.png', sha256: 'a'.repeat(64) },
        { kind: 'key_section', viewport: 'desktop', section: 'insight_grid', path: 'reports/freeform-craft.visual-review/desktop-section-01.png', sha256: 'b'.repeat(64) },
      ],
    },
  }
  const snapshot = {
    type: 'MESSAGES_SNAPSHOT',
    messages: [
      {
        id: 'assistant-report-trust',
        role: 'assistant',
        content: 'Report reviewed and published.',
        toolCalls: [
          { id: 'call-build-low', type: 'function', function: { name: 'build_report', arguments: JSON.stringify({ html_path: 'legacy-page.html', output_path: 'reports/legacy-page.html' }) } },
          { id: 'call-review-visuals', type: 'function', function: { name: 'report_review_visuals', arguments: JSON.stringify({ report_path: reportPath, reviewer: 'Nandini', decision: 'approved', notes: 'Reader-ready.' }) } },
          { id: 'call-publish-trust', type: 'function', function: { name: 'report_publish', arguments: JSON.stringify({ report_path: reportPath }) } },
        ],
      },
      { id: 'tool-build-low', role: 'tool', toolCallId: 'call-build-low', content: JSON.stringify(lowConfidenceBuild) },
      { id: 'tool-review-visuals', role: 'tool', toolCallId: 'call-review-visuals', content: JSON.stringify(visualReview) },
      { id: 'tool-publish-trust', role: 'tool', toolCallId: 'call-publish-trust', content: JSON.stringify(publishedReport) },
    ],
  }
  const sse = [
    { type: 'RUN_STARTED', threadId, runId },
    snapshot,
    { type: 'RUN_FINISHED', threadId, runId },
  ].map(event => `data: ${JSON.stringify(event)}\n\n`).join('')

  const screenshotRequests: string[] = []
  await page.route('**/api/plugins', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify([]) }))
  await page.route('**/api/chat/sessions?*', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify([{ id: threadId, title: 'Trust surfaces', createdAt: '2026-07-15T00:00:00Z' }]) }))
  await page.route('**/api/chat/sessions', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify([{ id: threadId, title: 'Trust surfaces', createdAt: '2026-07-15T00:00:00Z' }]) }))
  await page.route(`**/api/chat/sessions/${threadId}`, route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({ id: threadId, title: 'Trust surfaces', createdAt: '2026-07-15T00:00:00Z', messages: [], visualArtifacts: [] }),
  }))
  await page.route('**/api/agent', route => route.fulfill({ contentType: 'text/event-stream', body: sse }))
  await page.route('**/api/guardrails/config/session/**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ disabled: [] }) }))
  await page.route('**/api/guardrails', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ guardrails: [] }) }))
  await page.route('**/api/tools', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ tools: [] }) }))
  await page.route('**/api/skills', route => route.fulfill({ contentType: 'application/json', body: '[]' }))
  await page.route('**/api/subagents/', route => route.fulfill({ contentType: 'application/json', body: '[]' }))
  await page.route('**/api/artifacts?**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ artifacts: [] }) }))
  await page.route('**/api/workspace/files?**', route => {
    screenshotRequests.push(route.request().url())
    route.fulfill({ contentType: 'image/png', body: Buffer.from(pngBase64, 'base64') })
  })

  await page.goto(`/chat?session=${threadId}`)
  await expect(page.getByText('Report reviewed and published.')).toBeVisible()

  // Publish card: rubric warnings expand, skipped browser evidence is visible
  // (not a silent pass), the visual approval and fact verification surface.
  const qualityTag = page.locator('[data-testid="report-trust-quality"]').last()
  await expect(qualityTag).toHaveText('Quality: 2 warnings (v8)')
  await qualityTag.click()
  await expect(page.locator('[data-testid="report-trust-quality-detail"]')).toContainText('missing_table_caption')
  await expect(page.locator('[data-testid="report-trust-smoke"]')).toHaveText('Browser checks skipped')
  await expect(page.locator('[data-testid="report-trust-visual"]')).toHaveText('Visual review approved · Nandini')
  await expect(page.locator('[data-testid="report-trust-facts"]')).toHaveText('Facts verified · 2 bound')
  await expect(page.getByText('Word export failed')).toBeVisible()
  await expect(page.getByText('RuntimeError: converter unavailable')).toBeVisible()
  await expect(page.getByRole('link', { name: 'Publish receipt' })).toBeVisible()

  // The build is a narrated step; its provenance rides on the step label so
  // a low-confidence preservation is visibly different from a clean rebuild.
  await page.getByRole('button', { name: /Worked 3 steps/ }).click()
  await expect(page.getByText('Built report reports/legacy-page.html · preserved (low confidence)')).toBeVisible()

  // The visual review carries screenshots, so it renders as an evidence card
  // bound to the inspected artifacts.
  const reviewCard = page.locator('[data-testid="visual-review-card"]')
  await expect(reviewCard).toContainText('Approved · Nandini')
  await expect(reviewCard).toContainText('Bound to inspected capture')
  await expect(reviewCard).toContainText('Semantic review passed')
  await expect(reviewCard.locator('[data-testid="visual-review-screenshot"]')).toHaveCount(2)
  await expect(reviewCard.getByText('Key section · insight_grid')).toBeVisible()
  await expect.poll(() => screenshotRequests.length).toBeGreaterThanOrEqual(2)
})
