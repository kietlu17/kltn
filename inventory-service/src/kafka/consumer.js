const { Kafka } = require('kafkajs');
const { syncProductInventory } = require('../controllers/inventoryController');

async function handleProductSynced(message, options = {}) {
  const data = JSON.parse(message.value.toString());
  await syncProductInventory(data, options);
}

async function initConsumer() {
  const kafka = new Kafka({
    clientId: 'inventory-service',
    brokers: [process.env.KAFKA_BROKER || 'localhost:9092']
  });

  const consumer = kafka.consumer({ groupId: 'inventory-group' });
  await consumer.connect();
  await consumer.subscribe({ topic: 'product.created' });
  await consumer.subscribe({ topic: 'product.updated' });

  await consumer.run({
    eachMessage: async ({ topic, message }) => {
      if (topic === 'product.created' || topic === 'product.updated') {
        await handleProductSynced(message, { syncStock: topic === 'product.created' });
      }
    }
  });

  console.log('Inventory Service Kafka consumer running');
}

module.exports = { initConsumer };
