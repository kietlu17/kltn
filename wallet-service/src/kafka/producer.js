const { Kafka } = require('kafkajs');
const { Op } = require('sequelize');
const { OutboxEvent } = require('../models');

let producer;
let outboxTimer;

async function initProducer() {
  const kafka = new Kafka({
    clientId: 'wallet-service',
    brokers: [process.env.KAFKA_BROKER || 'localhost:9092']
  });
  producer = kafka.producer();
  await producer.connect();
  console.log('Wallet Service Kafka producer connected');
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
      await producer.send({
        topic: event.topic,
        messages: [
          {
            key: event.event_key,
            value: JSON.stringify(event.payload),
            headers: {
              sagaId: Buffer.from(String(event.saga_id || '')),
              correlationId: Buffer.from(String(event.correlation_id || ''))
            }
          }
        ]
      });
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
      console.error('[wallet-service] outbox publish failed', {
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
  outboxTimer = setInterval(() => {
    publishOutboxBatch().catch((err) => {
      console.error('[wallet-service] outbox poll failed', err.message);
    });
  }, intervalMs);
  outboxTimer.unref?.();
}

module.exports = { initProducer, initOutboxPublisher, publishOutboxBatch };
