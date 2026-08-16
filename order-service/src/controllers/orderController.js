const { Op, UniqueConstraintError } = require('sequelize');
const crypto = require('crypto');
const fs = require('fs');
const https = require('https');
const fetchImpl = require('node-fetch');
const Order = require('../models/Order');
const Shipment = require('../models/Shipment');
const Dispute = require('../models/Dispute');
const {
  publishOrderCreated,
  publishOrderCancelled,
  publishOrderRefundRequested,
  publishOrderPaid,
  publishOrderDelivered
} = require('../kafka/producer');

const INVENTORY_SERVICE_URL = process.env.INVENTORY_SERVICE_URL || 'http://localhost:3007';
const VOUCHER_SERVICE_URL = process.env.VOUCHER_SERVICE_URL || 'http://localhost:3013';
const SETTLEMENT_DELAY_DAYS = Number(process.env.SETTLEMENT_DELAY_DAYS || 15);
const SHIPMENT_STATUSES = new Set(['requested', 'handed_over', 'picked_up', 'in_transit', 'delivered', 'failed']);

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
  'refund_processing',
  'refunded',
  'cancelled'
]);
const AUTO_REFUND_PAYMENT_METHODS = new Set(['wallet', 'bank_transfer']);

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

function getPrimaryShopId(order) {
  const items = parseOrderItems(order);
  const firstShopId = items.find((item) => item?.shopId)?.shopId;
  return firstShopId ? String(firstShopId) : '';
}

function toNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : 0;
}

function isCodPaymentMethod(paymentMethod) {
  return String(paymentMethod || '').toLowerCase() === 'cod';
}

function isAutoRefundPaymentMethod(paymentMethod) {
  return AUTO_REFUND_PAYMENT_METHODS.has(String(paymentMethod || '').toLowerCase());
}

function shouldCommitStockTransition(currentStatus, nextStatus) {
  return (
    ['pending_payment', 'payment_processing'].includes(currentStatus) &&
    ['paid', 'confirmed', 'shipped', 'delivered'].includes(nextStatus)
  );
}

function buildSettlementEligibleAt(deliveredAt) {
  const base = deliveredAt instanceof Date ? deliveredAt : new Date(deliveredAt || Date.now());
  return new Date(base.getTime() + SETTLEMENT_DELAY_DAYS * 24 * 60 * 60 * 1000);
}

function buildTrackingCode(orderId) {
  const suffix = crypto.randomBytes(3).toString('hex').toUpperCase();
  return `MOCK-${orderId}-${suffix}`;
}

async function ensureShipmentForOrder(order, options = {}) {
  const orderId = Number(order?.id);
  if (!Number.isFinite(orderId)) return null;
  const shopId = getPrimaryShopId(order.toJSON ? order.toJSON() : order);
  let shipment = await Shipment.findOne({ where: { order_id: orderId } });
  if (shipment) {
    if (!order.shipment_tracking_code) {
      order.shipment_tracking_code = shipment.tracking_code;
      await order.save();
    }
    return shipment;
  }

  const now = new Date();
  shipment = await Shipment.create({
    order_id: orderId,
    shop_id: shopId,
    tracking_code: buildTrackingCode(orderId),
    carrier: options.carrier || 'mock_carrier',
    status: 'requested',
    callback_url: options.callbackUrl || '/orders/shipping/callback',
    handed_over_at: null,
    metadata: {
      source: 'marketplace_shipping_request',
      requestedAt: now.toISOString(),
      ...(options.metadata || {})
    }
  });
  order.shipment_tracking_code = shipment.tracking_code;
  await order.save();
  return shipment;
}

