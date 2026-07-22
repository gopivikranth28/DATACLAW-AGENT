import { expect, test } from '@playwright/test'

test('lists authenticated backend models in a selector', async ({ page }) => {
  const modelRequests: Record<string, unknown>[] = []

  await page.route('**/api/plugins', route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify([]),
  }))
  await page.route('**/api/providers', route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify([]),
  }))
  await page.route('**/api/config', route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({
      llm: {
        backend: 'openai',
        openai: { api_key: 'sk-test...1234', model: 'gpt-4o', base_url: '' },
      },
      app: {},
      plugins: {},
    }),
  }))
  await page.route('**/api/models', async route => {
    modelRequests.push(route.request().postDataJSON())
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        backend: 'openai',
        authenticated: true,
        models: [
          { id: 'gpt-4o', label: 'gpt-4o' },
          { id: 'gpt-5', label: 'gpt-5' },
        ],
      }),
    })
  })

  await page.goto('/config')

  const agentPanel = page.locator('.ant-tabs-tabpane-active')
  const selects = agentPanel.locator('.ant-select')
  await expect(selects).toHaveCount(2)
  await expect(selects.nth(1)).toContainText('gpt-4o')

  await selects.nth(1).click()
  await page.keyboard.press('ArrowDown')
  await page.keyboard.press('Enter')
  await expect(selects.nth(1)).toContainText('gpt-5')

  expect(modelRequests).toHaveLength(1)
  expect(modelRequests[0]).toMatchObject({ backend: 'openai', base_url: '' })
  expect(modelRequests[0]).not.toHaveProperty('api_key')
  await expect(agentPanel.locator('input[placeholder="gpt-4o"]')).toHaveCount(0)
})

test('uses three tabs and keeps related agent integrations together', async ({ page }) => {
  await page.route('**/api/plugins', route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify([
      {
        id: 'codex', name: 'dataclaw-codex', label: 'Codex',
        config_schema: {
          title: 'OpenAI Codex',
          fields: [{ name: 'enabled', field_type: 'bool', label: 'Enabled', description: 'Enable Codex subagent provider', default: false }],
        },
      },
      {
        id: 'browser', name: 'dataclaw-browser', label: 'Browser',
        config_schema: {
          title: 'Browser',
          fields: [{ name: 'enabled', field_type: 'bool', label: 'Enabled', default: true }],
        },
      },
    ]),
  }))
  await page.route('**/api/providers', route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify([
      {
        slot: 'compaction', name: 'LLMSummarizingCompactor', config_path: 'compaction', config_schema: [],
        backend: { config_key: 'compaction.backend', current: 'llm_summarizer', options: [], schemas: {}, config_paths: {} },
      },
      {
        slot: 'memory', name: 'NoopMemoryProvider', config_path: null, config_schema: [],
        backend: { config_key: 'memory.backend', current: 'noop', options: [], schemas: { noop: [] }, config_paths: { noop: null } },
      },
    ]),
  }))
  await page.route('**/api/config', route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({
      llm: { backend: 'openclaw', openclaw: {} },
      app: { max_turns: 30 },
      compaction: { backend: 'llm_summarizer', max_messages: 30, keep_recent: 8, max_tokens: 100000 },
      memory: { backend: 'noop' },
      plugins: { openclaw: { url: 'http://127.0.0.1:18789' }, codex: { enabled: false }, browser: { enabled: true } },
    }),
  }))
  await page.route('**/api/openclaw/check', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ installed: false }) }))
  await page.route('**/api/openclaw/plugins/dataclaw/sync-status', route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({ has_snapshot: false, in_sync: true, live_count: 0, added: [], removed: [] }),
  }))

  await page.goto('/config')

  await expect(page.getByRole('tab')).toHaveCount(3)
  await expect(page.getByRole('tab', { name: 'Agent' })).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible()
  await expect(page.getByText('OpenClaw installation', { exact: true })).toBeVisible()
  await expect(page.getByText('OpenClaw tool bridge', { exact: true })).toBeVisible()
  await expect(page.getByText('Codex delegation', { exact: true })).toBeVisible()
  await expect(page.getByText('Allow Codex delegation')).toBeVisible()

  await page.getByRole('tab', { name: 'Behavior' }).click()
  const behaviorPanel = page.locator('.ant-tabs-tabpane-active')
  await expect(behaviorPanel.getByText('Not currently applied')).toHaveCount(2)
  await expect(page.getByLabel('Start after')).toBeDisabled()
  await expect(page.getByLabel('Start after')).toHaveValue('30')

  await page.getByRole('tab', { name: 'Extensions' }).click()
  const extensionsPanel = page.locator('.ant-tabs-tabpane-active')
  await expect(extensionsPanel.getByText('Browser', { exact: true })).toBeVisible()
  await expect(extensionsPanel.getByRole('switch')).toBeChecked()
  await expect(extensionsPanel.getByText('Codex delegation', { exact: true })).toHaveCount(0)
  await expect(extensionsPanel.getByRole('button', { name: 'Manage' })).toHaveCount(0)
  await expect(page.locator('.ant-drawer')).toHaveCount(0)

  await page.setViewportSize({ width: 320, height: 844 })
  await expect.poll(async () => page.getByRole('button', { name: 'Save changes' }).evaluate(element => Math.ceil(element.getBoundingClientRect().right))).toBeLessThanOrEqual(320)
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320)
})

test('keeps changes as a draft and confirms navigation away', async ({ page }) => {
  const patches: Record<string, unknown>[] = []
  const baseConfig = {
    llm: { backend: 'openai', openai: { api_key: 'sk-test...1234', model: 'gpt-4o', base_url: '' } },
    app: { max_turns: 30, debug: false },
    compaction: { backend: 'noop', max_messages: 30, keep_recent: 8, max_tokens: 100000 },
    memory: { backend: 'noop' },
    plugins: {},
  }

  await page.route('**/api/plugins', route => route.fulfill({ contentType: 'application/json', body: '[]' }))
  await page.route('**/api/providers', route => route.fulfill({ contentType: 'application/json', body: '[]' }))
  await page.route('**/api/config', async route => {
    if (route.request().method() === 'PATCH') patches.push(route.request().postDataJSON())
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(baseConfig) })
  })
  await page.route('**/api/models', route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({ backend: 'openai', authenticated: true, models: [{ id: 'gpt-4o', label: 'gpt-4o' }] }),
  }))

  await page.goto('/config')
  await page.getByRole('tab', { name: 'Behavior' }).click()
  const actionRounds = page.getByRole('spinbutton', { name: 'Maximum action rounds' })
  await actionRounds.fill('40')
  await expect(page.getByText('1 unsaved change')).toBeVisible()
  expect(patches).toHaveLength(0)

  await page.getByRole('link', { name: 'Skills' }).click()
  await expect(page.getByRole('dialog', { name: 'Leave without saving?' })).toBeVisible()
  await page.getByRole('button', { name: 'Stay' }).click()
  await expect(page).toHaveURL(/\/config$/)

  await page.getByRole('link', { name: 'Skills' }).click()
  await page.getByRole('button', { name: 'Save and leave' }).click()
  await expect(page).toHaveURL(/\/skills$/)
  expect(patches).toHaveLength(1)
  expect(patches[0]).toMatchObject({ app: { max_turns: 40 } })
})
