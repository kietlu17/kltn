const { Kafka } = require('kafkajs');
const { sequelize } = require('../config/db');
const { InboxEvent } = require('../models');
const {
  debitForOrder,
  refundOrderToWallet,
  topupWallet,
  recordExternalPaymentForOrder
} = require('../services/walletService');
const { settleOrderToShop, reverseOrderSettlement } = require('../services/shopFinanceService');

function buildMessageId(topic, partition, message, payload) {
  return String(payload?.eventId || payload?.idempotencyKey || `${topic}:${partition}:${message.offset}`);
}

async function withInbox(topic, partition, message, handler) {
  const payload = JSON.parse(message.value.toString());
  const messageId = buildMessageId(topic, partition, message, payload);
  const [inbox, created] = await InboxEvent.findOrCreate({
    where: { message_id: messageId },
    defaults: {
      message_id: messageId,
      topic,
      payload,
      status: 'processing',
      attempts: 1
    }
  });

  if (!created && inbox.status === 'processed') {
    console.log('[wallet-service] duplicate event skipped', { topic, messageId });
    return;
  }

  try {
    await handler(payload);
    inbox.status = 'processed';
    inbox.processed_at = new Date();
    inbox.error = null;
    await inbox.save();
  } catch (err) {
    inbox.status = 'failed';
    inbox.attempts += 1;
    inbox.error = err.message;
    await inbox.save();
    console.error('[wallet-service] consume failed', {
      topic,
      messageId,
      sagaId: payload?.sagaId,
      correlationId: payload?.correlationId,
      error: err.message
    });
    throw err;
  }
}

async function handleWalletDebitRequested(payload) {
  await debitForOrder({
    orderId: payload.orderId,
    userId: payload.userId,
    amount: payload.amount || payload.totalPrice,
    paymentMethod: payload.paymentMethod || 'wallet',
    sagaId: payload.sagaId,
    correlationId: payload.correlationId
  });
}

async function handleWalletRefundRequested(payload) {
  const orderId = Number(payload.orderId);
  const settlementByShop = new Map();
  for (const item of parseOrderItems(payload)) {
    if (!item?.shopId) continue;
    const shopId = String(item.shopId);
    const lineAmount = toMoney(Number(item.price || 0) * Number(item.quantity || 0));
    settlementByShop.set(shopId, toMoney((settlementByShop.get(shopId) || 0) + lineAmount));
  }

  for (const [shopId, amount] of settlementByShop.entries()) {
    if (amount <= 0 || !Number.isFinite(orderId)) continue;
    await reverseOrderSettlement({
      shopId,
      orderId,
      amount,
      reason: payload.reason || 'order_cancelled',
      metadata: { source: 'wallet.refund.requested' },
      sagaId: payload.sagaId,
      correlationId: payload.correlationId
    });
  }

  await refundOrderToWallet({
    orderId: payload.orderId,
    userId: payload.userId,
    amount: payload.amount || payload.totalPrice,
    reason: payload.reason,
    allowWithoutDebit: Boolean(payload.allowWithoutDebit),
    sagaId: payload.sagaId,
    correlationId: payload.correlationId
  });
}

async function handleQrPaymentSucceeded(payload) {
  if (payload.purpose === 'wallet_topup') {
    await topupWallet(
      payload.userId,
      payload.amount,
      {
        source: 'qr_payment_succeeded',
        requestCode: payload.requestCode,
        gatewayTransactionId: payload.gatewayTransactionId || null
      },
      {
        idempotencyKey: `qr:wallet:${payload.requestCode || payload.requestId}`,
        reason: 'qr_topup',
        sagaId: payload.sagaId,
        correlationId: payload.correlationId
      }
    );
    return;
  }

  if (payload.purpose === 'order_payment') {
    await recordExternalPaymentForOrder({
      orderId: payload.orderId,
      userId: payload.userId,
      amount: payload.amount,
      paymentMethod: 'bank_transfer',
      metadata: {
        requestCode: payload.requestCode,
        requestId: payload.requestId,
        gatewayTransactionId: payload.gatewayTransactionId || null
      },
      sagaId: payload.sagaId,
      correlationId: payload.correlationId
    });
  }
}

function parseOrderItems(payload) {
  if (Array.isArray(payload?.products)) return payload.products;
  if (typeof payload?.products === 'string') {
    try {
      return JSON.parse(payload.products);
    } catch (err) {
      return [];
    }
  }
  return [];
}

function toMoney(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return 0;
  return Number(number.toFixed(2));
}

async function handleOrderPaid(payload) {
  const orderId = Number(payload?.id || payload?.orderId);
  if (!Number.isFinite(orderId)) return;

  const settlementByShop = new Map();
  for (const item of parseOrderItems(payload)) {
    if (!item?.shopId) continue;
    const shopId = String(item.shopId);
    const lineAmount = toMoney(Number(item.price || 0) * Number(item.quantity || 0));
    settlementByShop.set(shopId, toMoney((settlementByShop.get(shopId) || 0) + lineAmount));
  }

  for (const [shopId, amount] of settlementByShop.entries()) {
    if (amount <= 0) continue;
    await settleOrderToShop({
      shopId,
      orderId,
      amount,
      referenceId: `order:${orderId}:shop:${shopId}:settlement`,
      metadata: {
        paymentMethod: payload.payment_method || payload.paymentMethod,
        source: 'order.paid'
      },
      sagaId: payload.sagaId || `order:${orderId}:settlement`,
      correlationId: payload.correlationId || `order:${orderId}:settlement`
    });
  }
}

async function initConsumer() {
  const kafka = new Kafka({
    clientId: 'wallet-service-consumer',
    brokers: [process.env.KAFKA_BROKER || 'localhost:9092']
  });

  const consumer = kafka.consumer({ groupId: 'wallet-group' });
  await consumer.connect();
  await consumer.subscribe({ topic: 'wallet.debit.requested' });
  await consumer.subscribe({ topic: 'wallet.refund.requested' });
  await consumer.subscribe({ topic: 'qr.payment.succeeded' });
  await consumer.subscribe({ topic: 'order.paid' });

  await consumer.run({
    eachMessage: async ({ topic, partition, message }) => {
      await withInbox(topic, partition, message, async (payload) => {
        if (topic === 'wallet.debit.requested') await handleWalletDebitRequested(payload);
        if (topic === 'wallet.refund.requested') await handleWalletRefundRequested(payload);
        if (topic === 'qr.payment.succeeded') await handleQrPaymentSucceeded(payload);
        if (topic === 'order.paid') await handleOrderPaid(payload);
      });
    }
  });

  console.log('Wallet Service Kafka consumer running');
}

module.exports = { initConsumer };
