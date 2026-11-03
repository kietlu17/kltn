import { test, expect } from '@playwright/test';

const productId = 'a'.repeat(24);
const shopId = 'b'.repeat(24);
const buyerId = 'c'.repeat(24);
const sessionId = 's'.repeat(43);
const product = {
  _id: productId,
  name: 'Áo cotton basic',
  price: 200000,
  quantity: 12,
  shopId,
  images: [],
  variants: []
};

async function mockProductPage(page, { loggedIn = false } = {}) {
  if (loggedIn) {
    await page.addInitScript(({ buyerId }) => {
      localStorage.setItem('token', 'test-token');
      localStorage.setItem('auth_user', JSON.stringify({ id: buyerId, email: 'buyer@test.local', role: 'buyer' }));
    }, { buyerId });
  }

  await page.route('**/products**', (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === `/products/${productId}`) return route.fulfill({ json: product });
    return route.fulfill({ json: { items: [product], pagination: { total: 1, totalPages: 1 } } });
  });
  await page.route('**/categories', (route) => route.fulfill({ json: [] }));
  await page.route('**/shops', (route) => route.fulfill({ json: [{ _id: shopId, name: 'Shop demo' }] }));
  await page.route('**/cart/user', (route) => route.fulfill({ json: { products: [] } }));
  await page.route('**/orders/**', (route) => route.fulfill({ json: [] }));
  await page.route('**/reviews/product/**', (route) => route.fulfill({ json: [] }));
  await page.route('**/vouchers/checkout', (route) => route.fulfill({ json: [] }));
}

test('guest sees the original floating shopping assistant', async ({ page }) => {
  await mockProductPage(page);
  await page.goto('/');
  const launcher = page.getByRole('button', { name: 'Trợ lý mua sắm', exact: true });
  await expect(launcher).toBeVisible();
  await launcher.click();
  await expect(page.getByRole('dialog', { name: 'Trợ lý mua sắm' })).toBeVisible();
});

