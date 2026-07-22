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

  const backendCard = page.locator('.ant-card').filter({ hasText: 'Agent Backend' })
  const selects = backendCard.locator('.ant-select')
  await expect(selects).toHaveCount(2)
  await expect(selects.nth(1)).toContainText('gpt-4o')

  await selects.nth(1).click()
  await page.keyboard.press('ArrowDown')
  await page.keyboard.press('Enter')
  await expect(selects.nth(1)).toContainText('gpt-5')

  expect(modelRequests).toHaveLength(1)
  expect(modelRequests[0]).toMatchObject({ backend: 'openai', base_url: '' })
  expect(modelRequests[0]).not.toHaveProperty('api_key')
  await expect(backendCard.locator('input[placeholder="gpt-4o"]')).toHaveCount(0)
})
