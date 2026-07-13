const { Kafka } = require('kafkajs');
const { sequelize } = require('../config/db');
const { InboxEvent } = require('../models');
const {
  debitForOrder,
  refundOrderToWallet,
  topupWallet,
  recordExternalPaymentForOrder
} = require('../services/walletService');

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

  await consumer.run({
    eachMessage: async ({ topic, partition, message }) => {
      await withInbox(topic, partition, message, async (payload) => {
        if (topic === 'wallet.debit.requested') await handleWalletDebitRequested(payload);
        if (topic === 'wallet.refund.requested') await handleWalletRefundRequested(payload);
        if (topic === 'qr.payment.succeeded') await handleQrPaymentSucceeded(payload);
      });
    }
  });

  console.log('Wallet Service Kafka consumer running');
}

module.exports = { initConsumer };
