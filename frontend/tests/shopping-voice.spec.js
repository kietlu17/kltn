import { test, expect } from '@playwright/test';

async function mockMicrophone(page, denied = false) {
  await page.addInitScript(({ denied }) => {
    window.stoppedTracks = 0;
    Object.defineProperty(navigator, 'mediaDevices', { value: { getUserMedia: async () => {
      if (denied) throw new DOMException('denied', 'NotAllowedError');
      return { getTracks: () => [{ stop: () => { window.stoppedTracks++; } }] };
    } } });
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
  }, { denied });
}

test('microphone transcribes into draft without sending and releases tracks', async ({ page }) => {
  await mockMicrophone(page);
  let chats = 0;
  await page.route('**/assistant/chat', route => { chats++; return route.fulfill({ json: {} }); });
  await page.route('**/assistant/transcribe', route => route.fulfill({ json: { text: 'tai nghe dưới 500k' } }));
  await page.goto('/');
  await page.getByRole('button', { name: 'Trợ lý mua sắm', exact: true }).click();
  await page.getByRole('textbox', { name: 'Tin nhắn cho trợ lý' }).fill('Tìm');
  await page.getByRole('button', { name: 'Nhập bằng giọng nói' }).click();
  await expect(page.getByRole('button', { name: 'Gửi tin nhắn' })).toBeDisabled();
  await page.getByRole('button', { name: 'Dừng thu âm' }).click();
  await expect(page.getByRole('textbox', { name: 'Tin nhắn cho trợ lý' })).toHaveValue('Tìm tai nghe dưới 500k');
  expect(chats).toBe(0);
  expect(await page.evaluate(() => window.stoppedTracks)).toBeGreaterThan(0);
  await page.getByRole('button', { name: 'Nhập bằng giọng nói' }).click();
  await page.getByRole('button', { name: 'Đóng trợ lý' }).click();
  expect(await page.evaluate(() => window.stoppedTracks)).toBeGreaterThan(1);
});

test('microphone permission denial leaves typed text intact', async ({ page }) => {
  await mockMicrophone(page, true);
  await page.goto('/');
  await page.getByRole('button', { name: 'Trợ lý mua sắm', exact: true }).click();
  await page.getByRole('textbox', { name: 'Tin nhắn cho trợ lý' }).fill('Tìm áo');
  await page.getByRole('button', { name: 'Nhập bằng giọng nói' }).click();
  await expect(page.getByRole('alert')).toContainText('cho phép truy cập micro');
  await expect(page.getByRole('textbox', { name: 'Tin nhắn cho trợ lý' })).toHaveValue('Tìm áo');
  await expect(page.getByRole('button', { name: 'Gửi tin nhắn' })).toBeEnabled();
});
