const crypto = require('crypto');
const { Op, UniqueConstraintError } = require('sequelize');
const { sequelize } = require('../config/db');
const { SepayPaymentRequest, SepayWebhookLog, OutboxEvent } = require('../models');

function toMoney(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return 0;
  return Number(number.toFixed(2));
}

function normalizeAmount(amount) {
  return Math.round(toMoney(amount));
}

function getSepayConfig() {
  const bankCode = String(process.env.SEPAY_BANK_CODE || '').trim();
  const accountNumber = String(process.env.SEPAY_ACCOUNT_NUMBER || '').trim();
  const accountName = String(process.env.SEPAY_ACCOUNT_NAME || '').trim();
  const qrBaseUrl = String(process.env.SEPAY_QR_BASE_URL || 'https://qr.sepay.vn/img').trim();
  const webhookApiKey = String(process.env.SEPAY_WEBHOOK_API_KEY || '').trim();
  const enabled = String(process.env.SEPAY_ENABLED || '').toLowerCase() === 'true';
  return { enabled, bankCode, accountNumber, accountName, qrBaseUrl, webhookApiKey };
}

function assertSepayConfig() {
  const config = getSepayConfig();
  if (!config.enabled) {
    const err = new Error('SePay is disabled. Set SEPAY_ENABLED=true');
    err.status = 503;
    throw err;
  }
  if (!config.bankCode || !config.accountNumber) {
    const err = new Error('Missing SEPAY_BANK_CODE or SEPAY_ACCOUNT_NUMBER');
    err.status = 400;
    throw err;
  }
  return config;
}

function generateRequestCode(prefix) {
  const rand = crypto.randomBytes(4).toString('hex').toUpperCase();
  const time = Date.now().toString(36).toUpperCase();
  return `${prefix}${time}${rand}`.slice(0, 80);
}

function buildQrUrl({ qrBaseUrl, accountNumber, bankCode, amount, description }) {
  const url = new URL(qrBaseUrl);
  url.searchParams.set('acc', accountNumber);
  url.searchParams.set('bank', bankCode);
  if (Number.isFinite(amount) && amount > 0) url.searchParams.set('amount', String(Math.round(amount)));
  url.searchParams.set('des', description);
  return url.toString();
}

function getExpiryDate() {
  const ttlMs = Number(process.env.QR_PAYMENT_WINDOW_MS || 5 * 60 * 1000);
  return new Date(Date.now() + ttlMs);
}

function toPublicRequest(row) {
  const value = row?.toJSON ? row.toJSON() : row;
  return {
    id: value.id,
    requestCode: value.request_code,
    purpose: value.purpose,
    userId: value.user_id,
    orderId: value.order_id,
    amount: Number(value.amount || 0),
    bankCode: value.bank_code,
    accountNumber: value.account_number,
    accountName: value.account_name || '',
    qrUrl: value.qr_url,
    status: value.status,
    paidAt: value.paid_at || null,
    expiresAt: value.expires_at || null,
    createdAt: value.created_at || null,
    sagaId: value.saga_id || null,
    correlationId: value.correlation_id || null
  };
}

async function enqueueQrEvent(transaction, request, eventType, topic, extra = {}) {
  const publicRequest = toPublicRequest(request);
  const payload = {
    eventId: `${eventType}:${request.request_code}:${extra.gatewayTransactionId || request.updated_at?.getTime?.() || Date.now()}`,
    eventType,
    requestId: request.id,
    requestCode: request.request_code,
    purpose: request.purpose,
    userId: request.user_id,
    orderId: request.order_id,
    amount: Number(request.amount || 0),
    paymentMethod: 'bank_transfer',
    status: request.status,
    sagaId: request.saga_id || null,
    correlationId: request.correlation_id || null,
    occurredAt: new Date().toISOString(),
    request: publicRequest,
    ...extra
  };

  await OutboxEvent.create(
    {
      aggregate_type: 'sepay_payment_request',
      aggregate_id: String(request.id),
      event_type: eventType,
      topic,
      event_key: String(request.order_id || request.user_id || request.request_code),
      payload,
      headers: {
        sagaId: request.saga_id || '',
        correlationId: request.correlation_id || ''
      },
      saga_id: request.saga_id || null,
      correlation_id: request.correlation_id || null
    },
    { transaction }
  );
}

