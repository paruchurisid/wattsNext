const { test, expect } = require('@playwright/test');

test('new chat shows all welcome content and controls without scrolling on laptop screens', async ({ page, request }) => {
  await request.post('/api/settings', { data: { offline_mode: true } });
  await page.goto('/');
  await expect(page.locator('#message-input')).toBeEnabled();
  for (const viewport of [
    { width: 1920, height: 1080 }, { width: 1440, height: 900 },
    { width: 1366, height: 768 }, { width: 1366, height: 650 },
    { width: 1280, height: 600 }, { width: 1280, height: 560 },
  ]) {
    await page.setViewportSize(viewport);
    await page.locator('#new-conversation-btn').click();
    await expect(page.locator('#message-input')).toBeEnabled();
    for (const selector of ['.hero-symbol', '.empty-state h1', '.tagline', '.welcome-detail', '#open-wiki-btn',
      '.starter-prompts button', '.replay-label', '.composer', '#whatif-chips button', '#engine-status-btn', '#household-select']) {
      for (const control of await page.locator(selector).all()) {
        await expect(control).toBeVisible();
        const box = await control.boundingBox();
        expect(box.y, `${selector} at ${viewport.width}x${viewport.height}`).toBeGreaterThanOrEqual(0);
        expect(box.y + box.height, `${selector} at ${viewport.width}x${viewport.height}`).toBeLessThanOrEqual(viewport.height + 1);
      }
    }
    expect(await page.locator('.conversation').evaluate(node => node.scrollHeight <= node.clientHeight + 1)).toBeTruthy();
    expect(await page.evaluate(() => document.documentElement.scrollHeight <= innerHeight + 1)).toBeTruthy();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  }
});
