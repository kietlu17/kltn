const { Kafka } = require('kafkajs');

let producer;

async function initProducer() {
  const kafka = new Kafka({
    clientId: 'product-service',
    brokers: [process.env.KAFKA_BROKER || 'localhost:9092']
  });
  producer = kafka.producer();
  await producer.connect();
  console.log('Product Service Kafka producer connected');
}

async function publishProductCreated(product) {
  if (!producer) {
    throw new Error('Kafka producer not initialized');
  }
  await producer.send({
    topic: 'product.created',
    messages: [
      {
        key: String(product._id),
        value: JSON.stringify({
          id: String(product._id),
          name: product.name,
          shopId: product.shopId
        })
      }
    ]
  });
}

module.exports = { initProducer, publishProductCreated };
