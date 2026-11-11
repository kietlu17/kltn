// Live checkout rehearsal: chat "thanh toán" -> storefront checkout page -> COD order.
// Needs a demo buyer with a cart item and a default address.
// DEMO_TOKEN_FILE=<token> DEMO_USER_FILE=<user json> DEMO_SHOTS=<dir> npx playwright test tests/demo-checkout-live.spec.js
import { test, expect } from '@playwright/test';
import fs from 'node:fs';

test.skip(!process.env.DEMO_TOKEN_FILE, 'live rehearsal only');
test.setTimeout(180000);

test('chat checkout hands off to the checkout page and places a COD order', async ({ page }) => {
  const token = fs.readFileSync(process.env.DEMO_TOKEN_FILE, 'utf8').trim();
  const user = JSON.parse(fs.readFileSync(process.env.DEMO_USER_FILE, 'utf8'));
  const shots = process.env.DEMO_SHOTS;
  await page.addInitScript(({ token, user }) => {
    localStorage.setItem('token', token);
    localStorage.setItem('auth_user', JSON.stringify(user));
  }, { token, user });
  await page.setViewportSize({ width: 1366, height: 900 });
  await page.goto('/');
  await page.locator('.sa-launcher').click();
  const panel = page.getByRole('dialog', { name: 'Trợ lý mua sắm' });

  async function say(text) {
    const reply = page.waitForResponse((r) => r.url().includes('/assistant/chat'), { timeout: 60000 });
    await panel.getByLabel('Tin nhắn cho trợ lý').fill(text);
    await panel.getByLabel('Gửi tin nhắn').click();
    const data = await (await reply).json();
    await expect(panel.getByLabel('Gửi tin nhắn')).toBeVisible();
    console.log(`SAY ${text} -> route=${data.route} :: ${(data.answer || '').replace(/\n/g, ' / ').slice(0, 120)}`);
    return data;
  }

  await say('tìm tai nghe bluetooth dưới 500k');
  await say('thêm cái đầu tiên vào giỏ');
  const confirmed = page.waitForResponse((r) => r.url().includes('/assistant/chat'), { timeout: 60000 });
  await panel.getByRole('button', { name: 'Xác nhận thay đổi giỏ' }).last().click();
  console.log('CONFIRM', ((await (await confirmed).json()).answer || '').slice(0, 120));

  const reply = page.waitForResponse((r) => r.url().includes('/assistant/chat'), { timeout: 60000 });
  await panel.getByLabel('Tin nhắn cho trợ lý').fill('thanh toán khi nhận hàng');
  await panel.getByLabel('Gửi tin nhắn').click();
  const body = await (await reply).json();
  console.log(`CHAT route=${body.route} tool=${body.actionResult?.tool} :: ${(body.answer || '').replace(/\n/g, ' / ').slice(0, 200)}`);

  await page.waitForURL('**/checkout', { timeout: 15000 });
  await page.waitForLoadState('networkidle');
  await expect(page.locator('input[value="cod"]')).toBeChecked();
  await page.waitForTimeout(1500);
  await expect(page.getByText('Một số sản phẩm đã hết hàng')).toHaveCount(0);
  await page.screenshot({ path: `${shots}/checkout-page.png`, fullPage: true });
  console.log('CHECKOUT_PAGE', (await page.locator('main').innerText()).replace(/\s+/g, ' ').slice(0, 400));

  const order = page.waitForResponse((r) => r.url().includes('/orders') && r.request().method() === 'POST', { timeout: 60000 });
  await page.locator('button.btn-primary.btn-full').click();
  const created = await order;
  console.log(`ORDER_POST ${created.status()}`);
  await page.waitForURL('**/orders', { timeout: 30000 });
  await page.waitForLoadState('networkidle');
  await page.screenshot({ path: `${shots}/orders-page.png` });
  console.log('ORDERS_PAGE', (await page.locator('main').innerText()).replace(/\s+/g, ' ').slice(0, 300));
});
