const { Op, UniqueConstraintError } = require('sequelize');
const crypto = require('crypto');
const fs = require('fs');
const https = require('https');
const fetchImpl = require('node-fetch');
const Order = require('../models/Order');
const Dispute = require('../models/Dispute');
const { publishOrderCreated, publishOrderCancelled } = require('../kafka/producer');

const PRODUCT_SERVICE_URL = process.env.PRODUCT_SERVICE_URL || 'http://localhost:3004';

function createMtlsAgent() {
  if (process.env.MTLS_ENABLED !== 'true') return null;
  const caPath = process.env.MTLS_CA_PATH || process.env.TLS_CA_PATH;
  const certPath = process.env.MTLS_CLIENT_CERT_PATH || process.env.TLS_CERT_PATH;
  const keyPath = process.env.MTLS_CLIENT_KEY_PATH || process.env.TLS_KEY_PATH;
  if (!caPath || !certPath || !keyPath) {
    throw new Error('MTLS is enabled but MTLS_CA_PATH / MTLS_CLIENT_CERT_PATH / MTLS_CLIENT_KEY_PATH is missing');
  }
  return new https.Agent({
    ca: fs.readFileSync(caPath),
    cert: fs.readFileSync(certPath),
    key: fs.readFileSync(keyPath),
    rejectUnauthorized: process.env.MTLS_REJECT_UNAUTHORIZED !== 'false'
  });
}

const mtlsAgent = createMtlsAgent();

function buildRequestOptions(url, options) {
  if (mtlsAgent && url.startsWith('https://')) {
    return { ...options, agent: mtlsAgent };
  }
  return options;
}

const ALLOWED_ORDER_STATUSES = new Set([
  'pending_payment',
  'payment_processing',
  'paid',
  'payment_failed',
  'confirmed',
  'shipped',
  'delivered',
  'cancelled'
]);

function calcTotal(products) {
  return products.reduce((sum, p) => {
    const price = Number(p.price || 0);
    const qty = Number(p.quantity || 0);
    return sum + price * qty;
  }, 0);
}

function parseOrderItems(order) {
  if (Array.isArray(order.products)) return order.products;
  if (typeof order.products === 'string') {
    try {
      return JSON.parse(order.products);
    } catch {
      return [];
    }
  }
  return [];
}

function toNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : 0;
}

function isCodPaymentMethod(paymentMethod) {
  return String(paymentMethod || '').toLowerCase() === 'cod';
}

function normalizeIdempotencyKey(value) {
  if (!value) return '';
  return String(value).trim().slice(0, 128);
}

function stableStringify(value) {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) {
    return `[${value.map((item) => stableStringify(item)).join(',')}]`;
  }
  const keys = Object.keys(value).sort();
  const pairs = keys.map((key) => `${JSON.stringify(key)}:${stableStringify(value[key])}`);
  return `{${pairs.join(',')}}`;
}

function buildIdempotencyHash(payload) {
  const serialized = stableStringify(payload);
  return crypto.createHash('sha256').update(serialized).digest('hex');
}

async function decrementStock(products) {
  const items = Array.isArray(products) ? products : [];
  if (!items.length) return;
  const payload = {
    items: items.map((item) => ({
      productId: item.productId,
      variantId: item.variantId || null,
      quantity: item.quantity
    }))
  };
  const url = `${PRODUCT_SERVICE_URL}/products/stock/decrement`;
  const response = await fetchImpl(url, buildRequestOptions(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  }));
  if (!response.ok) {
    const text = await response.text();
    const error = new Error(text || `Stock update failed with status ${response.status}`);
    error.status = response.status;
    throw error;
  }
}

async function incrementStock(products) {
  const items = Array.isArray(products) ? products : [];
  if (!items.length) return;
  const payload = {
    items: items.map((item) => ({
      productId: item.productId,
      variantId: item.variantId || null,
      quantity: item.quantity
    }))
  };
  const url = `${PRODUCT_SERVICE_URL}/products/stock/increment`;
  const response = await fetchImpl(url, buildRequestOptions(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  }));
  if (!response.ok) {
    const text = await response.text();
    const error = new Error(text || `Stock compensate failed with status ${response.status}`);
    error.status = response.status;
    throw error;
  }
}

