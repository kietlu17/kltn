const crypto = require('crypto');
const CheckoutQuote = require('../models/CheckoutQuote');
const { canonicalizeProducts, ownedAddress, requestJson, withAgent } = require('../services/commerceData');

const ORDER_SERVICE_URL = process.env.ORDER_SERVICE_URL || 'http://localhost:3006';
const VOUCHER_SERVICE_URL = process.env.VOUCHER_SERVICE_URL || 'http://localhost:3013';
const QUOTE_TTL_SECONDS = Math.max(60, Number(process.env.CHECKOUT_QUOTE_TTL_SECONDS || 600));
const PAYMENT_METHODS = new Set(['cod', 'bank_transfer']);

function actor(req, requestedUserId) {
  const userId = String(req.headers['x-user-id'] || '');
  const role = String(req.headers['x-user-role'] || '');
  if (!userId || !['buyer', 'admin'].includes(role)) {
    const error = new Error('Authenticated buyer is required');
    error.status = 401;
    throw error;
  }
  if (role === 'buyer' && requestedUserId && String(requestedUserId) !== userId) {
    const error = new Error('Forbidden');
    error.status = 403;
    throw error;
  }
  return role === 'admin' && requestedUserId ? String(requestedUserId) : userId;
}

function digest(value) {
  return crypto.createHash('sha256').update(String(value)).digest('hex');
}

function safeEqual(left, right) {
  const a = Buffer.from(String(left));
  const b = Buffer.from(String(right));
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}

function quoteView(quote, confirmationToken) {
  const value = quote.toJSON ? quote.toJSON() : quote;
  return {
    quoteId: value.id,
    products: value.products,
    shippingAddress: value.shipping_address,
    paymentMethod: value.payment_method,
    voucherCode: value.voucher_code,
    subtotalPrice: Number(value.subtotal_price),
    totalPrice: Number(value.total_price),
    status: value.status,
    expiresAt: value.expires_at,
    ...(confirmationToken ? { confirmationToken } : {})
  };
}

function sendError(res, error, fallback) {
  const status = Number(error?.status);
  return res.status(Number.isInteger(status) && status >= 400 && status < 600 ? status : 500).json({
    message: status ? error.message : fallback,
    ...(error?.code ? { code: error.code } : {}),
    ...(!status ? { error: error.message } : {})
  });
}

async function previewVoucher(userId, voucherCode, products) {
  const code = String(voucherCode || '').trim();
  if (!code) return 0;
  const vouchers = await requestJson(`${VOUCHER_SERVICE_URL}/vouchers/checkout`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'x-user-id': userId,
      'x-user-role': 'buyer'
    },
    body: JSON.stringify({
      userId,
      items: products.map((item) => ({
        productId: item.productId,
        shopId: item.shopId,
        price: Number(item.price),
        quantity: Number(item.quantity)
      }))
    })
  });
  const voucher = (Array.isArray(vouchers) ? vouchers : []).find(
    (item) => String(item.code || '').toLowerCase() === code.toLowerCase()
  );
  if (!voucher || !voucher.eligible) {
    const error = new Error(voucher?.reason || 'Voucher is no longer eligible');
    error.status = 409;
    error.code = 'VOUCHER_CHANGED';
    throw error;
  }
  return Math.max(0, Number(voucher.discountAmount || 0));
}

async function createCheckoutQuote(req, res) {
  try {
    const userId = actor(req, req.body?.userId);
    const paymentMethod = String(req.body?.paymentMethod || '').toLowerCase();
    if (paymentMethod === 'wallet') {
      return res.status(409).json({
        code: 'STEP_UP_REQUIRED',
        message: 'Wallet auto-payment is disabled until a one-time payment authorization is supplied'
      });
    }
    if (!PAYMENT_METHODS.has(paymentMethod)) {
      return res.status(400).json({ message: 'paymentMethod must be cod or bank_transfer' });
    }
    const [products, shippingAddress] = await Promise.all([
      canonicalizeProducts(req.body?.products, { singleShop: true }),
      ownedAddress(userId, req.body?.addressId)
    ]);
    const subtotalPrice = products.reduce((sum, item) => sum + item.price * item.quantity, 0);
    const discountAmount = Math.min(
      await previewVoucher(userId, req.body?.voucherCode, products),
      subtotalPrice
    );
    const confirmationToken = crypto.randomBytes(32).toString('base64url');
    const quote = await CheckoutQuote.create({
      user_id: userId,
      session_id: String(req.body?.sessionId || '').slice(0, 128) || null,
      products,
      shipping_address: shippingAddress,
      payment_method: paymentMethod,
      voucher_code: req.body?.voucherCode ? String(req.body.voucherCode).trim().slice(0, 40) : null,
      subtotal_price: subtotalPrice,
      total_price: Math.max(subtotalPrice - discountAmount, 0),
      confirmation_digest: digest(confirmationToken),
      status: 'open',
      order_ids: [],
      expires_at: new Date(Date.now() + QUOTE_TTL_SECONDS * 1000)
    });
    return res.status(201).json(quoteView(quote, confirmationToken));
  } catch (error) {
    return sendError(res, error, 'Create checkout quote failed');
  }
}

