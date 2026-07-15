const { Kafka } = require('kafkajs');
const { sequelize } = require('../config/db');
const { InboxEvent } = require('../models');
const { publishPaymentEvent, enqueueEvent } = require('./producer');

const BANK_TRANSFER_DELAY_MS = Number(process.env.BANK_TRANSFER_DELAY_MS || 3000);
const BANK_TRANSFER_TIMEOUT_MS = Number(process.env.BANK_TRANSFER_TIMEOUT_MS || 10000);
const BANK_TRANSFER_PAYMENT_WINDOW_MS = Number(process.env.BANK_TRANSFER_PAYMENT_WINDOW_MS || 5 * 60 * 1000);
const SEPAY_ENABLED = String(process.env.SEPAY_ENABLED || '').toLowerCase() === 'true';
const paymentOutcome = new Map();

function normalizeOrder(payload) {
  const orderId = Number(payload?.id || payload?.orderId);
  const userId = payload?.user_id || payload?.userId;
  const totalPrice = Number(payload?.total_price || payload?.totalPrice || payload?.amount || 0);
  const paymentMethod = String(payload?.payment_method || payload?.paymentMethod || '').toLowerCase();
  const sagaId = payload?.sagaId || (Number.isFinite(orderId) ? `order:${orderId}:payment` : undefined);
  const correlationId = payload?.correlationId || sagaId;
  return { orderId, userId, totalPrice, paymentMethod, sagaId, correlationId };
}

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
    console.log('[payment-service] duplicate event skipped', { topic, messageId });
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
    console.error('[payment-service] consume failed', {
      topic,
      messageId,
      sagaId: payload?.sagaId,
      correlationId: payload?.correlationId,
      error: err.message
    });
    throw err;
  }
}

async function enqueuePaymentFailed(transaction, payload, reason) {
  await publishPaymentEvent(
    'payment.failed',
    {
      orderId: payload.orderId,
      status: 'payment_failed',
      paymentMethod: payload.paymentMethod,
      reason,
      userId: payload.userId || null,
      totalPrice: payload.totalPrice,
      sagaId: payload.sagaId,
      correlationId: payload.correlationId
    },
    {
      transaction,
      eventType: 'PaymentFailed',
      key: payload.orderId,
      aggregateId: payload.orderId
    }
  );
}

async function handleOrderCreated(payload) {
  const normalized = normalizeOrder(payload);
  const { orderId, paymentMethod: method } = normalized;
  if (!Number.isFinite(orderId)) return;

  if (method === 'wallet') {
    await sequelize.transaction(async (transaction) => {
      if (!normalized.userId) {
        await enqueuePaymentFailed(transaction, normalized, 'missing_user_id');
        return;
      }
      await enqueueEvent({
        transaction,
        topic: 'wallet.debit.requested',
        eventType: 'WalletDebitRequested',
        key: orderId,
        aggregateId: orderId,
        payload: {
          orderId,
          userId: normalized.userId,
          amount: normalized.totalPrice,
          totalPrice: normalized.totalPrice,
          paymentMethod: method,
          sagaId: normalized.sagaId,
          correlationId: normalized.correlationId
        }
      });
    });
    return;
  }

  if (method === 'bank_transfer') {
    await sequelize.transaction(async (transaction) => {
      await publishPaymentEvent(
        'payment.pending',
        {
          orderId,
          status: 'payment_processing',
          paymentMethod: method,
          userId: normalized.userId || null,
          totalPrice: normalized.totalPrice,
          sagaId: normalized.sagaId,
          correlationId: normalized.correlationId
        },
        {
          transaction,
          eventType: 'PaymentPending',
          key: orderId,
          aggregateId: orderId
        }
      );
    });

    paymentOutcome.set(orderId, 'pending');
    if (SEPAY_ENABLED) {
      setTimeout(async () => {
        try {
          if (paymentOutcome.get(orderId) !== 'pending') return;
          paymentOutcome.set(orderId, 'timed_out');
          await handleQrPaymentExpired({
            ...normalized,
            purpose: 'order_payment',
            reason: 'payment_window_expired'
          });
          paymentOutcome.delete(orderId);
        } catch (err) {
          console.error('Publish payment window timeout failed', err.message);
        }
      }, BANK_TRANSFER_PAYMENT_WINDOW_MS);
      return;
    }

    setTimeout(async () => {
      try {
        const shouldFail = String(process.env.BANK_TRANSFER_SHOULD_FAIL || '').toLowerCase() === 'true';
        const shouldTimeout = String(process.env.BANK_TRANSFER_SHOULD_TIMEOUT || '').toLowerCase() === 'true';
        if (paymentOutcome.get(orderId) !== 'pending') return;
        if (shouldTimeout) {
          paymentOutcome.set(orderId, 'timed_out');
          await handleQrPaymentExpired({
            ...normalized,
            reason: 'payment_timeout'
          });
          paymentOutcome.delete(orderId);
          return;
        }
        if (shouldFail) {
          paymentOutcome.set(orderId, 'failed');
          await handleQrPaymentFailed({
            ...normalized,
            reason: 'bank_transfer_failed'
          });
          paymentOutcome.delete(orderId);
          return;
        }
        paymentOutcome.set(orderId, 'succeeded');
        await handleQrPaymentSucceeded({
          purpose: 'order_payment',
          orderId,
          userId: normalized.userId,
          amount: normalized.totalPrice,
          sagaId: normalized.sagaId,
          correlationId: normalized.correlationId
        });
        paymentOutcome.delete(orderId);
      } catch (err) {
        console.error('Async bank transfer handling failed', err.message);
      }
    }, BANK_TRANSFER_DELAY_MS);

    setTimeout(async () => {
      try {
        if (paymentOutcome.get(orderId) !== 'pending') return;
        paymentOutcome.set(orderId, 'timed_out');
        await handleQrPaymentExpired({
          ...normalized,
          reason: 'payment_timeout'
        });
        paymentOutcome.delete(orderId);
      } catch (err) {
        console.error('Publish timeout event failed', err.message);
      }
    }, BANK_TRANSFER_TIMEOUT_MS);
    return;
  }

  if (method === 'cod') return;

  await sequelize.transaction(async (transaction) => {
    await enqueuePaymentFailed(transaction, normalized, 'unsupported_payment_method');
  });
}

