const { Kafka } = require('kafkajs');
const {
  handlePaymentPending,
  handlePaymentSucceeded,
  handlePaymentFailed,
  handlePaymentTimeout,
  handlePaymentRefunded,
  handleShopSettlementCompleted
} = require('../controllers/orderController');
const InboxEvent = require('../models/InboxEvent');

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
    console.log('[order-service] duplicate event skipped', { topic, messageId });
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
    console.error('[order-service] consume failed', {
      topic,
      messageId,
      sagaId: payload?.sagaId,
      correlationId: payload?.correlationId,
      error: err.message
    });
    throw err;
  }
}

async function initConsumer() {
  const kafka = new Kafka({
    clientId: 'order-service-consumer',
    brokers: [process.env.KAFKA_BROKER || 'localhost:9092']
  });

  const consumer = kafka.consumer({ groupId: 'order-group' });
  await consumer.connect();
  await consumer.subscribe({ topic: 'payment.pending' });
  await consumer.subscribe({ topic: 'payment.succeeded' });
  await consumer.subscribe({ topic: 'payment.failed' });
  await consumer.subscribe({ topic: 'payment.timeout' });
  await consumer.subscribe({ topic: 'payment.refunded' });
  await consumer.subscribe({ topic: 'shop.settlement.completed' });

  await consumer.run({
    eachMessage: async ({ topic, partition, message }) => {
      await withInbox(topic, partition, message, async (payload) => {
        if (topic === 'payment.pending') await handlePaymentPending(payload);
        if (topic === 'payment.succeeded') await handlePaymentSucceeded(payload);
        if (topic === 'payment.failed') await handlePaymentFailed(payload);
        if (topic === 'payment.timeout') await handlePaymentTimeout(payload);
        if (topic === 'payment.refunded') await handlePaymentRefunded(payload);
        if (topic === 'shop.settlement.completed') await handleShopSettlementCompleted(payload);
      });
    }
  });

  console.log('Order Service Kafka consumer running');
}

module.exports = { initConsumer };