async function cancelOrderWithCompensation(order, options = {}) {
  const isCancelled = order.status === 'cancelled';
  const previousStatus = order.status;
  const paymentMethod = String(order.payment_method || '').toLowerCase();
  const failureReason = String(options.reason || '').toLowerCase();
  const walletRefundEligible =
    paymentMethod === 'wallet' &&
    ['paid', 'payment_processing', 'payment_failed'].includes(previousStatus) &&
    failureReason !== 'insufficient_wallet_balance';
  const bankTransferRefundEligible =
    paymentMethod === 'bank_transfer' &&
    ['paid', 'confirmed', 'shipped', 'delivered'].includes(previousStatus);
  const shouldRefundToWallet = options.shouldRefundToWallet != null
    ? Boolean(options.shouldRefundToWallet)
    : (walletRefundEligible || bankTransferRefundEligible);

  if (!isCancelled) {
    order.status = 'cancelled';
    await order.save();
  }
  const items = parseOrderItems(order.toJSON ? order.toJSON() : order);
  await incrementStock(items);
  const cancelledPayload = {
    ...(order.toJSON ? order.toJSON() : order),
    cancel_reason: options.reason || null,
    shouldRefundToWallet
  };
  await publishOrderCancelled(cancelledPayload);
  if (options.reason) {
    console.log(`Order ${order.id} cancelled: ${options.reason}`);
  }
}

async function createOrder(req, res) {
  try {
    const { userId, products, shippingAddress, paymentMethod } = req.body;
    const idempotencyKey = normalizeIdempotencyKey(req.headers['idempotency-key']);
    if (!userId || !Array.isArray(products)) {
      return res.status(400).json({ message: 'userId and products are required' });
    }
    if (!shippingAddress) {
      return res.status(400).json({ message: 'shippingAddress is required' });
    }
    if (!paymentMethod) {
      return res.status(400).json({ message: 'paymentMethod is required' });
    }
    const shopIds = new Set(products.map((item) => item.shopId).filter((shopId) => shopId));
    if (shopIds.size === 0) {
      return res.status(400).json({ message: 'shopId is required for order items' });
    }
    if (shopIds.size > 1) {
      return res.status(400).json({ message: 'Each order must contain products from a single shop' });
    }

    const idempotencyHash = idempotencyKey
      ? buildIdempotencyHash({ userId, products, shippingAddress, paymentMethod })
      : null;

    if (idempotencyKey) {
      const existing = await Order.findOne({ where: { idempotency_key: idempotencyKey } });
      if (existing) {
        if (existing.idempotency_request_hash !== idempotencyHash) {
          return res.status(409).json({ message: 'Idempotency-Key is already used with a different request payload' });
        }
        return res.status(200).json(existing.toJSON());
      }
    }

    const totalPrice = calcTotal(products);
    let order;
    try {
      order = await Order.create({
        user_id: userId,
        products,
        total_price: totalPrice,
        status: 'pending_payment',
        idempotency_key: idempotencyKey || null,
        idempotency_request_hash: idempotencyHash,
        shipping_address: shippingAddress,
        payment_method: paymentMethod
      });
    } catch (err) {
      if (idempotencyKey && err instanceof UniqueConstraintError) {
        const existing = await Order.findOne({ where: { idempotency_key: idempotencyKey } });
        if (existing) {
          if (existing.idempotency_request_hash !== idempotencyHash) {
            return res.status(409).json({ message: 'Idempotency-Key is already used with a different request payload' });
          }
          return res.status(200).json(existing.toJSON());
        }
      }
      throw err;
    }

    try {
      await decrementStock(products);
    } catch (err) {
      if (err?.status === 409) {
        await Order.destroy({ where: { id: order.id } });
        return res.status(409).json({ message: 'Out of stock' });
      }
      throw err;
    }
    try {
      await publishOrderCreated(order.toJSON());
    } catch (err) {
      await cancelOrderWithCompensation(order, {
        reason: 'order_created_event_publish_failed',
        shouldRefundToWallet: false
      });
      return res.status(502).json({ message: 'Order processing failed, rolled back' });
    }
    return res.status(201).json(order.toJSON());
  } catch (err) {
    return res.status(500).json({ message: 'Create order failed', error: err.message });
  }
}