async function handleOrderCancelled(payload) {
  const normalized = normalizeOrder(payload);
  if (!Number.isFinite(normalized.orderId) || !normalized.userId) return;
  const shouldRefundToWallet = Boolean(payload?.shouldRefundToWallet);
  if (!shouldRefundToWallet) return;
  const cancelReason = String(payload?.cancel_reason || payload?.reason || 'order_cancelled');

  await sequelize.transaction(async (transaction) => {
    await enqueueEvent({
      transaction,
      topic: 'wallet.refund.requested',
      eventType: 'WalletRefundRequested',
      key: normalized.orderId,
      aggregateId: normalized.orderId,
      payload: {
        orderId: normalized.orderId,
        userId: normalized.userId,
        amount: normalized.totalPrice,
        totalPrice: normalized.totalPrice,
        paymentMethod: normalized.paymentMethod,
        products: payload.products || [],
        reason: cancelReason,
        allowWithoutDebit: normalized.paymentMethod === 'bank_transfer',
        sagaId: normalized.sagaId,
        correlationId: normalized.correlationId
      }
    });
  });
}

async function handleWalletDebited(payload) {
  await sequelize.transaction(async (transaction) => {
    await publishPaymentEvent(
      'payment.succeeded',
      {
        orderId: Number(payload.orderId),
        status: 'paid',
        paymentMethod: payload.paymentMethod || 'wallet',
        userId: payload.userId || null,
        totalPrice: Number(payload.amount || 0),
        walletDebited: true,
        debitTransactionId: payload.transactionId || null,
        sagaId: payload.sagaId,
        correlationId: payload.correlationId
      },
      {
        transaction,
        eventType: 'PaymentSucceeded',
        key: payload.orderId,
        aggregateId: payload.orderId
      }
    );
  });
}

async function handleWalletDebitFailed(payload) {
  await sequelize.transaction(async (transaction) => {
    await publishPaymentEvent(
      'payment.failed',
      {
        orderId: Number(payload.orderId),
        status: 'payment_failed',
        paymentMethod: payload.paymentMethod || 'wallet',
        reason: payload.reason || 'wallet_debit_failed',
        userId: payload.userId || null,
        totalPrice: Number(payload.amount || 0),
        sagaId: payload.sagaId,
        correlationId: payload.correlationId
      },
      {
        transaction,
        eventType: 'PaymentFailed',
        key: payload.orderId,
        aggregateId: payload.orderId
      }
    );
  });
}

