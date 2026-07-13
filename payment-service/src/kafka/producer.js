const { Kafka } = require('kafkajs');
const { Op } = require('sequelize');
const { OutboxEvent } = require('../models');

let producer;

async function initProducer() {
  const kafka = new Kafka({
    clientId: 'payment-service',
    brokers: [process.env.KAFKA_BROKER || 'localhost:9092']
  });
  producer = kafka.producer();
  await producer.connect();
  console.log('Payment Service Kafka producer connected');
}

async function sendKafkaEvent(topic, payload, key = payload.orderId || payload.userId || payload.eventId) {
  if (!producer) throw new Error('Kafka producer not initialized');
  await producer.send({
    topic,
    messages: [
      {
        key: String(key),
        value: JSON.stringify(payload),
        headers: {
          sagaId: Buffer.from(String(payload.sagaId || '')),
          correlationId: Buffer.from(String(payload.correlationId || ''))
        }
      }
    ]
  });
}

async function enqueueEvent({
  transaction,
  topic,
  eventType,
  key,
  payload,
  aggregateType = 'payment_saga',
  aggregateId = key
}) {
  const eventPayload = {
    ...payload,
    eventId: payload.eventId || `${eventType}:${key}:${Date.now()}`,
    eventType,
    occurredAt: payload.occurredAt || new Date().toISOString()
  };
  await OutboxEvent.create(
    {
      aggregate_type: aggregateType,
      aggregate_id: String(aggregateId),
      event_type: eventType,
      topic,
      event_key: String(key),
      payload: eventPayload,
      headers: {
        sagaId: eventPayload.sagaId || '',
        correlationId: eventPayload.correlationId || ''
      },
      saga_id: eventPayload.sagaId || null,
      correlation_id: eventPayload.correlationId || null
    },
    { transaction }
  );
}

async function publishPaymentEvent(topic, payload, options = {}) {
  if (options.transaction) {
    await enqueueEvent({
      transaction: options.transaction,
      topic,
      eventType: options.eventType || topic,
      key: options.key || payload.orderId || payload.userId || payload.eventId,
      payload,
      aggregateType: options.aggregateType,
      aggregateId: options.aggregateId
    });
    return;
  }
  await sendKafkaEvent(topic, payload, options.key);
}

async function publishOutboxBatch() {
  if (!producer) return;
  const events = await OutboxEvent.findAll({
    where: {
      status: { [Op.in]: ['pending', 'failed'] },
      [Op.or]: [{ next_attempt_at: null }, { next_attempt_at: { [Op.lte]: new Date() } }]
    },
    order: [['created_at', 'ASC']],
    limit: Number(process.env.OUTBOX_BATCH_SIZE || 25)
  });

  for (const event of events) {
    try {
      await sendKafkaEvent(event.topic, event.payload, event.event_key);
      event.status = 'published';
      event.published_at = new Date();
      event.error = null;
      await event.save();
    } catch (err) {
      event.status = 'failed';
      event.attempts += 1;
      event.error = err.message;
      event.next_attempt_at = new Date(Date.now() + Math.min(60000, 1000 * 2 ** event.attempts));
      await event.save();
      console.error('[payment-service] outbox publish failed', {
        outboxId: event.id,
        topic: event.topic,
        sagaId: event.saga_id,
        correlationId: event.correlation_id,
        error: err.message
      });
    }
  }
}

function initOutboxPublisher() {
  const intervalMs = Number(process.env.OUTBOX_POLL_INTERVAL_MS || 2000);
  const timer = setInterval(() => {
    publishOutboxBatch().catch((err) => {
      console.error('[payment-service] outbox poll failed', err.message);
    });
  }, intervalMs);
  timer.unref?.();
}

module.exports = {
  initProducer,
  publishPaymentEvent,
  enqueueEvent,
  initOutboxPublisher,
  publishOutboxBatch
};