async function markOrderDelivered(order, deliveredAt = new Date()) {
  const wasDelivered = order.status === 'delivered';
  const paymentMethod = String(order.payment_method || '').toLowerCase();
  const hasPlatformHeldFunds = ['wallet', 'bank_transfer', 'sepay'].includes(paymentMethod);
  const isCodOrder = paymentMethod === 'cod';
  order.status = 'delivered';
  order.delivered_at = order.delivered_at || deliveredAt;
  order.settlement_status = order.settlement_status === 'settled'
    ? 'settled'
    : (isCodOrder ? 'awaiting_cod_remittance' : (hasPlatformHeldFunds ? 'pending' : 'not_eligible'));
  order.settlement_eligible_at = hasPlatformHeldFunds
    ? (order.settlement_eligible_at || buildSettlementEligibleAt(order.delivered_at))
    : null;
  await order.save();
  if (!wasDelivered) {
    await publishOrderDelivered(order.toJSON());
  }
  return order;
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

function toInventoryItems(products) {
  const items = Array.isArray(products) ? products : [];
  return items.map((item) => ({
    productId: item.productId,
    variantId: item.variantId || null,
    quantity: item.quantity
  }));
}

async function sendInventoryCommand(path, payload) {
  const url = `${INVENTORY_SERVICE_URL}${path}`;
  const response = await fetchImpl(url, buildRequestOptions(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  }));
  if (!response.ok) {
    const text = await response.text();
    let message = text || `Inventory update failed with status ${response.status}`;
    try {
      message = JSON.parse(text).message || message;
    } catch {
      // keep raw response text
    }
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }
}

async function sendVoucherCommand(path, payload) {
  const url = `${VOUCHER_SERVICE_URL}${path}`;
  const response = await fetchImpl(url, buildRequestOptions(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  }));
  const text = await response.text();
  let data = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { message: text };
    }
  }
  if (!response.ok) {
    const error = new Error(data?.message || `Voucher update failed with status ${response.status}`);
    error.status = response.status;
    error.payload = data;
    throw error;
  }
  return data;
}

async function reserveStock(orderId, products) {
  const items = toInventoryItems(products);
  if (!items.length) return;
  await sendInventoryCommand('/inventory/reserve', { orderId, items });
}

async function releaseStock(orderId, options = {}) {
  if (!orderId) return;
  await sendInventoryCommand('/inventory/release', {
    orderId,
    restoreCommitted: Boolean(options.restoreCommitted)
  });
}

async function commitStock(orderId) {
  if (!orderId) return;
  await sendInventoryCommand('/inventory/commit', { orderId });
}

async function reserveVoucher(orderId, userId, code, products) {
  if (!code) return null;
  return sendVoucherCommand('/vouchers/reserve', {
    orderId,
    userId,
    code,
    items: products
  });
}

async function releaseVoucher(orderId, options = {}) {
  if (!orderId) return;
  await sendVoucherCommand('/vouchers/release', {
    orderId,
    restoreCommitted: Boolean(options.restoreCommitted)
  });
}

