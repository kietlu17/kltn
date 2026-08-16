const { Kafka } = require('kafkajs');
const { applyDeliveredOrderSales } = require('../services/productSalesService');

async function handleOrderDelivered(message) {
  const order = JSON.parse(message.value.toString());
  const result = await applyDeliveredOrderSales(order);
  if (result?.processed) {
    console.log(`[product-service] sold count updated for delivered order ${result.orderId}`);
  }
}

async function initConsumer() {
  const kafka = new Kafka({
    clientId: 'product-service',
    brokers: [process.env.KAFKA_BROKER || 'localhost:9092']
  });

  const consumer = kafka.consumer({ groupId: 'product-sales-group' });
  await consumer.connect();
  await consumer.subscribe({ topic: 'order.delivered', fromBeginning: true });

  await consumer.run({
    eachMessage: async ({ topic, message }) => {
      if (topic === 'order.delivered') {
        await handleOrderDelivered(message);
      }
    }
  });

  console.log('Product Service Kafka consumer running');
}

module.exports = { initConsumer, handleOrderDelivered };
