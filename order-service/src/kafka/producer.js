const { Kafka } = require('kafkajs');

let producer;

async function initProducer() {
  const kafka = new Kafka({
    clientId: 'order-service',
    brokers: [process.env.KAFKA_BROKER || 'localhost:9092']
  });
  producer = kafka.producer();
  await producer.connect();
  console.log('Order Service Kafka producer connected');
}

async function publishOrderCreated(order) {
  if (!producer) throw new Error('Kafka producer not initialized');
  await producer.send({
    topic: 'order.created',
    messages: [
      {
        key: String(order.id),
        value: JSON.stringify(order)
      }
    ]
  });
}

async function publishOrderCancelled(order) {
  if (!producer) throw new Error('Kafka producer not initialized');
  await producer.send({
    topic: 'order.cancelled',
    messages: [
      {
        key: String(order.id),
        value: JSON.stringify(order)
      }
    ]
  });
}

async function publishOrderRefundRequested(order) {
  if (!producer) throw new Error('Kafka producer not initialized');
  await producer.send({
    topic: 'order.refund_requested',
    messages: [
      {
        key: String(order.id),
        value: JSON.stringify(order)
      }
    ]
  });
}

async function publishOrderPaid(order) {
  if (!producer) throw new Error('Kafka producer not initialized');
  await producer.send({
    topic: 'order.paid',
    messages: [
      {
        key: String(order.id),
        value: JSON.stringify(order)
      }
    ]
  });
}

module.exports = {
  initProducer,
  publishOrderCreated,
  publishOrderCancelled,
  publishOrderRefundRequested,
  publishOrderPaid
};