test('product cards show cart and similar actions without a size advice button', async ({ page }) => {
  await mockProductPage(page);
  const selectedId = '6ad8cc23a55a838dfd3437b6';
  const selectedName = 'Áo Sơ Mi Nữ Dáng Suông Trễ Cổ';
  const requests = [];
  await page.route('**/assistant/chat', (route) => {
    requests.push(route.request().postDataJSON());
    return route.fulfill({ json: {
      sessionId,
      answer: requests.length === 1 ? 'Chọn một mẫu để tư vấn.' : 'Bạn cho biết chiều cao và cân nặng nhé.',
      products: requests.length === 1 ? [
        { id: productId, name: product.name, price: product.price },
        { id: selectedId, name: selectedName, price: 49000 },
      ] : [],
    } });
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Trợ lý mua sắm', exact: true }).click();
  const panel = page.getByRole('dialog', { name: 'Trợ lý mua sắm' });
  const input = panel.getByRole('textbox', { name: 'Tin nhắn cho trợ lý' });
  await input.fill('tôi muốn mua áo sơ mi trắng nữ');
  await panel.getByRole('button', { name: 'Gửi tin nhắn', exact: true }).click();
  const card = panel.locator('.sa-product').filter({ hasText: selectedName });
  await expect(card).toBeVisible();
  await expect(panel.getByRole('button', { name: 'Tư vấn size', exact: true })).toHaveCount(0);
  await expect(card.getByRole('button', { name: 'Thêm giỏ', exact: true })).toBeVisible();
  await card.getByRole('button', { name: 'Tìm tương tự', exact: true }).click();
  await expect.poll(() => requests.length).toBe(2);
  expect(requests[1]).toMatchObject({
    message: `Tìm sản phẩm tương tự ${selectedName}`, referenceProductId: selectedId, sessionId, image: null,
  });
  await expect(panel.getByText('Bạn cho biết chiều cao và cân nặng nhé.', { exact: true })).toBeVisible();
  await expect(page).toHaveURL(/\/$/);
});

test('AI tab uses chatbot-service endpoint and keeps its session', async ({ page }) => {
  await mockProductPage(page);
  const requests = [];
  let legacyCalls = 0;
  await page.route('**/chat/ai/respond', (route) => {
    legacyCalls += 1;
    return route.abort();
  });
  await page.route('**/assistant/chat', (route) => {
    requests.push(route.request().postDataJSON());
    return route.fulfill({ json: {
      sessionId,
      answer: 'Sản phẩm này dùng vải cotton.',
      products: [{ id: productId, name: product.name, price: product.price, variants: [] }]
    } });
  });

  await page.goto(`/product/${productId}`);
  await page.getByRole('button', { name: 'Chat với shop' }).click();
  await page.getByPlaceholder('Hỏi về sản phẩm này...').fill('Chất liệu là gì?');
  await page.getByRole('button', { name: 'Gửi', exact: true }).click();
  await expect(page.getByText('Sản phẩm này dùng vải cotton.')).toBeVisible();
  await expect(page.getByRole('link', { name: /Áo cotton basic/ })).toHaveAttribute('href', `/product/${productId}`);

  await page.getByPlaceholder('Hỏi về sản phẩm này...').fill('Còn hàng không?');
  await page.getByRole('button', { name: 'Gửi', exact: true }).click();
  await expect.poll(() => requests.length).toBe(2);
  expect(requests[0].referenceProductId).toBe(productId);
  expect(requests[0].sessionId).toBeNull();
  expect(requests[1].sessionId).toBe(sessionId);
  expect(legacyCalls).toBe(0);
});

test('human tab keeps the existing conversation flow', async ({ page }) => {
  await mockProductPage(page, { loggedIn: true });
  const conversationRequests = [];
  await page.route('**/chat/conversations', async (route) => {
    conversationRequests.push(route.request().postDataJSON());
    return route.fulfill({ json: { id: 'conversation-1' } });
  });
  await page.route('**/chat/conversations/conversation-1/messages', (route) => {
    if (route.request().method() === 'POST') {
      return route.fulfill({ status: 201, json: {
        id: 'message-1', senderRole: 'buyer', text: route.request().postDataJSON().text
      } });
    }
    return route.fulfill({ json: [] });
  });

  await page.goto(`/product/${productId}`);
  await page.getByRole('button', { name: 'Chat với shop' }).click();
  await page.getByRole('button', { name: 'Chat với người bán' }).click();
  await expect.poll(() => conversationRequests.length).toBe(1);
  expect(conversationRequests[0]).toMatchObject({ shopId, buyerId, product: { productId } });

  await page.getByPlaceholder('Nhắn cho người bán...').fill('Shop còn màu đen không?');
  await page.getByRole('button', { name: 'Gửi', exact: true }).click();
  await expect(page.getByText('Shop còn màu đen không?')).toBeVisible();
});

test('guest can use AI but is asked to log in for seller chat', async ({ page }) => {
  await mockProductPage(page);
  await page.goto(`/product/${productId}`);
  await page.getByRole('button', { name: 'Chat với shop' }).click();
  await expect(page.getByPlaceholder('Hỏi về sản phẩm này...')).toBeVisible();
  await page.getByRole('button', { name: 'Chat với người bán' }).click();
  await expect(page.getByText('Vui lòng đăng nhập tài khoản người mua để chat với người bán')).toBeVisible();
  await expect(page.getByPlaceholder('Hỏi về sản phẩm này...')).toBeVisible();
});

test('quick replies resend their text and handoff opens seller chat on a product page', async ({ page }) => {
  await mockProductPage(page, { loggedIn: true });
  await page.route('**/chat/conversations**', (route) => route.fulfill({
    json: new URL(route.request().url()).pathname.endsWith('/messages') ? [] : { id: 'conv-1' },
  }));
  const requests = [];
  await page.route('**/assistant/chat', (route) => {
    requests.push(route.request().postDataJSON());
    return route.fulfill({ json: requests.length === 1
      ? { sessionId, answer: 'Bạn muốn tìm loại sản phẩm nào?', products: [], route: 'clarify',
        suggestions: ['Thời trang', 'Điện tử'], handoff: false }
      : { sessionId, answer: 'Bạn có muốn chat trực tiếp với nhân viên shop không?', products: [],
        route: 'clarify', suggestions: [], handoff: true } });
  });
  await page.goto(`/product/${productId}`);
  await page.getByRole('button', { name: 'Trợ lý mua sắm', exact: true }).click();
  const panel = page.getByRole('dialog', { name: 'Trợ lý mua sắm' });
  await panel.getByRole('textbox', { name: 'Tin nhắn cho trợ lý' }).fill('cái đó');
  await panel.getByRole('button', { name: 'Gửi tin nhắn', exact: true }).click();
  const replies = panel.getByRole('group', { name: 'Gợi ý trả lời nhanh' });
  await expect(replies.getByRole('button', { name: 'Điện tử', exact: true })).toBeVisible();
  await replies.getByRole('button', { name: 'Điện tử', exact: true }).click();
  await expect.poll(() => requests.length).toBe(2);
  expect(requests[1]).toMatchObject({ message: 'Điện tử', sessionId });
  // Quick replies belong to the latest assistant turn only.
  await expect(panel.getByRole('group', { name: 'Gợi ý trả lời nhanh' })).toHaveCount(0);
  await panel.getByRole('button', { name: 'Chat với người bán', exact: true }).click();
  await expect(page.getByRole('dialog', { name: 'Trợ lý mua sắm' })).toHaveCount(0);
  await expect(page.locator('.chat-tab.active')).toHaveText('Chat với người bán');
});
