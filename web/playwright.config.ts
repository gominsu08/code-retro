import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e', timeout: 180_000, retries: 0, workers: 1,
  use: { baseURL: 'http://127.0.0.1:8000', browserName: 'chromium', channel: 'msedge', headless: true, viewport: { width: 1440, height: 960 }, screenshot: 'only-on-failure', trace: 'retain-on-failure' },
  reporter: [['list']],
});
