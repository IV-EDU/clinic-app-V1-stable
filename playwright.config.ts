import { defineConfig } from '@playwright/test';
import os from 'os';
import path from 'path';

const port = Number(process.env.PW_PORT || '8181');
const baseURL = process.env.PW_BASE_URL || `http://127.0.0.1:${port}`;
const dbPath =
  process.env.PW_E2E_DB_PATH ||
  path.join(os.tmpdir(), 'clinic-app-local-playwright', 'app-e2e.db');
const pythonCommand = process.env.PW_PYTHON || '.venv\\Scripts\\python.exe';

export default defineConfig({
  testDir: './e2e/tests',
  timeout: 30_000,
  expect: {
    timeout: 10_000,
  },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [
    ['list'],
    ['html', { outputFolder: 'playwright-report', open: 'never' }],
  ],
  outputDir: 'test-results',
  use: {
    baseURL,
    browserName: 'chromium',
    headless: true,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  webServer: {
    command: `"${pythonCommand}" devtools/playwright_server.py`,
    url: `${baseURL}/auth/login`,
    reuseExistingServer: false,
    timeout: 120_000,
    env: {
      ...process.env,
      PW_PORT: String(port),
      PW_BASE_URL: baseURL,
      PW_E2E_DB_PATH: dbPath,
    },
  },
});
