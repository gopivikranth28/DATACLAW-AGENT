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
      agent: { runtime: 'dataclaw' },
      llm: {
        backend: 'openai',
        backends: { openai: { api_key: 'sk-test...1234', model: 'gpt-4o', base_url: '' } },
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
  await expect(selects).toHaveCount(3)
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

test('shows reasoning effort only for models that support it', async ({ page }) => {
  await page.route('**/api/plugins', route => route.fulfill({ contentType: 'application/json', body: '[]' }))
  await page.route('**/api/providers', route => route.fulfill({ contentType: 'application/json', body: '[]' }))
  await page.route('**/api/config', route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({
      agent: { runtime: 'dataclaw' },
      llm: { backend: 'anthropic', backends: { anthropic: { api_key: 'sk-ant...1234', model: 'claude-opus-5-5' } } },
      app: {},
      plugins: {},
    }),
  }))
  await page.route('**/api/models', route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({
      backend: 'anthropic',
      authenticated: true,
      models: [
        { id: 'claude-opus-5-5', label: 'Claude Opus 5.5', supports_reasoning: true, reasoning_efforts: ['low', 'medium', 'high', 'xhigh', 'max'] },
        { id: 'claude-legacy', label: 'Claude Legacy', supports_reasoning: false, reasoning_efforts: [] },
      ],
    }),
  }))

  await page.goto('/config')

  const utilitySection = page.getByRole('heading', { name: 'Configure the DataClaw utility model' }).locator('xpath=ancestor::section')
  await expect(utilitySection.getByText('Reasoning effort', { exact: true })).toBeVisible()
  const selects = utilitySection.locator('.ant-select')
  await selects.nth(2).click()
  await page.locator('.ant-select-dropdown:visible').getByText('xhigh', { exact: true }).click()
  await expect(selects.nth(2)).toContainText('xhigh')

  await selects.nth(1).click()
  await page.locator('.ant-select-dropdown:visible').getByText('Claude Legacy', { exact: true }).click()
  await expect(utilitySection.getByText('Reasoning effort', { exact: true })).toHaveCount(0)
})

test('renders OpenAI-compatible presets from the backend registry', async ({ page }) => {
  const modelRequests: Record<string, unknown>[] = []
  await page.route('**/api/plugins', route => route.fulfill({ contentType: 'application/json', body: '[]' }))
  await page.route('**/api/providers', route => route.fulfill({ contentType: 'application/json', body: '[]' }))
  await page.route('**/api/config', route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({
      agent: { runtime: 'dataclaw' },
      llm: { backend: 'openai_compatible', backends: { openai_compatible: { preset: 'vllm', model: '' } } },
      app: {},
      plugins: {},
    }),
  }))
  await page.route('**/api/models', async route => {
    modelRequests.push(route.request().postDataJSON())
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({ backend: 'openai_compatible', authenticated: true, models: [{ id: 'qwen3', label: 'qwen3' }] }),
    })
  })

  await page.goto('/config')

  const utilitySection = page.getByRole('heading', { name: 'Configure the DataClaw utility model' }).locator('xpath=ancestor::section')
  await expect(utilitySection.locator('.ant-select').first()).toContainText('OpenAI-compatible endpoint')
  await expect(utilitySection.getByText('Preset', { exact: true })).toBeVisible()
  await expect(utilitySection.locator('input[placeholder="http://localhost:8001/v1"]')).toBeVisible()
  await expect(utilitySection.getByText(/--port 8001/)).toBeVisible()
  await expect(utilitySection.getByText('API key (optional)', { exact: true })).toBeVisible()
  await expect.poll(() => modelRequests.length).toBeGreaterThan(0)
  expect(modelRequests[0]).toMatchObject({ backend: 'openai_compatible', preset: 'vllm', base_url: '' })
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
      agent: { runtime: 'openclaw' },
      llm: { backend: 'codex', backends: { codex: { auth_mode: 'default', model: 'gpt-5.5' } } },
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
  await page.route('**/api/models', route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({ backend: 'codex', authenticated: false, models: [], message: 'Sign in required.' }),
  }))

  await page.goto('/config')

  await expect(page.getByRole('tab')).toHaveCount(3)
  await expect(page.getByRole('tab', { name: 'Agent' })).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible()
  await expect(page.getByText('OpenClaw installation and authentication', { exact: true })).toBeVisible()
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