async function commitVoucher(orderId) {
  if (!orderId) return;
  await sendVoucherCommand('/vouchers/commit', { orderId });
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
  await releaseStock(order.id, { restoreCommitted: true });
  await releaseVoucher(order.id, { restoreCommitted: true });
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
    const { userId, products, shippingAddress, paymentMethod, voucherCode } = req.body;
    const idempotencyKey = normalizeIdempotencyKey(req.headers['idempotency-key']);
    const actorRole = req.headers['x-user-role'] || '';
    const actorUserId = req.headers['x-user-id'] || '';
    if (!userId || !Array.isArray(products)) {
      return res.status(400).json({ message: 'userId and products are required' });
    }
    if (actorRole === 'buyer' && String(userId) !== String(actorUserId)) {
      return res.status(403).json({ message: 'Forbidden' });
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
      ? buildIdempotencyHash({ userId, products, shippingAddress, paymentMethod, voucherCode: voucherCode || null })
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

    const subtotalPrice = calcTotal(products);
    let order;
    try {
      order = await Order.create({
        user_id: userId,
        products,
        subtotal_price: subtotalPrice,
        discount_amount: 0,
        total_price: subtotalPrice,
        voucher_code: voucherCode || null,
        voucher_snapshot: null,
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
      await reserveStock(order.id, products);
    } catch (err) {
      if (err?.status === 409) {
        await Order.destroy({ where: { id: order.id } });
        return res.status(409).json({ message: 'Out of stock' });
      }
      throw err;
    }
    try {
      const voucherResult = await reserveVoucher(order.id, userId, voucherCode, products);
      if (voucherResult) {
        const discountAmount = Math.min(toNumber(voucherResult.discountAmount), subtotalPrice);
        order.discount_amount = discountAmount;
        order.total_price = Math.max(subtotalPrice - discountAmount, 0);
        order.voucher_snapshot = voucherResult.voucher || null;
        await order.save();
      }
    } catch (err) {
      await cancelOrderWithCompensation(order, {
        reason: 'voucher_reserve_failed',
        shouldRefundToWallet: false
      });
      const status = err?.status === 409 || err?.status === 404 ? err.status : 502;
      return res.status(status).json({ message: err.message || 'Voucher is not available' });
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
    if (order.status === 'delivered') {
      return res.status(400).json({
        message: 'Delivered order cannot be cancelled. Please create a return/refund request.',
        refundRequired: true,
        status: order.status
      });
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
    if (order.status === 'payment_failed') {
      return res.status(400).json({ message: 'Payment failed for this order' });
    }
    const shopId = getPrimaryShopId(order.toJSON ? order.toJSON() : order);
    const actorShopId = req.headers['x-user-shop-id'] || req.headers['x-user-id'] || '';
    const actorRole = req.headers['x-user-role'] || '';
    if (actorRole === 'seller' && String(shopId) !== String(actorShopId)) {
      return res.status(403).json({ message: 'Forbidden' });
    }
    const isCodOrder = isCodPaymentMethod(order.payment_method);
    if (isCodOrder) {
      if (['pending_payment', 'payment_processing'].includes(order.status)) {
        await commitStock(order.id);
        await commitVoucher(order.id);
        order.status = 'confirmed';
        await order.save();
      }
      return res.json(order.toJSON());
    }
    if (order.status === 'pending_payment' || order.status === 'payment_processing') {
      return res.status(400).json({ message: 'Order payment is not completed yet' });
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

async function createShipment(req, res) {
  try {
    const id = Number(req.params.id);
    const order = await Order.findByPk(id);
    if (!order) {
      return res.status(404).json({ message: 'Order not found' });
    }
    if (['cancelled', 'payment_failed'].includes(order.status)) {
      return res.status(400).json({ message: 'Order cannot be shipped' });
    }
    if (!['confirmed', 'shipped'].includes(order.status)) {
      return res.status(400).json({ message: 'Order must be confirmed before shipping handoff' });
    }

    const shopId = getPrimaryShopId(order.toJSON ? order.toJSON() : order);
    const actorShopId = req.headers['x-user-shop-id'] || req.headers['x-user-id'] || '';
    const actorRole = req.headers['x-user-role'] || '';
    if (actorRole === 'seller' && String(shopId) !== String(actorShopId)) {
      return res.status(403).json({ message: 'Forbidden' });
    }

    const existingShipment = await Shipment.findOne({ where: { order_id: id } });
    const shipment = await ensureShipmentForOrder(order, req.body || {});
    const created = !existingShipment;
    return res.status(created ? 201 : 200).json({
      order: order.toJSON(),
      shipment: shipment.toJSON()
    });
  } catch (err) {
    return res.status(500).json({ message: 'Create shipment failed', error: err.message });
  }
}

async function getOrderShipment(req, res) {
  try {
    const orderId = Number(req.params.orderId);
    const order = await Order.findByPk(orderId);
    if (!order) return res.status(404).json({ message: 'Order not found' });

    const actorRole = req.headers['x-user-role'] || '';
    const actorUserId = req.headers['x-user-id'] || '';
    const actorShopId = req.headers['x-user-shop-id'] || actorUserId;
    const shopId = getPrimaryShopId(order.toJSON ? order.toJSON() : order);
    if (actorRole === 'buyer' && String(order.user_id) !== String(actorUserId)) {
      return res.status(403).json({ message: 'Forbidden' });
    }
    if (actorRole === 'seller' && String(shopId) !== String(actorShopId)) {
      return res.status(403).json({ message: 'Forbidden' });
    }

    const shipment = await Shipment.findOne({ where: { order_id: orderId } });
    if (!shipment) return res.status(404).json({ message: 'Shipment not found' });
    return res.json(shipment.toJSON());
  } catch (err) {
    return res.status(500).json({ message: 'Get shipment failed', error: err.message });
  }
}

async function applyShipmentStatus({ trackingCode, orderId, status, metadata = {}, deliveredAt = null }) {
  const nextStatus = String(status || '').toLowerCase();
  if (!SHIPMENT_STATUSES.has(nextStatus)) {
    const error = new Error('Invalid shipment status');
    error.status = 400;
    throw error;
  }

  const where = trackingCode ? { tracking_code: String(trackingCode) } : { order_id: Number(orderId) };
  const shipment = await Shipment.findOne({ where });
  if (!shipment) {
    const error = new Error('Shipment not found');
    error.status = 404;
    throw error;
  }

  const order = await Order.findByPk(shipment.order_id);
  if (!order) {
    const error = new Error('Order not found');
    error.status = 404;
    throw error;
  }

  shipment.status = nextStatus;
  shipment.metadata = { ...(shipment.metadata || {}), ...metadata };
  shipment.updated_at = new Date();
  if (nextStatus === 'handed_over') shipment.handed_over_at = shipment.handed_over_at || new Date();
  if (['picked_up', 'in_transit'].includes(nextStatus)) shipment.in_transit_at = shipment.in_transit_at || new Date();
  if (nextStatus === 'delivered') shipment.delivered_at = shipment.delivered_at || deliveredAt || new Date();
  await shipment.save();

  if (nextStatus === 'delivered') {
    await markOrderDelivered(order, shipment.delivered_at);
  } else if (['picked_up', 'in_transit'].includes(nextStatus) && order.status === 'confirmed') {
    order.status = 'shipped';
    order.shipment_tracking_code = shipment.tracking_code;
    await order.save();
  }

  return { order: order.toJSON(), shipment: shipment.toJSON() };
}

async function simulateShipmentStatus(req, res) {
  try {
    const result = await applyShipmentStatus({
      trackingCode: req.params.trackingCode,
      status: req.body?.status,
      metadata: { source: 'mock_carrier_simulation', ...(req.body?.metadata || {}) },
      deliveredAt: req.body?.deliveredAt ? new Date(req.body.deliveredAt) : null
    });
    return res.json(result);
  } catch (err) {
    return res.status(err.status || 500).json({ message: err.message || 'Simulate shipment failed' });
  }
}

async function receiveShippingCallback(req, res) {
  try {
    const result = await applyShipmentStatus({
      trackingCode: req.body?.trackingCode,
      orderId: req.body?.orderId,
      status: req.body?.status,
      metadata: {
        source: 'mock_carrier_callback',
        carrierPayload: req.body || {}
      },
      deliveredAt: req.body?.deliveredAt ? new Date(req.body.deliveredAt) : null
    });
    return res.json({ ok: true, ...result });
  } catch (err) {
    return res.status(err.status || 500).json({ message: err.message || 'Shipping callback failed' });
  }
}

async function getUserOrders(req, res) {
  try {
    const userId = req.params.userId || req.headers['x-user-id'];
    if (!userId) {
      return res.status(400).json({ message: 'userId is required' });
    }
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
    const nextStatus = String(status || '').toLowerCase();
    if (!ALLOWED_ORDER_STATUSES.has(nextStatus)) {
      return res.status(400).json({ message: 'Invalid status' });
    }
    const order = await Order.findByPk(id);
    if (!order) {
      return res.status(404).json({ message: 'Order not found' });
    }
    const currentStatus = String(order.status || '').toLowerCase();
    if (currentStatus === 'delivered' && nextStatus === 'cancelled') {
      return res.status(400).json({
        message: 'Delivered order cannot be cancelled. Please resolve a return/refund request instead.',
        refundRequired: true,
        status: order.status
      });
    }
    if (isCodPaymentMethod(order.payment_method)) {
      const allowedCodNextByCurrent = {
        pending_payment: new Set(['pending_payment', 'confirmed', 'cancelled', 'payment_failed']),
        payment_processing: new Set(['payment_processing', 'confirmed', 'cancelled', 'payment_failed']),
        confirmed: new Set(['confirmed', 'shipped', 'cancelled']),
        shipped: new Set(['shipped', 'delivered', 'cancelled']),
        delivered: new Set(['delivered']),
        paid: new Set(['paid', 'cancelled']),
        payment_failed: new Set(['payment_failed']),
        cancelled: new Set(['cancelled'])
      };
      const allowedSet = allowedCodNextByCurrent[currentStatus] || new Set([currentStatus]);
      if (!allowedSet.has(nextStatus)) {
        return res.status(400).json({
          message: 'Invalid COD status flow. Expected: pending_payment -> confirmed -> shipped -> delivered'
        });
      }
    }
    if (shouldCommitStockTransition(currentStatus, nextStatus)) {
      await Promise.all([commitStock(order.id), commitVoucher(order.id)]);
    }
    if (nextStatus === 'delivered') {
      await markOrderDelivered(order);
    } else {
      order.status = nextStatus;
      await order.save();
    }
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
    if (order.status === 'delivered') {
      return res.status(400).json({
        message: 'Delivered order cannot be cancelled. Please resolve a return/refund request instead.',
        refundRequired: true,
        status: order.status
      });
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
    if (order.status !== 'delivered') {
      return res.status(400).json({ message: 'Return/refund requests are only available for delivered orders' });
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
    const shouldQueueRefund = status === 'resolved';
    let refundOrder = null;
    let refundQueued = false;
    let refundRequired = false;
    let refundMessage = null;

    if (shouldQueueRefund) {
      refundOrder = await Order.findByPk(dispute.order_id);
      if (!refundOrder) {
        return res.status(404).json({ message: 'Order not found for dispute' });
      }
      if (refundOrder.status === 'refunded') {
        return res.json({
          ...dispute.toJSON(),
          refundRequired: false,
          refundQueued: false,
          refundMessage: 'Order is already refunded'
        });
      }
      if (!['delivered', 'refund_processing'].includes(refundOrder.status)) {
        return res.status(400).json({ message: 'Only delivered orders can be resolved as return/refund requests' });
      }
    }

    dispute.status = status;
    dispute.handled_by = req.headers['x-user-id'] || null;
    dispute.handled_note = typeof note === 'string' ? note : '';
    dispute.handled_at = new Date();
    await dispute.save();

    if (shouldQueueRefund) {
      refundRequired = true;
      if (isAutoRefundPaymentMethod(refundOrder.payment_method)) {
        await publishOrderRefundRequested({
          ...refundOrder.toJSON(),
          dispute_id: dispute.id,
          refund_reason: dispute.reason,
          refund_note: dispute.handled_note || dispute.note || null,
          shouldRefundToWallet: true
        });
        refundOrder.status = 'refund_processing';
        await refundOrder.save();
        refundQueued = true;
      } else {
        refundMessage = 'Manual refund is required for this payment method';
      }
    }

    return res.json({
      ...dispute.toJSON(),
      refundRequired,
      refundQueued,
      refundMessage
    });
  } catch (err) {
    return res.status(500).json({ message: 'Update dispute failed', error: err.message });
  }
}

async function handlePaymentRefunded(event) {
  const orderId = Number(event?.orderId);
  if (!Number.isFinite(orderId)) return;
  const order = await Order.findByPk(orderId);
  if (!order || order.status === 'cancelled') return;
  order.status = 'refunded';
  order.settlement_status = order.settlement_status === 'settled' ? 'settled' : 'not_eligible';
  await order.save();
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
  await Promise.all([commitStock(order.id), commitVoucher(order.id)]);
  order.status = 'paid';
  await order.save();
  await publishOrderPaid(order.toJSON());
}

async function handlePaymentFailed(event) {
  const orderId = Number(event?.orderId);
  if (!Number.isFinite(orderId)) return;
  const order = await Order.findByPk(orderId);
  if (!order || order.status === 'cancelled') return;
  if (['paid', 'confirmed', 'shipped', 'delivered', 'refund_processing', 'refunded'].includes(order.status)) return;
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
  if (['paid', 'confirmed', 'shipped', 'delivered', 'refund_processing', 'refunded'].includes(order.status)) return;
  order.status = 'payment_failed';
  await order.save();
  await cancelOrderWithCompensation(order, {
    reason: event?.reason || 'payment_timeout',
    shouldRefundToWallet: String(order.payment_method || '').toLowerCase() === 'wallet'
  });
}

async function handleShopSettlementCompleted(event) {
  const orderId = Number(event?.orderId);
  if (!Number.isFinite(orderId)) return;
  const order = await Order.findByPk(orderId);
  if (!order) return;
  order.settlement_status = 'settled';
  order.settled_at = event?.settledAt ? new Date(event.settledAt) : new Date();
  await order.save();
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
  createShipment,
  getOrderShipment,
  simulateShipmentStatus,
  receiveShippingCallback,
  createDispute,
  getAdminDisputes,
  updateAdminDispute,
  handlePaymentPending,
  handlePaymentSucceeded,
  handlePaymentFailed,
  handlePaymentTimeout,
  handlePaymentRefunded,
  handleShopSettlementCompleted
};
