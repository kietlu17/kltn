const { Kafka } = require('kafkajs');
const {
  handlePaymentPending,
  handlePaymentSucceeded,
  handlePaymentFailed,
  handlePaymentTimeout
} = require('../controllers/orderController');

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

  await consumer.run({
    eachMessage: async ({ topic, message }) => {
      const payload = JSON.parse(message.value.toString());
      if (topic === 'payment.pending') await handlePaymentPending(payload);
      if (topic === 'payment.succeeded') await handlePaymentSucceeded(payload);
      if (topic === 'payment.failed') await handlePaymentFailed(payload);
      if (topic === 'payment.timeout') await handlePaymentTimeout(payload);
    }
  });

  console.log('Order Service Kafka consumer running');
}

module.exports = { initConsumer };
