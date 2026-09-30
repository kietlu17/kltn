const { Kafka } = require('kafkajs');

let producer;

function toProductInventoryPayload(product) {
  const variants = Array.isArray(product.variants)
    ? product.variants.map((variant) => ({
        id: String(variant._id || variant.id || ''),
        name: variant.name,
        sku: variant.sku || '',
        quantity: Number(variant.quantity || 0)
      }))
    : [];
  return {
    id: String(product._id),
    name: product.name,
    shopId: product.shopId,
    quantity: Number(product.quantity || 0),
    variants
  };
}

async function initProducer() {
  const kafka = new Kafka({
    clientId: 'product-service',
    brokers: [process.env.KAFKA_BROKER || 'localhost:9092']
  });
  producer = kafka.producer();
  await producer.connect();
  console.log('Product Service Kafka producer connected');
}

async function closeProducer() {
  if (!producer) return;
  await producer.disconnect();
  producer = null;
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
        value: JSON.stringify(toProductInventoryPayload(product))
      }
    ]
  });
}

async function publishProductUpdated(product) {
  if (!producer) {
    throw new Error('Kafka producer not initialized');
  }
  await producer.send({
    topic: 'product.updated',
    messages: [
      {
        key: String(product._id),
        value: JSON.stringify(toProductInventoryPayload(product))
      }
    ]
  });
}

async function publishProductDeleted(product) {
  if (!producer) {
    throw new Error('Kafka producer not initialized');
  }
  await producer.send({
    topic: 'product.deleted',
    messages: [
      {
        key: String(product._id),
        value: JSON.stringify({ id: String(product._id) })
      }
    ]
  });
}

module.exports = {
  initProducer,
  closeProducer,
  publishProductCreated,
  publishProductUpdated,
  publishProductDeleted
};
