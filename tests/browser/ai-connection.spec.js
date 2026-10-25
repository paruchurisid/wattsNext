const { test, expect } = require('@playwright/test');

test('Ollama connects from the browser and its validated reply identifies the model', async ({ page, request }) => {
  await request.post('/api/settings', { data: { provider: 'local', offline_mode: false } });
  await page.route('http://127.0.0.1:11434/api/tags', route => route.fulfill({ json: { models: [{ name: 'llama3.2:3b' }] } }));
  let modelCalls = 0;
  await page.route('http://127.0.0.1:11434/api/chat', route => {
    modelCalls++;
    expect(route.request().postDataJSON().messages[0].role).toBe('system');
    return route.fulfill({ json: { message: { content: 'Repairs in this example could take 6.7 to 13.5 hours because the assigned transformer needs to be replaced.' }, done_reason: 'stop' } });
  });
  await page.goto('/');
  await expect(page.getByRole('textbox', { name: 'Message', exact: true })).toBeEnabled();
  await page.getByRole('combobox', { name: 'Choose a sample household by city' }).selectOption('h1');
  await expect(page.getByRole('textbox', { name: 'Message', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: 'Open settings', exact: true }).click();
  await page.getByRole('button', { name: 'Connect & save', exact: true }).click();
  await expect(page.locator('#settings-status')).toContainText('Connected');
  await page.getByRole('button', { name: 'Close', exact: true }).click();
  await page.getByRole('textbox', { name: 'Message', exact: true }).fill('How long could repairs take?');
  await page.getByRole('button', { name: 'Send message', exact: true }).click();
  await expect(page.locator('.reply-source')).toContainText('Ollama · llama3.2:3b');
  await expect(page.locator('.conversation')).toContainText('assigned transformer needs to be replaced');
  expect(modelCalls).toBe(1);
});

test('workspace adapts to the viewport with a compact composer and no horizontal overflow', async ({ page, request }) => {
  await request.post('/api/settings', { data: { offline_mode: true } });
  await page.goto('/');
  await expect(page.getByRole('textbox', { name: 'Message', exact: true })).toBeEnabled();
  for (const size of [{ width: 1920, height: 1080 }, { width: 1366, height: 768 }, { width: 375, height: 812 }]) {
    await page.setViewportSize(size);
    await page.getByRole('button', { name: 'Ask', exact: true }).click();
    const box = await page.locator('.composer').boundingBox();
    expect(box.width).toBeLessThanOrEqual(880);
    expect(box.y + box.height).toBeLessThanOrEqual(size.height);
    for (const view of ['Ask', 'Storm Activity', 'Wiki']) {
      await page.getByRole('button', { name: view, exact: true }).click();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
    }
  }
});
