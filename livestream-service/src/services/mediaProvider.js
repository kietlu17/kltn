const {
  AccessToken,
  LiveKitAPI,
  RoomServiceClient,
  WebhookReceiver,
  S3Upload,
  SegmentedFileOutput,
  SegmentedFileProtocol
} = require('livekit-server-sdk');

const apiKey = process.env.LIVEKIT_API_KEY || 'devkey';
const apiSecret = process.env.LIVEKIT_API_SECRET || 'devsecret';
const livekitHost = process.env.LIVEKIT_HOST || 'http://localhost:7880';
const publicUrl = process.env.LIVEKIT_PUBLIC_URL || 'ws://localhost:7880';
const hlsPublicBaseUrl = (process.env.HLS_PUBLIC_BASE_URL || 'http://localhost:8088/hls').replace(/\/$/, '');
const hlsBucket = process.env.LIVE_HLS_BUCKET || 'live-hls';
const hlsSegmentDuration = Number(process.env.LIVEKIT_HLS_SEGMENT_DURATION_SECONDS || 2);

const roomClient = new RoomServiceClient(livekitHost, apiKey, apiSecret);
const livekitApi = new LiveKitAPI({ host: livekitHost, apiKey, secret: apiSecret });
const webhookReceiver = new WebhookReceiver(apiKey, apiSecret);
const aiAgentIdentityPrefix = 'agent-';

function buildRoomName(liveId) {
  return `live_${liveId}`;
}

function buildHlsPlaylistPath(liveId) {
  return `${liveId}/index.m3u8`;
}

function buildHlsPlaybackUrl(liveId) {
  return `${hlsPublicBaseUrl}/${buildHlsPlaylistPath(liveId)}`;
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
  const participants = await roomClient.listParticipants(roomName).catch(() => []);
  const hasActiveAgent = participants.some((item) => {
    const identity = item.identity || item.sid || '';
    return item.kind === 4 || identity.startsWith(aiAgentIdentityPrefix);
  });
  if (hasActiveAgent) return null;

  const staleDispatches = dispatches.filter((item) => item.agentName === agentName || item.agent_name === agentName);
  await Promise.all(staleDispatches.map((item) => {
    const dispatchId = item.id || item.dispatchId || item.dispatch_id;
    if (!dispatchId) return null;
    return livekitApi.agentDispatch.deleteDispatch(dispatchId, roomName).catch(() => null);
  }));
  return livekitApi.agentDispatch.createDispatch(roomName, agentName, {
    metadata: JSON.stringify(metadata)
  });
}

function buildHlsOutput(liveId) {
  return new SegmentedFileOutput({
    protocol: SegmentedFileProtocol.HLS_PROTOCOL,
    filenamePrefix: `${liveId}/segment`,
    playlistName: buildHlsPlaylistPath(liveId),
    livePlaylistName: `${liveId}/live.m3u8`,
    segmentDuration: hlsSegmentDuration,
    output: {
      case: 's3',
      value: new S3Upload({
        accessKey: process.env.MINIO_ROOT_USER || 'minioadmin',
        secret: process.env.MINIO_ROOT_PASSWORD || 'minioadmin',
        region: process.env.LIVE_HLS_REGION || 'us-east-1',
        endpoint: process.env.LIVE_HLS_S3_ENDPOINT || 'http://minio:9000',
        bucket: hlsBucket,
        forcePathStyle: true
      })
    }
  });
}

async function startHlsEgress(roomName, liveId, participantIdentity = '') {
  if (process.env.LIVEKIT_EGRESS_ENABLED !== 'true') {
    return null;
  }

  const egress = participantIdentity
    ? await livekitApi.egress.startParticipantEgress(
      roomName,
      participantIdentity,
      { segments: buildHlsOutput(liveId) },
      { screenShare: false }
    )
    : await livekitApi.egress.startRoomCompositeEgress(
      roomName,
      buildHlsOutput(liveId),
      {
        layout: process.env.LIVEKIT_EGRESS_LAYOUT || 'speaker',
        audioOnly: false,
        videoOnly: false
      }
    );

  return {
    egressId: egress.egressId || egress.egressID || egress.egress_id || '',
    egressStatus: String(egress.status || 'starting'),
    hlsPlaylistPath: buildHlsPlaylistPath(liveId),
    hlsPlaybackUrl: buildHlsPlaybackUrl(liveId)
  };
}

async function stopHlsEgress(egressId) {
  if (!egressId) return null;
  return livekitApi.egress.stopEgress(egressId);
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
  startHlsEgress,
  stopHlsEgress,
  buildHlsPlaybackUrl,
  buildHlsPlaylistPath,
  receiveWebhook,
  createToken,
  publicUrl
};
