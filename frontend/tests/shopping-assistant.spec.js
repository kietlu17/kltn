import { test, expect } from '@playwright/test';

const productId = 'a'.repeat(24);
const sessionId = 's'.repeat(43);
const product = { id: productId, name: 'Áo cotton basic', price: 200000, imageUrl: '', variants: [] };

test.beforeEach(async ({ page }) => {
  await page.route('**/products?*', (route) => route.fulfill({ json: { items: [], pagination: { total: 0, totalPages: 1 } } }));
  await page.route('**/categories', (route) => route.fulfill({ json: [] }));
  await page.route('**/shops', (route) => route.fulfill({ json: [] }));
});

test('guest can chat, follow up with a product, and reset the session', async ({ page }) => {
  const requests = [];
  await page.route('**/assistant/chat', (route) => {
    requests.push(route.request().postDataJSON());
    return route.fulfill({ json: { sessionId, answer: 'Tôi tìm được áo cotton phù hợp.', products: [product] } });
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Trợ lý mua sắm', exact: true }).click();
  await page.getByRole('textbox', { name: 'Tin nhắn cho trợ lý' }).fill('Áo dưới 300k');
  await page.getByRole('button', { name: 'Gửi tin nhắn' }).click();
  await expect(page.getByText('Tôi tìm được áo cotton phù hợp.')).toBeVisible();
  await expect(page.getByRole('link', { name: /Áo cotton basic/ })).toHaveAttribute('href', `/product/${productId}`);
  await page.getByRole('button', { name: 'Tìm tương tự', exact: true }).click();
  await expect(page.getByText('Tôi tìm được áo cotton phù hợp.')).toHaveCount(2);
  expect(requests[1].referenceProductId).toBe(productId);
  expect(requests[1].sessionId).toBe(sessionId);
  await page.getByRole('button', { name: 'Chat mới' }).click();
  await page.getByRole('textbox', { name: 'Tin nhắn cho trợ lý' }).fill('Tìm balo');
  await page.getByRole('button', { name: 'Gửi tin nhắn' }).click();
  await expect(page.getByText('Tôi tìm được áo cotton phù hợp.')).toBeVisible();
  expect(requests[2].sessionId).toBeNull();
});

test('image upload is previewed, sent, and recoverable after service failure', async ({ page }) => {
  let received;
  await page.route('**/assistant/chat', (route) => {
    received = route.request().postDataJSON();
    return route.fulfill({ status: 503, json: { detail: 'Trợ lý đang khởi động.' } });
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Trợ lý mua sắm', exact: true }).click();
  await page.locator('input[type=file]').setInputFiles({
    name: 'sample.png', mimeType: 'image/png',
    buffer: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a1ZkAAAAASUVORK5CYII=', 'base64'),
  });
  await expect(page.getByAltText('Ảnh đã chọn')).toBeVisible();
  await page.getByRole('button', { name: 'Gửi tin nhắn' }).click();
  await expect(page.getByRole('alert')).toHaveText('Trợ lý đang khởi động.');
  expect(received.image).toMatch(/^data:image\/png;base64,/);
  await expect(page.getByAltText('Ảnh đã chọn')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Gửi tin nhắn' })).toBeEnabled();
});

test('mobile panel fits the viewport and Escape returns focus', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  const launcher = page.getByRole('button', { name: 'Trợ lý mua sắm', exact: true });
  await launcher.click();
  const box = await page.getByRole('dialog', { name: 'Trợ lý mua sắm' }).boundingBox();
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(390);
  expect(box.y).toBeGreaterThanOrEqual(0);
  await page.getByRole('textbox', { name: 'Tin nhắn cho trợ lý' }).press('Escape');
  await expect(launcher).toBeFocused();
  await expect(page.getByRole('dialog')).toHaveCount(0);
});

test('assistant is absent on seller and login routes', async ({ page }) => {
  await page.goto('/seller/login');
  await expect(page.getByRole('button', { name: 'Trợ lý mua sắm', exact: true })).toHaveCount(0);
});
