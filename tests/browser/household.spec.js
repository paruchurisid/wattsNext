const { test, expect } = require('@playwright/test');

test.beforeEach(async ({ page, request }) => {
  const settings = await request.post('/api/settings', { data: { offline_mode: true } });
  expect(settings.ok()).toBeTruthy();
  await page.goto('/');
  await expect(page.getByRole('textbox', { name: 'Message', exact: true })).toBeEnabled();
  await page.getByRole('combobox', { name: 'Choose a sample household by city' }).selectOption('h1');
  await expect(page.getByRole('textbox', { name: 'Message', exact: true })).toBeEnabled();
});

test('Wiki risk question opens Ask with current household facts', async ({ page }) => {
  await page.getByRole('button', { name: 'Wiki', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Household A · Roanoke' })).toBeVisible();
  await page.getByRole('button', { name: 'Ask about the risk ↗', exact: true }).click();
  const conversation = page.getByRole('main', { name: 'Conversation' });
  await expect(conversation).toContainText("Why is this household's power outage risk high?");
  await expect(conversation).toContainText('High risk');
  await expect(page.getByRole('textbox', { name: 'Message', exact: true })).toBeEnabled();
});

test('Scenario changes refresh Wiki before the next question', async ({ page }) => {
  await page.getByRole('button', { name: 'Road blocked', exact: true }).click();
  await expect(page.getByRole('textbox', { name: 'Message', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: 'Wiki', exact: true }).click();
  const wiki = page.locator('#wiki-content');
  await expect(wiki).toContainText('Road blocked');
  await expect(wiki).toContainText('9.7 hours');
  await expect(wiki).toContainText('16.5 hours');
  await expect(wiki).toContainText('How sure we are: Low');
});

test('Household switching replaces Wiki without horizontal overflow', async ({ page }) => {
  await page.getByRole('combobox', { name: 'Choose a sample household by city' }).selectOption('h2');
  await expect(page.getByRole('textbox', { name: 'Message', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: 'Wiki', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Household B · Roanoke' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
});
