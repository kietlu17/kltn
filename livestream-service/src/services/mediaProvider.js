const { AccessToken, LiveKitAPI, RoomServiceClient, WebhookReceiver } = require('livekit-server-sdk');

const apiKey = process.env.LIVEKIT_API_KEY || 'devkey';
const apiSecret = process.env.LIVEKIT_API_SECRET || 'devsecret';
const livekitHost = process.env.LIVEKIT_HOST || 'http://localhost:7880';
const publicUrl = process.env.LIVEKIT_PUBLIC_URL || 'ws://localhost:7880';

const roomClient = new RoomServiceClient(livekitHost, apiKey, apiSecret);
const livekitApi = new LiveKitAPI({ host: livekitHost, apiKey, secret: apiSecret });
const webhookReceiver = new WebhookReceiver(apiKey, apiSecret);

function buildRoomName(liveId) {
  return `live_${liveId}`;
}

async function ensureRoom(roomName) {
  try {
    await roomClient.createRoom({
      name: roomName,
      emptyTimeout: Number(process.env.LIVEKIT_EMPTY_TIMEOUT_SECONDS || 900),
      maxParticipants: Number(process.env.LIVEKIT_MAX_PARTICIPANTS || 10000)
    });
  } catch (err) {
    if (!/already exists|exists/i.test(err.message || '')) {
      throw err;
    }
  }
}

async function endRoom(roomName) {
  try {
    await roomClient.deleteRoom(roomName);
  } catch (err) {
    if (!/not found|does not exist/i.test(err.message || '')) {
      throw err;
    }
  }
}

async function listRooms() {
  return roomClient.listRooms();
}

async function dispatchAiCohost(roomName, metadata = {}) {
  const agentName = process.env.LIVEKIT_AI_COHOST_AGENT_NAME || 'live-commerce-cohost';
  const dispatches = await livekitApi.agentDispatch.listDispatch(roomName).catch(() => []);
  const alreadyDispatched = dispatches.some((item) => item.agentName === agentName || item.agent_name === agentName);
  if (alreadyDispatched) return null;
  return livekitApi.agentDispatch.createDispatch(roomName, agentName, {
    metadata: JSON.stringify(metadata)
  });
}

async function receiveWebhook(rawBody, authHeader) {
  return webhookReceiver.receive(rawBody, authHeader);
}

async function createToken({ roomName, identity, displayName, role }) {
  const ttl = role === 'seller'
    ? process.env.LIVEKIT_PUBLISHER_TOKEN_TTL || '4h'
    : process.env.LIVEKIT_VIEWER_TOKEN_TTL || '2h';
  const token = new AccessToken(apiKey, apiSecret, {
    identity,
    name: displayName || identity,
    ttl
  });
  token.addGrant({
    room: roomName,
    roomJoin: true,
    canPublish: role === 'seller' || role === 'moderator',
    canSubscribe: true,
    canPublishData: true
  });
  return token.toJwt();
}

module.exports = {
  buildRoomName,
  ensureRoom,
  endRoom,
  listRooms,
  dispatchAiCohost,
  receiveWebhook,
  createToken,
  publicUrl
};