async function handleWalletRefunded(payload) {
  await sequelize.transaction(async (transaction) => {
    await publishPaymentEvent(
      'payment.refunded',
      {
        orderId: Number(payload.orderId),
        userId: payload.userId || null,
        status: 'refunded',
        amount: Number(payload.amount || 0),
        reason: payload.reason || 'order_cancelled',
        sagaId: payload.sagaId,
        correlationId: payload.correlationId
      },
      {
        transaction,
        eventType: 'PaymentRefunded',
        key: payload.orderId,
        aggregateId: payload.orderId
      }
    );
  });
}

async function handleQrPaymentSucceeded(payload) {
  if (payload.purpose !== 'order_payment' || !payload.orderId) return;
  paymentOutcome.set(Number(payload.orderId), 'succeeded');
  await sequelize.transaction(async (transaction) => {
    await publishPaymentEvent(
      'payment.succeeded',
      {
        orderId: Number(payload.orderId),
        status: 'paid',
        paymentMethod: 'bank_transfer',
        userId: payload.userId || null,
        totalPrice: Number(payload.amount || 0),
        walletDebited: false,
        qrRequestId: payload.requestId || null,
        requestCode: payload.requestCode || null,
        sagaId: payload.sagaId,
        correlationId: payload.correlationId
      },
      {
        transaction,
        eventType: 'PaymentSucceeded',
        key: payload.orderId,
        aggregateId: payload.orderId
      }
    );
  });
  paymentOutcome.delete(Number(payload.orderId));
}

async function handleQrPaymentFailed(payload) {
  if (payload.purpose && payload.purpose !== 'order_payment') return;
  const normalized = normalizeOrder(payload);
  if (!Number.isFinite(normalized.orderId)) return;
  paymentOutcome.set(normalized.orderId, 'failed');
  await sequelize.transaction(async (transaction) => {
    await enqueuePaymentFailed(transaction, normalized, payload.reason || 'qr_payment_failed');
  });
  paymentOutcome.delete(normalized.orderId);
}

async function handleQrPaymentExpired(payload) {
  if (payload.purpose && payload.purpose !== 'order_payment') return;
  const normalized = normalizeOrder(payload);
  if (!Number.isFinite(normalized.orderId)) return;
  paymentOutcome.set(normalized.orderId, 'timed_out');
  await sequelize.transaction(async (transaction) => {
    await publishPaymentEvent(
      'payment.timeout',
      {
        orderId: normalized.orderId,
        status: 'payment_timeout',
        paymentMethod: normalized.paymentMethod || 'bank_transfer',
        reason: payload.reason || 'payment_window_expired',
        userId: normalized.userId || null,
        totalPrice: normalized.totalPrice,
        sagaId: normalized.sagaId,
        correlationId: normalized.correlationId
      },
      {
        transaction,
        eventType: 'PaymentTimedOut',
        key: normalized.orderId,
        aggregateId: normalized.orderId
      }
    );
  });
  paymentOutcome.delete(normalized.orderId);
}

async function initConsumer() {
  const kafka = new Kafka({
    clientId: 'payment-service-consumer',
    brokers: [process.env.KAFKA_BROKER || 'localhost:9092']
  });

  const consumer = kafka.consumer({ groupId: 'payment-group' });
  await consumer.connect();
  await consumer.subscribe({ topic: 'order.created' });
  await consumer.subscribe({ topic: 'order.cancelled' });
  await consumer.subscribe({ topic: 'wallet.debited' });
  await consumer.subscribe({ topic: 'wallet.debit_failed' });
  await consumer.subscribe({ topic: 'wallet.refunded' });
  await consumer.subscribe({ topic: 'qr.payment.succeeded' });
  await consumer.subscribe({ topic: 'qr.payment.failed' });
  await consumer.subscribe({ topic: 'qr.payment.expired' });

  await consumer.run({
    eachMessage: async ({ topic, partition, message }) => {
      await withInbox(topic, partition, message, async (payload) => {
        if (topic === 'order.created') await handleOrderCreated(payload);
        if (topic === 'order.cancelled') await handleOrderCancelled(payload);
        if (topic === 'wallet.debited') await handleWalletDebited(payload);
        if (topic === 'wallet.debit_failed') await handleWalletDebitFailed(payload);
        if (topic === 'wallet.refunded') await handleWalletRefunded(payload);
        if (topic === 'qr.payment.succeeded') await handleQrPaymentSucceeded(payload);
        if (topic === 'qr.payment.failed') await handleQrPaymentFailed(payload);
        if (topic === 'qr.payment.expired') await handleQrPaymentExpired(payload);
      });
    }
  });

  console.log('Payment Service Kafka consumer running');
}

module.exports = { initConsumer };
