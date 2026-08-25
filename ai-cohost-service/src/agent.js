import 'dotenv/config';
import fs from 'node:fs';
import https from 'node:https';
import { fileURLToPath } from 'node:url';
import fetch from 'node-fetch';
import { Kafka } from 'kafkajs';
import { AutoSubscribe, WorkerOptions, cli, defineAgent } from '@livekit/agents';
import { RoomEvent } from '@livekit/rtc-node';

const textEncoder = new TextEncoder();
const textDecoder = new TextDecoder();

const kafka = new Kafka({
  clientId: process.env.KAFKA_CLIENT_ID || 'ai-cohost-service',
  brokers: [process.env.KAFKA_BROKER || 'localhost:9092']
});
const producer = kafka.producer();
let kafkaReady = false;

function mtlsAgent() {
  if (process.env.MTLS_ENABLED !== 'true') return undefined;
  return new https.Agent({
    ca: fs.readFileSync(process.env.MTLS_CA_PATH),
    cert: fs.readFileSync(process.env.MTLS_CLIENT_CERT_PATH),
    key: fs.readFileSync(process.env.MTLS_CLIENT_KEY_PATH),
    rejectUnauthorized: process.env.MTLS_REJECT_UNAUTHORIZED !== 'false'
  });
}

const cartAgent = mtlsAgent();

async function publishKafka(topic, payload, key) {
  if (!kafkaReady) {
    await producer.connect();
    kafkaReady = true;
  }
  await producer.send({
    topic,
    messages: [
      {
        key: key || payload.liveId || payload.id || null,
        value: JSON.stringify({
          ...payload,
          eventType: topic,
          occurredAt: payload.occurredAt || new Date().toISOString()
        })
      }
    ]
  });
}

function decodePacket(payload) {
  try {
    return JSON.parse(textDecoder.decode(payload));
  } catch {
    return null;
  }
}

async function publishRoomData(room, payload) {
  if (!room.localParticipant) return;
  await room.localParticipant.publishData(textEncoder.encode(JSON.stringify(payload)), {
    reliable: true,
    topic: payload.type || 'live.event'
  });
}

function detectPurchaseIntent(text) {
  const normalized = String(text || '').toLowerCase();
  const hasBuyIntent = [
    'toi muon mua',
    'tôi muốn mua',
    'mua san pham',
    'mua sản phẩm',
    'lay san pham',
    'lấy sản phẩm',
    'add cart',
    'them vao gio',
    'thêm vào giỏ'
  ].some((keyword) => normalized.includes(keyword));

  if (!hasBuyIntent) return null;

  const quantityMatch = normalized.match(/(\d+)\s*(cai|cái|sp|san pham|sản phẩm|mon|món)?/);
  return {
    name: 'add_to_cart',
    confidence: 0.82,
    quantity: quantityMatch ? Math.max(1, Number(quantityMatch[1])) : 1
  };
}

async function addToCart({ buyerId, productId, quantity }) {
  const response = await fetch(`${process.env.CART_SERVICE_URL || 'https://localhost:3005'}/cart/add`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    agent: cartAgent,
    body: JSON.stringify({ userId: buyerId, productId, quantity })
  });

  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload?.message || `cart-service returned ${response.status}`);
  }
  return payload;
}

async function handleChatMessage(room, message, jobMetadata) {
  const chatEvent = {
    type: 'live.chat.message.created',
    id: message.id,
    liveId: message.liveId || jobMetadata.liveId,
    shopId: message.shopId || jobMetadata.shopId,
    buyerId: message.buyerId || message.senderId,
    senderId: message.senderId,
    senderRole: message.senderRole,
    senderName: message.senderName,
    text: message.text,
    activePinnedProductId: message.activePinnedProductId || jobMetadata.activePinnedProductId || null
  };
  await publishKafka('live.chat.message.created', chatEvent, chatEvent.liveId);

  if (message.senderRole !== 'buyer') return;
  const intent = detectPurchaseIntent(message.text);
  if (!intent) return;

  const productId = chatEvent.activePinnedProductId;
  const intentEvent = {
    type: 'live.intent.detected',
    id: `intent-${Date.now()}`,
    liveId: chatEvent.liveId,
    shopId: chatEvent.shopId,
    buyerId: chatEvent.buyerId,
    intent: intent.name,
    productId,
    quantity: intent.quantity,
    confidence: intent.confidence,
    reply: productId
      ? `Da nhan yeu cau mua ${intent.quantity} san pham dang ghim`
      : 'Shop chua co san pham dang ghim de them vao gio'
  };
  await publishKafka('live.intent.detected', intentEvent, intentEvent.liveId);
  await publishRoomData(room, intentEvent);

  if (!productId || !chatEvent.buyerId) return;

  try {
    await addToCart({ buyerId: chatEvent.buyerId, productId, quantity: intent.quantity });
    const cartEvent = {
      type: 'live.cart.item_added',
      id: `cart-${Date.now()}`,
      liveId: chatEvent.liveId,
      shopId: chatEvent.shopId,
      buyerId: chatEvent.buyerId,
      productId,
      quantity: intent.quantity,
      reply: `Da them ${intent.quantity} san pham vao gio hang`
    };
    await publishKafka('live.cart.item_added', cartEvent, cartEvent.liveId);
    await publishRoomData(room, cartEvent);
  } catch (err) {
    await publishRoomData(room, {
      type: 'live.cart.item_add_failed',
      id: `cart-failed-${Date.now()}`,
      liveId: chatEvent.liveId,
      buyerId: chatEvent.buyerId,
      productId,
      quantity: intent.quantity,
      reply: err.message
    });
  }
}

export default defineAgent({
  entry: async (ctx) => {
    const jobMetadata = ctx.job?.metadata ? JSON.parse(ctx.job.metadata) : {};
    const room = ctx.room;

    room.on(RoomEvent.DataReceived, (payload, participant) => {
      const message = decodePacket(payload);
      if (!message || message.type !== 'live.chat.message') return;
      handleChatMessage(room, {
        ...message,
        senderId: message.senderId || participant?.identity,
        senderName: message.senderName || participant?.name || participant?.identity
      }, jobMetadata).catch((err) => {
        console.error('ai co-host failed to handle chat message', err);
      });
    });

    await ctx.connect(undefined, AutoSubscribe.SUBSCRIBE_ALL);
  }
});

cli.runApp(new WorkerOptions({ agent: fileURLToPath(import.meta.url) }));
