const Redis = require('ioredis');
const LiveSession = require('../models/LiveSession');
const { listRooms, dispatchAiCohost } = require('./mediaProvider');
const { publishEvent } = require('../kafka/producer');

const redis = new Redis(process.env.REDIS_URL || 'redis://localhost:6379');

function viewerSetKey(liveId) {
  return `live:${liveId}:viewers`;
}

function viewerPresenceKey(liveId, identity) {
  return `live:${liveId}:viewer:${identity}`;
}

function isViewerIdentity(identity = '') {
  return identity.startsWith('buyer:') || identity.startsWith('guest:') || identity.startsWith('hls:');
}

async function pruneExpiredViewers(liveId) {
  const identities = await redis.smembers(viewerSetKey(liveId));
  if (!identities.length) return 0;
  const keys = identities.map((identity) => viewerPresenceKey(liveId, identity));
  const values = await redis.mget(keys);
  const expired = identities.filter((_identity, index) => !values[index]);
  if (expired.length) {
    await redis.srem(viewerSetKey(liveId), ...expired);
  }
  return redis.scard(viewerSetKey(liveId));
}

async function countActiveViewers(liveId) {
  if (!liveId) return 0;
  return pruneExpiredViewers(liveId);
}

async function markViewerJoined(liveId, identity) {
  if (!liveId || !isViewerIdentity(identity)) return 0;
  await redis.sadd(viewerSetKey(liveId), identity);
  await redis.set(viewerPresenceKey(liveId, identity), '1', 'EX', Number(process.env.LIVE_VIEWER_TTL_SECONDS || 45));
  return countActiveViewers(liveId);
}

async function markViewerLeft(liveId, identity) {
  if (!liveId || !isViewerIdentity(identity)) return 0;
  await redis.srem(viewerSetKey(liveId), identity);
  await redis.del(viewerPresenceKey(liveId, identity));
  return countActiveViewers(liveId);
}

async function markViewerHeartbeat(liveId, identity) {
  if (!liveId || !isViewerIdentity(identity)) return 0;
  await redis.sadd(viewerSetKey(liveId), identity);
  await redis.set(viewerPresenceKey(liveId, identity), '1', 'EX', Number(process.env.LIVE_VIEWER_TTL_SECONDS || 45));
  return countActiveViewers(liveId);
}

async function flushLiveStats() {
  const activeLives = await LiveSession.find({ status: { $in: ['starting', 'live', 'paused'] } }).limit(200);
  await Promise.all(activeLives.map(async (live) => {
    const viewerCount = await countActiveViewers(String(live._id));
    const nextPeak = Math.max(Number(live.stats?.peakViewers || 0), Number(viewerCount || 0));
    live.stats = {
      ...(live.stats || {}),
      peakViewers: nextPeak,
      totalViewers: Math.max(Number(live.stats?.totalViewers || 0), Number(viewerCount || 0))
    };
    await live.save();
    await publishEvent('live.stats.updated.v1', {
      liveId: String(live._id),
      shopId: live.shopId,
      viewerCount,
      peakViewers: nextPeak
    });
  }));
}

async function reconcileLiveRooms() {
  const providerRooms = await listRooms();
  const activeRoomNames = new Set((providerRooms || []).map((room) => room.name));
  const activeLives = await LiveSession.find({ status: { $in: ['starting', 'live'] } }).limit(200);
  await Promise.all(activeLives.map(async (live) => {
    if (activeRoomNames.has(live.providerRoomId)) {
      if (process.env.LIVEKIT_AI_COHOST_IN_ROOM_ENABLED === 'true' && process.env.LIVE_AI_COHOST_RECONCILE_ENABLED !== 'false') {
        await dispatchAiCohost(live.providerRoomId, {
          liveId: String(live._id),
          shopId: live.shopId,
          sellerId: live.sellerId,
          activePinnedProductId: live.activePinnedProductId || null
        }).catch((err) => {
          console.error('Live AI co-host reconcile failed', err.message);
          publishEvent('live.ai_cohost.reconcile_failed.v1', {
            liveId: String(live._id),
            shopId: live.shopId,
            providerRoomId: live.providerRoomId,
            error: err.message
          }).catch(() => {});
        });
      }
      return;
    }
    live.status = 'paused';
    await live.save();
    await publishEvent('live.session.paused.v1', {
      liveId: String(live._id),
      shopId: live.shopId,
      reason: 'provider_room_missing'
    });
  }));
}

function startStatsFlush() {
  const intervalMs = Number(process.env.LIVE_STATS_FLUSH_INTERVAL_MS || 30000);
  setInterval(() => {
    flushLiveStats().catch((err) => console.error('Live stats flush failed', err.message));
  }, intervalMs);
}

function startReconcileJob() {
  const intervalMs = Number(process.env.LIVE_RECONCILE_INTERVAL_MS || 60000);
  setInterval(() => {
    reconcileLiveRooms().catch((err) => console.error('Live reconcile failed', err.message));
  }, intervalMs);
}

module.exports = {
  startStatsFlush,
  startReconcileJob,
  flushLiveStats,
  reconcileLiveRooms,
  markViewerJoined,
  markViewerLeft,
  markViewerHeartbeat,
  countActiveViewers
};
