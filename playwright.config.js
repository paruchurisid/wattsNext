const { defineConfig, devices } = require('@playwright/test');
module.exports = defineConfig({
  testDir: './tests/browser',
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: [['list'], ['html', { open: 'never' }], ['junit', { outputFile: 'reports/browser.xml' }]],
  use: { baseURL: 'http://127.0.0.1:8002', trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  projects: [
    { name: 'desktop-chromium', use: { ...devices['Desktop Chrome'] } },
    { name: 'mobile-chromium', use: { ...devices['Pixel 7'] } },
  ],
  webServer: {
    command: 'python -m uvicorn server:app --host 127.0.0.1 --port 8002',
    url: 'http://127.0.0.1:8002/', reuseExistingServer: false,
    env: { WATTSNEXT_USE_NEON: 'false', DATABASE_URL: '', WATTSNEXT_PROVIDER: 'local' },
    timeout: 30000,
  },
});