async function confirmCheckout(req, res) {
  let quote;
  try {
    const userId = actor(req, req.body?.userId);
    quote = await CheckoutQuote.findByPk(req.params.id);
    if (!quote || String(quote.user_id) !== userId) return res.status(404).json({ message: 'Checkout quote not found' });
    if (quote.session_id && String(req.body?.sessionId || '') !== String(quote.session_id)) {
      return res.status(403).json({ message: 'Checkout quote belongs to a different session' });
    }
    const tokenDigest = digest(req.body?.confirmationToken || '');
    if (!safeEqual(tokenDigest, quote.confirmation_digest)) {
      return res.status(403).json({ message: 'Invalid checkout confirmation' });
    }
    if (quote.status === 'committed') {
      return res.json({ ...quoteView(quote), orderIds: quote.order_ids, replayed: true });
    }
    if (new Date(quote.expires_at).getTime() <= Date.now()) {
      quote.status = 'expired';
      await quote.save();
      return res.status(410).json({ message: 'Checkout quote expired; create a new quote' });
    }
    if (!['open', 'failed'].includes(quote.status)) {
      return res.status(409).json({ message: 'Checkout is already being processed' });
    }
    const [claimed] = await CheckoutQuote.update(
      { status: 'committing' },
      { where: { id: quote.id, status: ['open', 'failed'] } }
    );
    if (claimed !== 1) {
      return res.status(409).json({ message: 'Checkout is already being processed' });
    }
    quote.status = 'committing';

    // Re-price and re-check stock immediately before the irreversible action.
    const products = await canonicalizeProducts(quote.products, { singleShop: true });
    const currentSubtotal = products.reduce((sum, item) => sum + item.price * item.quantity, 0);
    const currentDiscount = Math.min(
      await previewVoucher(userId, quote.voucher_code, products),
      currentSubtotal
    );
    const currentTotal = Math.max(currentSubtotal - currentDiscount, 0);
    const originalLines = JSON.stringify((quote.products || []).map((item) => ({
      productId: item.productId,
      variantId: item.variantId || null,
      quantity: Number(item.quantity),
      price: Number(item.price),
      shopId: item.shopId
    })));
    const currentLines = JSON.stringify(products.map((item) => ({
      productId: item.productId,
      variantId: item.variantId || null,
      quantity: Number(item.quantity),
      price: Number(item.price),
      shopId: item.shopId
    })));
    if (
      currentSubtotal !== Number(quote.subtotal_price)
      || currentTotal !== Number(quote.total_price)
      || currentLines !== originalLines
    ) {
      quote.status = 'expired';
      await quote.save();
      return res.status(409).json({
        code: 'QUOTE_CHANGED',
        message: 'Price or product data changed; review a new checkout quote before confirming'
      });
    }
    const url = `${ORDER_SERVICE_URL}/orders`;
    const response = await require('node-fetch')(url, withAgent(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Idempotency-Key': `checkout:${quote.id}`,
        'x-user-id': userId,
        'x-user-role': 'buyer'
      },
      body: JSON.stringify({
        userId,
        products,
        shippingAddress: quote.shipping_address,
        paymentMethod: quote.payment_method,
        voucherCode: quote.voucher_code
      })
    }));
    const text = await response.text();
    let orderPayload;
    try {
      orderPayload = text ? JSON.parse(text) : null;
    } catch {
      orderPayload = null;
    }
    if (!response.ok) {
      const error = new Error(orderPayload?.message || `Order creation failed with status ${response.status}`);
      error.status = response.status;
      throw error;
    }
    quote.products = products;
    quote.subtotal_price = Number(orderPayload.subtotal_price);
    quote.total_price = Number(orderPayload.total_price);
    quote.order_ids = [orderPayload.id];
    quote.status = 'committed';
    await quote.save();
    return res.status(201).json({
      ...quoteView(quote),
      orderIds: quote.order_ids,
      order: orderPayload,
      paymentStatus: quote.payment_method === 'bank_transfer' ? 'awaiting_transfer' : 'pending_cod'
    });
  } catch (error) {
    if (quote && quote.status === 'committing') {
      quote.status = 'failed';
      try {
        await quote.save();
      } catch {
        // Preserve the original failure.
      }
    }
    return sendError(res, error, 'Confirm checkout failed');
  }
}

module.exports = { createCheckoutQuote, confirmCheckout };
