// Live demo rehearsal: real gateway, real agentic-rag, no mocks.
// DEMO_TOKEN_FILE=<token> DEMO_USER_FILE=<user json> DEMO_SHOTS=<dir> npx playwright test tests/demo-live.spec.js
import { test, expect } from '@playwright/test';
import fs from 'node:fs';

test.skip(!process.env.DEMO_TOKEN_FILE, 'live rehearsal only');
test.setTimeout(300000);

test('live assistant rehearsal', async ({ page }) => {
  const token = fs.readFileSync(process.env.DEMO_TOKEN_FILE, 'utf8').trim();
  const user = JSON.parse(fs.readFileSync(process.env.DEMO_USER_FILE, 'utf8'));
  const shots = process.env.DEMO_SHOTS;
  const consoleErrors = [];
  page.on('console', (msg) => msg.type() === 'error' && consoleErrors.push(msg.text()));
  page.on('pageerror', (err) => consoleErrors.push(String(err)));
  page.on('response', (r) => r.status() >= 400 && consoleErrors.push(`${r.status()} ${r.url()}`));
  await page.addInitScript(({ token, user }) => {
    localStorage.setItem('token', token);
    localStorage.setItem('auth_user', JSON.stringify(user));
  }, { token, user });
  await page.setViewportSize({ width: 1366, height: 860 });
  await page.goto('/');
  await page.waitForLoadState('networkidle');
  await page.locator('.sa-launcher').click();
  const panel = page.getByRole('dialog', { name: 'Trợ lý mua sắm' });
  await expect(panel).toBeVisible();
  console.log('MEDIA_BUTTONS', await panel.getByLabel('Chọn ảnh sản phẩm').count());
  let step = 0;

  async function finish(label, response) {
    const res = await response;
    await expect(panel.getByLabel('Gửi tin nhắn')).toBeVisible();
    await page.waitForTimeout(700);
    step += 1;
    const body = await res.json().catch(() => ({}));
    console.log(`STEP ${step} ${res.status()} route=${body.route} ${label} :: ${(body.answer || '').slice(0, 140).replace(/\n/g, ' / ')}`);
    await page.screenshot({ path: `${shots}/${String(step).padStart(2, '0')}.png` });
    return body;
  }

  async function say(text) {
    const response = page.waitForResponse((r) => r.url().includes('/assistant/chat'), { timeout: 60000 });
    await panel.getByLabel('Tin nhắn cho trợ lý').fill(text);
    await panel.getByLabel('Gửi tin nhắn').click();
    return finish(text, response);
  }

  async function click(name) {
    const response = page.waitForResponse((r) => r.url().includes('/assistant/chat'), { timeout: 60000 });
    await panel.getByRole('button', { name }).last().click();
    return finish(`[click ${name}]`, response);
  }

  await say('tìm tai nghe bluetooth dưới 500k');
  await say('cái thứ 2 có chống ồn không');
  const pending = await say('thêm cái đó vào giỏ');
  console.log('PENDING', JSON.stringify(pending.pendingAction));
  await click('Xác nhận thay đổi giỏ');
  console.log('CART_BADGE', await page.locator('header').first().innerText().then((t) => t.replace(/\s+/g, ' ').slice(0, 120)));
  await say('giỏ hàng của tôi có gì');
  await say('áo thun nam màu đen size L');
  await say('chính sách đổi trả thế nào');
  await say('viết cho tôi bài thơ');
  const quick = panel.locator('.sa-quick-replies button');
  if (await quick.count()) await click(await quick.first().innerText());
  console.log('ERRORS', JSON.stringify(consoleErrors.slice(0, 12)));
});