async function createSepayTopupRequest({ userId, amount, correlationId }) {
  const config = assertSepayConfig();
  const normalizedAmount = normalizeAmount(amount);
  if (!Number.isFinite(normalizedAmount) || normalizedAmount <= 0) throw new Error('amount must be greater than 0');

  const requestCode = generateRequestCode('TOPUP');
  const qrUrl = buildQrUrl({
    qrBaseUrl: config.qrBaseUrl,
    accountNumber: config.accountNumber,
    bankCode: config.bankCode,
    amount: normalizedAmount,
    description: requestCode
  });

  const created = await SepayPaymentRequest.create({
    request_code: requestCode,
    purpose: 'wallet_topup',
    user_id: String(userId),
    order_id: null,
    amount: normalizedAmount,
    bank_code: config.bankCode,
    account_number: config.accountNumber,
    account_name: config.accountName || null,
    qr_url: qrUrl,
    status: 'pending',
    expires_at: getExpiryDate(),
    metadata: {},
    correlation_id: correlationId || null
  });
  return toPublicRequest(created);
}

async function createSepayOrderRequest({ orderId, userId, amount, correlationId }) {
  const config = assertSepayConfig();
  const normalizedOrderId = Number(orderId);
  const normalizedAmount = normalizeAmount(amount);
  if (!Number.isFinite(normalizedOrderId)) throw new Error('orderId is invalid');
  if (!Number.isFinite(normalizedAmount) || normalizedAmount <= 0) throw new Error('amount must be greater than 0');

  const existing = await SepayPaymentRequest.findOne({
    where: {
      purpose: 'order_payment',
      order_id: normalizedOrderId,
      status: { [Op.in]: ['pending', 'paid'] }
    },
    order: [['id', 'DESC']]
  });
  if (existing) {
    if (String(existing.user_id) !== String(userId)) {
      const err = new Error('Order payment request belongs to another user');
      err.status = 403;
      throw err;
    }
    return toPublicRequest(existing);
  }

  const sagaId = `order:${normalizedOrderId}:payment`;
  const requestCode = generateRequestCode(`ORD${normalizedOrderId}`);
  const qrUrl = buildQrUrl({
    qrBaseUrl: config.qrBaseUrl,
    accountNumber: config.accountNumber,
    bankCode: config.bankCode,
    amount: normalizedAmount,
    description: requestCode
  });
  const created = await SepayPaymentRequest.create({
    request_code: requestCode,
    purpose: 'order_payment',
    user_id: String(userId),
    order_id: normalizedOrderId,
    amount: normalizedAmount,
    bank_code: config.bankCode,
    account_number: config.accountNumber,
    account_name: config.accountName || null,
    qr_url: qrUrl,
    status: 'pending',
    expires_at: getExpiryDate(),
    metadata: {},
    saga_id: sagaId,
    correlation_id: correlationId || sagaId
  });
  return toPublicRequest(created);
}

async function getSepayRequestById(id) {
  const row = await SepayPaymentRequest.findByPk(Number(id));
  if (!row) return null;
  return toPublicRequest(row);
}

function parseAuthorizationHeader(value) {
  if (!value) return '';
  return String(value).trim();
}

function collectRequestCodeCandidates(payload) {
  const candidates = new Set();
  const directCode = String(payload?.code || '').trim();
  if (directCode) candidates.add(directCode);

  const sourceTexts = [payload?.content, payload?.description, payload?.referenceCode]
    .map((value) => String(value || '').trim())
    .filter(Boolean);

  sourceTexts.forEach((text) => {
    const tokens = text.match(/[A-Z0-9]{8,80}/g) || [];
    tokens.forEach((token) => {
      if (token.startsWith('ORD') || token.startsWith('TOPUP')) candidates.add(token);
    });
  });

  return Array.from(candidates);
}

async function markRequestFailed(request, reason, metadata = {}) {
  return sequelize.transaction(async (transaction) => {
    const locked = await SepayPaymentRequest.findByPk(request.id, {
      transaction,
      lock: transaction.LOCK.UPDATE
    });
    if (!locked || locked.status !== 'pending') return locked || request;
    locked.status = 'failed';
    locked.metadata = {
      ...(locked.metadata || {}),
      failure: { reason, ...metadata }
    };
    await locked.save({ transaction });
    await enqueueQrEvent(transaction, locked, 'QRPaymentFailed', 'qr.payment.failed', { reason });
    return locked;
  });
}

