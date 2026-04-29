const { Kafka } = require('kafkajs');
const { publishPaymentEvent } = require('./producer');
const { debitForOrder, refundOrderToWallet } = require('../services/walletService');

const BANK_TRANSFER_DELAY_MS = Number(process.env.BANK_TRANSFER_DELAY_MS || 3000);
const BANK_TRANSFER_TIMEOUT_MS = Number(process.env.BANK_TRANSFER_TIMEOUT_MS || 10000);
const paymentOutcome = new Map();

function normalizeOrder(payload) {
  const orderId = Number(payload?.id || payload?.orderId);
  const userId = payload?.user_id || payload?.userId;
  const totalPrice = Number(payload?.total_price || payload?.totalPrice || 0);
  const paymentMethod = String(payload?.payment_method || payload?.paymentMethod || '').toLowerCase();
  return { orderId, userId, totalPrice, paymentMethod };
}

async function publishPaymentFailed(payload, reason) {
  await publishPaymentEvent('payment.failed', {
    orderId: payload.orderId,
    status: 'payment_failed',
    paymentMethod: payload.paymentMethod,
    reason,
    userId: payload.userId || null,
    totalPrice: payload.totalPrice,
    eventAt: new Date().toISOString()
  });
}

async function handleOrderCreated(payload) {
  const normalized = normalizeOrder(payload);
  const { orderId } = normalized;
  const method = normalized.paymentMethod;
  if (!Number.isFinite(orderId)) return;

  if (method === 'wallet') {
    if (!normalized.userId) {
      await publishPaymentFailed(normalized, 'missing_user_id');
      return;
    }
    const debit = await debitForOrder({
      orderId,
      userId: normalized.userId,
      amount: normalized.totalPrice,
      paymentMethod: method
    });
    if (!debit.ok) {
      await publishPaymentFailed(normalized, debit.reason || 'wallet_debit_failed');
      return;
    }
    try {
      await publishPaymentEvent('payment.succeeded', {
        orderId,
        status: 'paid',
        paymentMethod: method,
        userId: normalized.userId || null,
        totalPrice: normalized.totalPrice,
        walletDebited: true,
        debitTransactionId: debit.transaction?.id || null,
        eventAt: new Date().toISOString()
      });
    } catch (err) {
      // Saga compensation: rollback wallet debit if success event cannot be published.
      await refundOrderToWallet({
        orderId,
        userId: normalized.userId,
        amount: normalized.totalPrice,
        reason: 'payment_event_publish_failed',
        allowWithoutDebit: false
      });
      await publishPaymentFailed(normalized, 'payment_event_publish_failed');
    }
    return;
  }

  if (method === 'bank_transfer') {
    await publishPaymentEvent('payment.pending', {
      orderId,
      status: 'payment_processing',
      paymentMethod: method,
      userId: normalized.userId || null,
      totalPrice: normalized.totalPrice,
      eventAt: new Date().toISOString()
    });

    paymentOutcome.set(orderId, 'pending');

    setTimeout(async () => {
      try {
        const shouldFail = String(process.env.BANK_TRANSFER_SHOULD_FAIL || '').toLowerCase() === 'true';
        const shouldTimeout = String(process.env.BANK_TRANSFER_SHOULD_TIMEOUT || '').toLowerCase() === 'true';
        if (paymentOutcome.get(orderId) !== 'pending') return;
        if (shouldTimeout) {
          paymentOutcome.set(orderId, 'timed_out');
          await publishPaymentEvent('payment.timeout', {
            orderId,
            status: 'payment_timeout',
            paymentMethod: method,
            reason: 'payment_timeout',
            userId: normalized.userId || null,
            totalPrice: normalized.totalPrice,
            eventAt: new Date().toISOString()
          });
          paymentOutcome.delete(orderId);
          return;
        }
        if (shouldFail) {
          paymentOutcome.set(orderId, 'failed');
          await publishPaymentEvent('payment.failed', {
            orderId,
            status: 'payment_failed',
            paymentMethod: method,
            reason: 'bank_transfer_failed',
            userId: normalized.userId || null,
            totalPrice: normalized.totalPrice,
            eventAt: new Date().toISOString()
          });
          paymentOutcome.delete(orderId);
          return;
        }
        paymentOutcome.set(orderId, 'succeeded');
        await publishPaymentEvent('payment.succeeded', {
          orderId,
          status: 'paid',
          paymentMethod: method,
          userId: normalized.userId || null,
          totalPrice: normalized.totalPrice,
          eventAt: new Date().toISOString()
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
        await publishPaymentEvent('payment.timeout', {
          orderId,
          status: 'payment_timeout',
          paymentMethod: method,
          reason: 'payment_timeout',
          userId: normalized.userId || null,
          totalPrice: normalized.totalPrice,
          eventAt: new Date().toISOString()
        });
        paymentOutcome.delete(orderId);
      } catch (err) {
        console.error('Publish timeout event failed', err.message);
      }
    }, BANK_TRANSFER_TIMEOUT_MS);
    return;
  }

  if (method === 'cod') {
    await publishPaymentEvent('payment.succeeded', {
      orderId,
      status: 'paid',
      paymentMethod: method,
      walletDebited: false,
      eventAt: new Date().toISOString()
    });
    return;
  }

  await publishPaymentFailed(normalized, 'unsupported_payment_method');
}

async function handleOrderCancelled(payload) {
  const normalized = normalizeOrder(payload);
  if (!Number.isFinite(normalized.orderId) || !normalized.userId) return;
  const shouldRefundToWallet = Boolean(payload?.shouldRefundToWallet);
  if (!shouldRefundToWallet) return;
  const cancelReason = String(payload?.cancel_reason || 'order_cancelled');
  const refund = await refundOrderToWallet({
    orderId: normalized.orderId,
    userId: normalized.userId,
    amount: normalized.totalPrice,
    reason: cancelReason,
    allowWithoutDebit: true
  });
  if (!refund.ok) return;
  await publishPaymentEvent('payment.refunded', {
    orderId: normalized.orderId,
    userId: normalized.userId,
    status: 'refunded',
    reason: cancelReason,
    eventAt: new Date().toISOString()
  });
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

  await consumer.run({
    eachMessage: async ({ topic, message }) => {
      const payload = JSON.parse(message.value.toString());
      if (topic === 'order.created') await handleOrderCreated(payload);
      if (topic === 'order.cancelled') await handleOrderCancelled(payload);
    }
  });

  console.log('Payment Service Kafka consumer running');
}

module.exports = { initConsumer };
