const { Kafka } = require('kafkajs');

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

async function publishPaymentEvent(topic, payload) {
  if (!producer) throw new Error('Kafka producer not initialized');
  await producer.send({
    topic,
    messages: [
      {
        key: String(payload.orderId),
        value: JSON.stringify(payload)
      }
    ]
  });
}

module.exports = { initProducer, publishPaymentEvent };