async function processSepayWebhook(payload, headers = {}) {
  const config = assertSepayConfig();
  const expectedKey = config.webhookApiKey;
  if (!expectedKey) {
    const err = new Error('Missing SEPAY_WEBHOOK_API_KEY');
    err.status = 503;
    throw err;
  }
  const authHeader = parseAuthorizationHeader(headers.authorization || headers.Authorization);
  if (authHeader !== `Apikey ${expectedKey}`) {
    const err = new Error('Unauthorized webhook');
    err.status = 401;
    throw err;
  }

  const transactionId = payload?.id != null ? String(payload.id) : '';
  if (!transactionId) {
    const err = new Error('Webhook payload is missing id');
    err.status = 400;
    throw err;
  }

  const requestCodeCandidates = collectRequestCodeCandidates(payload);
  const requestCode = requestCodeCandidates[0] || '';
  const transferType = String(payload?.transferType || '').trim().toLowerCase();
  const transferAmount = toMoney(payload?.transferAmount || 0);

  let duplicate = false;
  try {
    await SepayWebhookLog.create({
      sepay_transaction_id: transactionId,
      request_code: requestCode || null,
      transfer_type: transferType || null,
      transfer_amount: transferAmount || 0,
      payload: payload || {}
    });
  } catch (err) {
    if (err instanceof UniqueConstraintError) duplicate = true;
    else throw err;
  }

  if (!requestCodeCandidates.length || transferType !== 'in') return { duplicate, handled: true, matched: false };

  const request = await SepayPaymentRequest.findOne({
    where: { request_code: { [Op.in]: requestCodeCandidates } }
  });
  if (!request) return { duplicate, handled: true, matched: false };

  const requiredAmount = toMoney(request.amount);
  if (transferAmount < requiredAmount) {
    const failed = await markRequestFailed(request, 'insufficient_amount', { transferAmount });
    return {
      duplicate,
      handled: true,
      matched: true,
      paid: false,
      reason: 'insufficient_amount',
      request: toPublicRequest(failed)
    };
  }

  if (request.status === 'paid') {
    return { handled: true, duplicate, matched: true, paid: true, request: toPublicRequest(request) };
  }
  if (request.status !== 'pending') {
    return { handled: true, duplicate, matched: true, paid: false, reason: request.status, request: toPublicRequest(request) };
  }

  const refreshed = await sequelize.transaction(async (transaction) => {
    const locked = await SepayPaymentRequest.findByPk(request.id, {
      transaction,
      lock: transaction.LOCK.UPDATE
    });
    if (!locked || locked.status !== 'pending') return locked;
    locked.status = 'paid';
    locked.paid_at = new Date();
    locked.sepay_transaction_id = transactionId;
    locked.metadata = {
      ...(locked.metadata || {}),
      webhook: {
        transferAmount,
        transferType,
        referenceCode: payload?.referenceCode || null,
        gateway: payload?.gateway || null
      }
    };
    await locked.save({ transaction });
    await enqueueQrEvent(transaction, locked, 'QRPaymentSucceeded', 'qr.payment.succeeded', {
      gatewayTransactionId: transactionId,
      transferAmount
    });
    return locked;
  });

  return { handled: true, duplicate, matched: true, paid: true, request: toPublicRequest(refreshed) };
}

async function expirePendingRequests() {
  const now = new Date();
  const rows = await SepayPaymentRequest.findAll({
    where: {
      status: 'pending',
      expires_at: { [Op.lte]: now }
    },
    limit: Number(process.env.QR_EXPIRY_BATCH_SIZE || 50)
  });

  for (const row of rows) {
    await sequelize.transaction(async (transaction) => {
      const locked = await SepayPaymentRequest.findByPk(row.id, {
        transaction,
        lock: transaction.LOCK.UPDATE
      });
      if (!locked || locked.status !== 'pending') return;
      locked.status = 'expired';
      await locked.save({ transaction });
      await enqueueQrEvent(transaction, locked, 'QRPaymentExpired', 'qr.payment.expired', {
        reason: 'payment_window_expired'
      });
    });
  }
}

function initExpiryPublisher() {
  const intervalMs = Number(process.env.QR_EXPIRY_POLL_INTERVAL_MS || 30000);
  const timer = setInterval(() => {
    expirePendingRequests().catch((err) => {
      console.error('[payment-gateway] expire pending QR failed', err.message);
    });
  }, intervalMs);
  timer.unref?.();
}

module.exports = {
  getSepayConfig,
  createSepayTopupRequest,
  createSepayOrderRequest,
  getSepayRequestById,
  processSepayWebhook,
  expirePendingRequests,
  initExpiryPublisher
};
