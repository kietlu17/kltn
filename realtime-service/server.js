require('dotenv').config();
const http = require('http');
const express = require('express');
const cors = require('cors');
const jwt = require('jsonwebtoken');
const fetch = require('node-fetch');
const { Kafka } = require('kafkajs');
const { Server } = require('socket.io');

const PORT = Number(process.env.PORT || 3015);
const JWT_SECRET = process.env.JWT_SECRET || 'devsecret';
const AI_COHOST_SERVICE_URL = (process.env.AI_COHOST_SERVICE_URL || 'http://ai-cohost-service:3020').replace(/\/$/, '');
const KAFKA_BROKER = process.env.KAFKA_BROKER || 'localhost:9092';

const app = express();
app.use(cors({ origin: true, credentials: true }));
app.use(express.json());

const server = http.createServer(app);
const io = new Server(server, {
  path: '/socket.io',
  cors: { origin: true, credentials: true },
  transports: ['websocket', 'polling']
});

let producer;

async function initProducer() {
  const kafka = new Kafka({ clientId: 'realtime-service', brokers: [KAFKA_BROKER] });
  producer = kafka.producer();
  await producer.connect();
  console.log('Realtime Service Kafka producer connected');
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

function liveRoom(liveId) {
  return `live:${liveId}`;
}

function verifySocket(socket, next) {
  try {
    const token = socket.handshake.auth?.token || socket.handshake.headers?.authorization?.replace(/^Bearer\s+/i, '');
    const liveId = socket.handshake.auth?.liveId || socket.handshake.query?.liveId;
    if (!token) return next(new Error('Unauthorized'));
    if (!liveId) return next(new Error('liveId is required'));
    const user = jwt.verify(token, JWT_SECRET);
    socket.user = {
      id: String(user.id || ''),
      email: user.email || '',
      role: user.role || '',
      shopId: user.shopId || ''
    };
    socket.liveId = String(liveId);
    return next();
  } catch {
    return next(new Error('Unauthorized'));
  }
}

function publicUser(user) {
  return {
    userId: user.id,
    email: user.email,
    role: user.role,
    shopId: user.shopId
  };
}

async function forwardToAi(chatEvent) {
  if (chatEvent.senderRole !== 'buyer') return;
  try {
    const response = await fetch(`${AI_COHOST_SERVICE_URL}/live-chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: chatEvent })
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(body.message || body.error || `AI service returned ${response.status}`);
    }
    (body.events || []).forEach((event) => {
      io.to(liveRoom(chatEvent.liveId)).emit('live:event', event);
    });
  } catch (err) {
    const event = {
      type: 'live.ai.error',
      id: `ai-error-${Date.now()}`,
      liveId: chatEvent.liveId,
      buyerId: chatEvent.buyerId,
      reply: 'Tro ly AI dang ban. Vui long thu lai sau.'
    };
    io.to(liveRoom(chatEvent.liveId)).emit('live:event', event);
    console.error('AI live chat forward failed', err.message);
  }
}

io.use(verifySocket);

io.on('connection', (socket) => {
  const roomName = liveRoom(socket.liveId);
  socket.join(roomName);
  io.to(roomName).emit('live:presence', {
    liveId: socket.liveId,
    viewerCount: io.sockets.adapter.rooms.get(roomName)?.size || 0
  });

  socket.on('live:chat:send', async (payload = {}, ack) => {
    try {
      const text = String(payload.text || '').trim();
      if (!text) throw new Error('Message is empty');
      const event = {
        type: 'live.chat.message',
        id: payload.id || `msg-${Date.now()}`,
        liveId: socket.liveId,
        shopId: payload.shopId || '',
        senderId: socket.user.id,
        senderRole: socket.user.role,
        senderName: payload.senderName || socket.user.email || socket.user.role,
        buyerId: socket.user.role === 'buyer' ? socket.user.id : payload.buyerId,
        text,
        activePinnedProductId: payload.activePinnedProductId || null
      };
      io.to(roomName).emit('live:event', event);
      await publishEvent('live.chat.message.created', { ...event, type: 'live.chat.message.created' }, event.liveId);
      ack?.({ ok: true, event });
      forwardToAi(event);
    } catch (err) {
      ack?.({ ok: false, message: err.message });
    }
  });

  socket.on('live:event:send', async (payload = {}, ack) => {
    try {
      if (!['seller', 'admin'].includes(socket.user.role)) throw new Error('Forbidden');
      const event = {
        ...payload,
        id: payload.id || `${payload.type || 'live-event'}-${Date.now()}`,
        liveId: socket.liveId,
        senderId: socket.user.id,
        senderRole: socket.user.role
      };
      io.to(roomName).emit('live:event', event);
      if (event.type) await publishEvent(event.type, event, event.liveId);
      ack?.({ ok: true, event });
    } catch (err) {
      ack?.({ ok: false, message: err.message });
    }
  });

  socket.on('disconnect', () => {
    io.to(roomName).emit('live:presence', {
      liveId: socket.liveId,
      viewerCount: io.sockets.adapter.rooms.get(roomName)?.size || 0
    });
  });
});

app.get('/health', (_req, res) => {
  res.json({ ok: true, service: 'realtime-service' });
});

initProducer()
  .catch((err) => console.error('Realtime Service Kafka producer failed', err.message))
  .finally(() => {
    server.listen(PORT, () => console.log(`Realtime Service running on port ${PORT}`));
  });