async function cancelOrder(req, res) {
  try {
    const id = Number(req.params.id);
    const order = await Order.findByPk(id);
    if (!order) {
      return res.status(404).json({ message: 'Order not found' });
    }
    const actorRole = req.headers['x-user-role'] || '';
    const actorUserId = req.headers['x-user-id'] || '';
    if (actorRole === 'buyer' && String(order.user_id) !== String(actorUserId)) {
      return res.status(403).json({ message: 'Forbidden' });
    }
    if (order.status === 'cancelled') {
      return res.json(order.toJSON());
    }
    await cancelOrderWithCompensation(order, { reason: 'manual_cancel' });
    return res.json(order.toJSON());
  } catch (err) {
    return res.status(500).json({ message: 'Cancel order failed', error: err.message });
  }
}

async function confirmOrder(req, res) {
  try {
    const id = Number(req.params.id);
    const order = await Order.findByPk(id);
    if (!order) {
      return res.status(404).json({ message: 'Order not found' });
    }
    if (order.status === 'cancelled') {
      return res.status(400).json({ message: 'Cancelled order cannot be confirmed' });
    }
    if (order.status === 'pending_payment' || order.status === 'payment_processing') {
      return res.status(400).json({ message: 'Order payment is not completed yet' });
    }
    if (order.status === 'payment_failed') {
      return res.status(400).json({ message: 'Payment failed for this order' });
    }
    const isCodOrder = isCodPaymentMethod(order.payment_method);
    if (isCodOrder) {
      if (['pending_payment', 'payment_processing', 'paid'].includes(order.status)) {
        order.status = 'confirmed';
        await order.save();
      }
      return res.json(order.toJSON());
    }
    if (['confirmed', 'shipped', 'delivered'].includes(order.status)) {
      return res.json(order.toJSON());
    }
    if (order.status !== 'paid') {
      return res.status(400).json({ message: 'Order payment is not completed yet' });
    }
    order.status = 'confirmed';
    await order.save();
    return res.json(order.toJSON());
  } catch (err) {
    return res.status(500).json({ message: 'Confirm order failed', error: err.message });
  }
}

async function getUserOrders(req, res) {
  try {
    const userId = req.params.userId;
    const orders = await Order.findAll({
      where: { user_id: userId },
      order: [['created_at', 'DESC']]
    });
    return res.json(orders.map((order) => order.toJSON()));
  } catch (err) {
    return res.status(500).json({ message: 'Get orders failed', error: err.message });
  }
}

async function getSellerOrders(req, res) {
  try {
    const { shopId } = req.params;
    if (!shopId) {
      return res.status(400).json({ message: 'shopId is required' });
    }
    const rows = await Order.findAll({ order: [['created_at', 'DESC']] });
    const orders = rows
      .map((order) => order.toJSON())
      .map((order) => {
        const items = parseOrderItems(order);
        const scopedItems = items.filter((item) => String(item.shopId) === String(shopId));
        if (scopedItems.length === 0) return null;
        return { ...order, products: scopedItems };
      })
      .filter(Boolean);
    return res.json(orders);
  } catch (err) {
    return res.status(500).json({ message: 'Get seller orders failed', error: err.message });
  }
}

