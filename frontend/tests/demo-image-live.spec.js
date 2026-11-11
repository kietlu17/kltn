// Live photo-search rehearsal: real gateway, agentic-rag and CLIP model server.
// DEMO_TOKEN_FILE=<token> DEMO_USER_FILE=<user json> DEMO_IMAGE=<jpg> DEMO_SHOTS=<dir> npx playwright test tests/demo-image-live.spec.js
import { test, expect } from '@playwright/test';
import fs from 'node:fs';

test.skip(!process.env.DEMO_IMAGE, 'live rehearsal only');
test.setTimeout(180000);

test('shopper finds a product from a photo', async ({ page }) => {
  const token = fs.readFileSync(process.env.DEMO_TOKEN_FILE, 'utf8').trim();
  const user = JSON.parse(fs.readFileSync(process.env.DEMO_USER_FILE, 'utf8'));
  await page.addInitScript(({ token, user }) => {
    localStorage.setItem('token', token);
    localStorage.setItem('auth_user', JSON.stringify(user));
  }, { token, user });
  await page.setViewportSize({ width: 1366, height: 860 });
  await page.goto('/');
  await page.locator('.sa-launcher').click();
  const panel = page.getByRole('dialog', { name: 'Trợ lý mua sắm' });
  await expect(panel.getByLabel('Chọn ảnh sản phẩm')).toBeVisible();
  await expect(panel.getByRole('button', { name: 'Nhập bằng giọng nói' })).toHaveCount(0);

  await panel.locator('input[type=file]').setInputFiles(process.env.DEMO_IMAGE);
  await expect(panel.locator('.sa-attachment')).toBeVisible();
  const started = Date.now();
  const response = page.waitForResponse((r) => r.url().includes('/assistant/chat'), { timeout: 60000 });
  await panel.getByLabel('Gửi tin nhắn').click();
  const body = await (await response).json();
  await expect(panel.locator('article').first()).toBeVisible();
  console.log(`PHOTO ${Date.now() - started}ms route=${body.route} warnings=${body.warnings} :: ${(body.answer || '').slice(0, 120)}`);
  console.log('PRODUCTS', JSON.stringify((body.products || []).map((p) => p.name.slice(0, 50))));
  await page.screenshot({ path: `${process.env.DEMO_SHOTS}/photo-search.png` });

  const follow = page.waitForResponse((r) => r.url().includes('/assistant/chat'), { timeout: 60000 });
  await panel.getByLabel('Tin nhắn cho trợ lý').fill('cái đầu tiên giá bao nhiêu');
  await panel.getByLabel('Gửi tin nhắn').click();
  const next = await (await follow).json();
  console.log(`FOLLOW route=${next.route} :: ${(next.answer || '').slice(0, 140)}`);
  await page.screenshot({ path: `${process.env.DEMO_SHOTS}/photo-follow-up.png` });
});
