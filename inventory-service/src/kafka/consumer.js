const { Kafka } = require('kafkajs');
const Inventory = require('../models/Inventory');

async function handleProductCreated(message) {
  const data = JSON.parse(message.value.toString());
  await Inventory.findOrCreate({
    where: { product_id: data.id },
    defaults: { stock: 0, reserved_stock: 0 }
  });
}

async function handleOrderCreated(message) {
  const order = JSON.parse(message.value.toString());
  const products = order.products || [];
  for (const p of products) {
    const qty = Number(p.quantity || 0);
    if (!p.productId || qty <= 0) continue;
    await Inventory.decrement('stock', { by: qty, where: { product_id: p.productId } });
  }
}

async function handleOrderCancelled(message) {
  const order = JSON.parse(message.value.toString());
  const products = order.products || [];
  for (const p of products) {
    const qty = Number(p.quantity || 0);
    if (!p.productId || qty <= 0) continue;
    await Inventory.increment('stock', { by: qty, where: { product_id: p.productId } });
  }
}

async function initConsumer() {
  const kafka = new Kafka({
    clientId: 'inventory-service',
    brokers: [process.env.KAFKA_BROKER || 'localhost:9092']
  });

  const consumer = kafka.consumer({ groupId: 'inventory-group' });
  await consumer.connect();
  await consumer.subscribe({ topic: 'product.created' });
  await consumer.subscribe({ topic: 'order.created' });
  await consumer.subscribe({ topic: 'order.cancelled' });

  await consumer.run({
    eachMessage: async ({ topic, message }) => {
      if (topic === 'product.created') await handleProductCreated(message);
      if (topic === 'order.created') await handleOrderCreated(message);
      if (topic === 'order.cancelled') await handleOrderCancelled(message);
    }
  });

  console.log('Inventory Service Kafka consumer running');
}

module.exports = { initConsumer };