test('shows CLI and authentication controls only for the selected external runtime', async ({ page }) => {
  test.setTimeout(60_000)
  let hermesRestarts = 0
  let hermesSetups = 0
  let configSaves = 0
  const utilityChecks: Record<string, unknown>[] = []
  await page.route('**/api/plugins', route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify([
      {
        id: 'hermes', name: 'dataclaw-hermes', label: 'Hermes Agent',
        config_schema: {
          title: 'Hermes Runtime',
          fields: [
            { name: 'url', field_type: 'string', label: 'Hermes API URL', default: 'http://127.0.0.1:8642' },
            { name: 'api_key', field_type: 'string', label: 'Hermes API key', default: '' },
            { name: 'dataclaw_api_url', field_type: 'string', label: 'Dataclaw callback URL', default: 'http://127.0.0.1:8000' },
            { name: 'profile', field_type: 'string', label: 'Hermes profile', default: 'dataclaw' },
            { name: 'model', field_type: 'string', label: 'Hermes model override', default: '' },
            { name: 'cli_path', field_type: 'string', label: 'Hermes CLI', default: 'hermes' },
            { name: 'request_timeout_seconds', field_type: 'int', label: 'Request timeout (seconds)', default: 60 },
            { name: 'reconnect_timeout_seconds', field_type: 'int', label: 'Reconciliation timeout (seconds)', default: 30 },
            { name: 'tool_callback_timeout_seconds', field_type: 'int', label: 'Tool callback timeout (seconds)', default: 330 },
          ],
        },
      },
    ]),
  }))
  await page.route('**/api/providers', route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify([]),
  }))
  let currentConfig = {
      agent: { runtime: 'openclaw' },
      llm: {
        backend: 'codex',
        backends: {
          openai: { model: '' },
          codex: { auth_mode: 'api_key', api_key: '', model: 'gpt-5.5' },
        },
      },
      app: {},
      plugins: {
        openclaw: { url: 'http://127.0.0.1:18789', openclaw_cmd: 'openclaw' },
        hermes: {
          url: 'http://127.0.0.1:8642',
          api_key: '***',
          dataclaw_api_url: 'http://127.0.0.1:8000',
          profile: 'dataclaw',
          cli_path: '/opt/hermes/bin/hermes',
        },
      },
    }
  await page.route('**/api/config', async route => {
    if (route.request().method() === 'PATCH') {
      configSaves += 1
      currentConfig = route.request().postDataJSON()
      return route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({ status: 'updated' }),
      })
    }
    return route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify(currentConfig),
    })
  })
  await page.route('**/api/openclaw/check', route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({ installed: true, version: 'OpenClaw 1.2.3' }),
  }))
  await page.route('**/api/openclaw/plugins/dataclaw/sync-status', route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({ has_snapshot: false, in_sync: true, live_count: 0, added: [], removed: [] }),
  }))
  await page.route('**/api/hermes/health', route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({
      status: 'unhealthy',
      configured_runtime: 'hermes',
      last_selection_error: "Codex auth_mode is 'api_key' but no API key provided",
    }),
  }))
  await page.route('**/api/hermes/install/status', route => route.fulfill({
    contentType: 'application/json',
    body: JSON.stringify({
      installed: true,
      version: '0.19.0',
      compatible_version: '0.19.0',
      version_compatible: true,
      extension_installed: true,
      restricted_profile: true,
      model: 'claude-sonnet-4-5',
      provider: 'anthropic',
      model_selected: true,
      model_configured: true,
      provider_auth_configured: false,
      provider_auth_detail: 'anthropic: logged out',
    }),
  }))
  await page.route('**/api/hermes/gateway/restart', route => {
    hermesRestarts += 1
    return route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({ status: 'restarted', profile: 'dataclaw' }),
    })
  })
  await page.route('**/api/hermes/install/extension', route => {
    hermesSetups += 1
    return route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({ status: 'installed', profile: 'dataclaw' }),
    })
  })
  await page.route('**/api/models', async route => {
    const payload = route.request().postDataJSON()
    utilityChecks.push(payload)
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({ backend: payload.backend, authenticated: true, models: [] }),
    })
  })

  await page.goto('/config')

  await expect(page.getByTestId('openclaw-runtime-setup')).toBeVisible()
  await expect(page.getByTestId('hermes-runtime-setup')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Configure model / sign in' })).toBeVisible()

  const runtimeSection = page.getByRole('heading', { name: 'Choose the agent runtime' }).locator('xpath=ancestor::section')
  const runtimeSelect = runtimeSection.locator('.ant-select').first()
  await runtimeSelect.click()
  await page.locator('.ant-select-item-option-content', { hasText: 'Hermes Agent' }).click()

  await expect(page.getByTestId('hermes-runtime-setup')).toBeVisible()
  await expect(page.getByTestId('openclaw-runtime-setup')).toHaveCount(0)
  await expect(page.getByRole('heading', { name: 'Connect DataClaw and Hermes' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Install the CLI and tool bridge' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Choose the Hermes primary model' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Configure the DataClaw utility model' })).toHaveCount(1)
  await expect(page.getByText('anthropic · claude-sonnet-4-5 · no credentials detected', { exact: true })).toBeVisible()
  await expect(page.getByText('No credentials detected for anthropic', { exact: true })).toBeVisible()
  await expect(page.getByTestId('hermes-runtime-setup').locator('input[type="password"]')).toHaveCount(1)
  await expect(page.getByText('Hermes is configured; the DataClaw utility model needs authentication', { exact: true })).toBeVisible()
  await expect(page.getByText('DataClaw utility Codex is set to API-key sign-in', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Configure model / sign in' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Save & set up bridge' })).toBeEnabled()
  await expect(page.getByText('Advanced Hermes settings', { exact: true })).toBeVisible()
  await expect(page.getByText('Hermes provider override', { exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: 'Use Codex OAuth' }).last().click()
  await expect(page.getByText('DataClaw utility Codex is set to API-key sign-in', { exact: true })).toHaveCount(0)
  await expect(page.getByText('Codex account', { exact: true })).toBeVisible()

  const utilitySection = page.getByRole('heading', { name: 'Configure the DataClaw utility model' }).locator('xpath=ancestor::section')
  const utilityBackendSelect = utilitySection.locator('.ant-select').first()
  for (const provider of [
    { value: 'anthropic', label: 'Anthropic Claude' },
    { value: 'openai', label: 'OpenAI API' },
    { value: 'gemini', label: 'Google Gemini' },
  ]) {
    await utilityBackendSelect.click()
    await page.locator('.ant-select-dropdown:visible').getByText(provider.label, { exact: true }).click()
    await expect(page.getByText(`${provider.label} API key required for DataClaw utility calls`, { exact: true })).toBeVisible()
    await utilitySection.getByRole('button', { name: 'Check utility access' }).click()
    await expect(page.getByText(`${provider.value} credentials are available to DataClaw.`, { exact: true })).toBeVisible()
    await expect(page.getByText(`${provider.label} API key required for DataClaw utility calls`, { exact: true })).toHaveCount(0)
  }
  expect(new Set(utilityChecks.map(request => request.backend))).toEqual(new Set(['anthropic', 'openai', 'gemini', 'codex']))

  await page.getByRole('button', { name: 'Restart gateway' }).click()
  await expect.poll(() => hermesRestarts).toBe(1)
  await page.getByRole('button', { name: 'Save & set up bridge' }).click()
  await expect.poll(() => configSaves).toBe(1)
  await expect.poll(() => hermesSetups).toBe(1)
  await expect(page.getByRole('button', { name: 'Update bridge' })).toBeVisible()

  await page.setViewportSize({ width: 320, height: 844 })
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320)

  await runtimeSelect.click()
  await page.locator('.ant-select-item-option-content', { hasText: 'DataClaw' }).click()
  await expect(page.getByTestId('hermes-runtime-setup')).toHaveCount(0)
  await expect(page.getByTestId('openclaw-runtime-setup')).toHaveCount(0)
})

test('keeps changes as a draft and confirms navigation away', async ({ page }) => {
  const patches: Record<string, unknown>[] = []
  const baseConfig = {
    agent: { runtime: 'dataclaw' },
    llm: { backend: 'openai', backends: { openai: { api_key: 'sk-test...1234', model: 'gpt-4o', base_url: '' } } },
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