async function getSellerStats(req, res) {
  try {
    const { shopId } = req.params;
    if (!shopId) {
      return res.status(400).json({ message: 'shopId is required' });
    }
    const now = new Date();
    const year = Number(req.query.year) || now.getFullYear();
    const month = Number(req.query.month) || now.getMonth() + 1;
    if (month < 1 || month > 12) {
      return res.status(400).json({ message: 'month must be between 1 and 12' });
    }
    const start = new Date(Date.UTC(year, month - 1, 1, 0, 0, 0));
    const end = new Date(Date.UTC(year, month, 1, 0, 0, 0));
    const result = await Order.findAll({
      where: {
        created_at: { [Op.gte]: start, [Op.lt]: end },
        status: { [Op.notIn]: ['cancelled', 'payment_failed'] }
      },
      order: [['created_at', 'DESC']]
    });
    let totalOrders = 0;
    let totalItems = 0;
    let totalRevenue = 0;
    result.forEach((orderRow) => {
      const order = orderRow.toJSON();
      const items = parseOrderItems(order);
      const scopedItems = items.filter((item) => String(item.shopId) === String(shopId));
      if (scopedItems.length === 0) return;
      totalOrders += 1;
      scopedItems.forEach((item) => {
        const quantity = toNumber(item.quantity);
        const price = toNumber(item.price);
        totalItems += quantity;
        totalRevenue += price * quantity;
      });
    });
    return res.json({
      shopId,
      month,
      year,
      totalOrders,
      totalItems,
      totalRevenue
    });
  } catch (err) {
    return res.status(500).json({ message: 'Get seller stats failed', error: err.message });
  }
}

async function getAdminOrders(req, res) {
  try {
    const rows = await Order.findAll({ order: [['created_at', 'DESC']] });
    return res.json(rows.map((row) => row.toJSON()));
  } catch (err) {
    return res.status(500).json({ message: 'Get admin orders failed', error: err.message });
  }
}

async function updateAdminOrderStatus(req, res) {
  try {
    const id = Number(req.params.id);
    const { status } = req.body || {};
    if (!ALLOWED_ORDER_STATUSES.has(status)) {
      return res.status(400).json({ message: 'Invalid status' });
    }
    const order = await Order.findByPk(id);
    if (!order) {
      return res.status(404).json({ message: 'Order not found' });
    }
    if (isCodPaymentMethod(order.payment_method) && status === 'paid' && order.status !== 'delivered') {
      return res.status(400).json({ message: 'COD order can be marked paid only after delivered' });
    }
    order.status = status;
    await order.save();
    return res.json(order.toJSON());
  } catch (err) {
    return res.status(500).json({ message: 'Update order status failed', error: err.message });
  }
}

async function forceCancelOrder(req, res) {
  try {
    const id = Number(req.params.id);
    const order = await Order.findByPk(id);
    if (!order) {
      return res.status(404).json({ message: 'Order not found' });
    }
    if (order.status !== 'cancelled') {
      await cancelOrderWithCompensation(order, { reason: 'admin_force_cancel' });
    }
    return res.json(order.toJSON());
  } catch (err) {
    return res.status(500).json({ message: 'Force cancel order failed', error: err.message });
  }
}

async function createDispute(req, res) {
  try {
    const orderId = Number(req.params.id);
    const order = await Order.findByPk(orderId);
    if (!order) {
      return res.status(404).json({ message: 'Order not found' });
    }
    const actorUserId = req.headers['x-user-id'] || '';
    const actorRole = req.headers['x-user-role'] || '';
    if (actorRole === 'buyer' && String(order.user_id) !== String(actorUserId)) {
      return res.status(403).json({ message: 'Forbidden' });
    }
    const { reason, note, evidenceText } = req.body || {};
    if (!reason || !String(reason).trim()) {
      return res.status(400).json({ message: 'reason is required' });
    }
    const dispute = await Dispute.create({
      order_id: orderId,
      user_id: order.user_id,
      reason: String(reason).trim(),
      note: typeof note === 'string' ? note : '',
      evidence_text: typeof evidenceText === 'string' ? evidenceText : '',
      status: 'open'
    });
    return res.status(201).json(dispute.toJSON());
  } catch (err) {
    return res.status(500).json({ message: 'Create dispute failed', error: err.message });
  }
}

