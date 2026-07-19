import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: 'http://127.0.0.1:5187',
    trace: 'on-first-retry',
  },
  webServer: [
    {
      command: '.venv/bin/python -m uvicorn dataclaw.api.app:create_app --factory --host 127.0.0.1 --port 8001',
      cwd: '..',
      env: { DATACLAW_HOME: '/tmp/dataclaw-playwright-e2e' },
      url: 'http://127.0.0.1:8001/docs',
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: 'npm run dev -- --host 127.0.0.1 --port 5187',
      env: { DATACLAW_API_URL: 'http://127.0.0.1:8001' },
      url: 'http://127.0.0.1:5187',
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
})
