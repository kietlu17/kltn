import { test, expect } from '@playwright/test';

const productId = 'a'.repeat(24);
const product = { _id: productId, name: 'Áo cotton', price: 200000, quantity: 5, images: [], variants: [] };

async function mockProductPage(page) {
  await page.route('**/products**', (route) => {
    const path = new URL(route.request().url()).pathname;
    return route.fulfill({ json: path === `/products/${productId}`
      ? product
      : { items: [product], pagination: { total: 1, totalPages: 1 } } });
  });
  await page.route('**/categories', (route) => route.fulfill({ json: [] }));
  await page.route('**/shops', (route) => route.fulfill({ json: [] }));
}

async function mockMicrophone(page) {
  await page.addInitScript(() => {
    window.stoppedTracks = 0;
    Object.defineProperty(navigator, 'mediaDevices', { value: {
      getUserMedia: async () => ({ getTracks: () => [{ stop: () => { window.stoppedTracks += 1; } }] })
    } });
    window.MediaRecorder = class {
      static isTypeSupported() { return true; }
      state = 'inactive';
      start() { this.state = 'recording'; }
      stop() {
        this.state = 'inactive';
        this.ondataavailable?.({ data: new Blob(['audio'], { type: 'audio/webm' }) });
        this.onstop?.();
      }
    };
  });
}

test('AI tab sends an uploaded image to chatbot-service', async ({ page }) => {
  await mockProductPage(page);
  let received;
  await page.route('**/assistant/chat', (route) => {
    received = route.request().postDataJSON();
    return route.fulfill({ json: { sessionId: 's'.repeat(43), answer: 'Đã tìm theo ảnh.', products: [] } });
  });
  await page.goto(`/product/${productId}`);
  await page.getByRole('button', { name: 'Chat với shop' }).click();
  await page.locator('.chat-widget input[type=file]').setInputFiles({
    name: 'sample.png',
    mimeType: 'image/png',
    buffer: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a1ZkAAAAASUVORK5CYII=', 'base64')
  });
  await expect(page.getByAltText('Ảnh đã chọn')).toBeVisible();
  await page.getByRole('button', { name: 'Gửi', exact: true }).click();
  await expect(page.getByText('Đã tìm theo ảnh.')).toBeVisible();
  expect(received.image).toMatch(/^data:image\/png;base64,/);
  expect(received.referenceProductId).toBe(productId);
});

test('microphone transcribes into the AI draft without sending it', async ({ page }) => {
  await mockMicrophone(page);
  await mockProductPage(page);
  let chatCalls = 0;
  await page.route('**/assistant/chat', (route) => {
    chatCalls += 1;
    return route.fulfill({ json: {} });
  });
  await page.route('**/assistant/transcribe', (route) => route.fulfill({ json: { text: 'tai nghe dưới 500k' } }));
  await page.goto(`/product/${productId}`);
  await page.getByRole('button', { name: 'Chat với shop' }).click();
  await page.getByPlaceholder('Hỏi về sản phẩm này...').fill('Tìm');
  await page.getByRole('button', { name: 'Nhập bằng giọng nói' }).click();
  await page.getByRole('button', { name: 'Dừng thu âm' }).click();
  await expect(page.getByPlaceholder('Hỏi về sản phẩm này...')).toHaveValue('Tìm tai nghe dưới 500k');
  expect(chatCalls).toBe(0);
  expect(await page.evaluate(() => window.stoppedTracks)).toBeGreaterThan(0);
});