async function getAdminDisputes(req, res) {
  try {
    const rows = await Dispute.findAll({ order: [['created_at', 'DESC']] });
    return res.json(rows.map((row) => row.toJSON()));
  } catch (err) {
    return res.status(500).json({ message: 'Get disputes failed', error: err.message });
  }
}

async function updateAdminDispute(req, res) {
  try {
    const id = Number(req.params.id);
    const { status, note } = req.body || {};
    if (!['resolved', 'rejected'].includes(status)) {
      return res.status(400).json({ message: 'status must be resolved or rejected' });
    }
    const dispute = await Dispute.findByPk(id);
    if (!dispute) {
      return res.status(404).json({ message: 'Dispute not found' });
    }
    dispute.status = status;
    dispute.handled_by = req.headers['x-user-id'] || null;
    dispute.handled_note = typeof note === 'string' ? note : '';
    dispute.handled_at = new Date();
    await dispute.save();
    return res.json(dispute.toJSON());
  } catch (err) {
    return res.status(500).json({ message: 'Update dispute failed', error: err.message });
  }
}

async function handlePaymentPending(event) {
  const orderId = Number(event?.orderId);
  if (!Number.isFinite(orderId)) return;
  const order = await Order.findByPk(orderId);
  if (!order) return;
  if (order.status === 'pending_payment') {
    order.status = 'payment_processing';
    await order.save();
  }
}

async function handlePaymentSucceeded(event) {
  const orderId = Number(event?.orderId);
  if (!Number.isFinite(orderId)) return;
  const order = await Order.findByPk(orderId);
  if (!order || order.status === 'cancelled') return;
  const paymentMethod = String(order.payment_method || '').toLowerCase();
  if (paymentMethod === 'cod') {
    // Ignore COD success events to avoid premature "paid" status before delivery.
    return;
  }
  if (paymentMethod === 'wallet' && event?.walletDebited !== true) {
    order.status = 'payment_failed';
    await order.save();
    await cancelOrderWithCompensation(order, {
      reason: 'wallet_debit_not_confirmed',
      shouldRefundToWallet: false
    });
    return;
  }
  order.status = 'paid';
  await order.save();
}

async function handlePaymentFailed(event) {
  const orderId = Number(event?.orderId);
  if (!Number.isFinite(orderId)) return;
  const order = await Order.findByPk(orderId);
  if (!order || order.status === 'cancelled') return;
  if (['paid', 'confirmed', 'shipped', 'delivered'].includes(order.status)) return;
  order.status = 'payment_failed';
  await order.save();
  const reason = event?.reason || 'payment_failed';
  await cancelOrderWithCompensation(order, {
    reason,
    shouldRefundToWallet:
      String(order.payment_method || '').toLowerCase() === 'wallet' &&
      String(reason).toLowerCase() !== 'insufficient_wallet_balance'
  });
}

async function handlePaymentTimeout(event) {
  const orderId = Number(event?.orderId);
  if (!Number.isFinite(orderId)) return;
  const order = await Order.findByPk(orderId);
  if (!order || order.status === 'cancelled') return;
  if (['paid', 'confirmed', 'shipped', 'delivered'].includes(order.status)) return;
  order.status = 'payment_failed';
  await order.save();
  await cancelOrderWithCompensation(order, {
    reason: event?.reason || 'payment_timeout',
    shouldRefundToWallet: String(order.payment_method || '').toLowerCase() === 'wallet'
  });
}

module.exports = {
  createOrder,
  cancelOrder,
  confirmOrder,
  getUserOrders,
  getSellerOrders,
  getSellerStats,
  getAdminOrders,
  updateAdminOrderStatus,
  forceCancelOrder,
  createDispute,
  getAdminDisputes,
  updateAdminDispute,
  handlePaymentPending,
  handlePaymentSucceeded,
  handlePaymentFailed,
  handlePaymentTimeout
};
