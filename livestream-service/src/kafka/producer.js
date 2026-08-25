const { Kafka } = require('kafkajs');

let producer;

async function initProducer() {
  const kafka = new Kafka({
    clientId: 'livestream-service',
    brokers: [process.env.KAFKA_BROKER || 'localhost:9092']
  });
  producer = kafka.producer();
  await producer.connect();
  console.log('Livestream Service Kafka producer connected');
}

async function publishEvent(topic, payload, key = payload.liveId || payload.id) {
  if (!producer) return;
  await producer.send({
    topic,
    messages: [
      {
        key: String(key || Date.now()),
        value: JSON.stringify({
          eventId: `${topic}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
          eventType: topic,
          occurredAt: new Date().toISOString(),
          ...payload
        })
      }
    ]
  });
}

module.exports = { initProducer, publishEvent };
