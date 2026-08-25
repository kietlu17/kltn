const Redis = require('ioredis');
const LiveSession = require('../models/LiveSession');
const { listRooms } = require('./mediaProvider');
const { publishEvent } = require('../kafka/producer');

const redis = new Redis(process.env.REDIS_URL || 'redis://localhost:6379');

function viewerSetKey(liveId) {
  return `live:${liveId}:viewers`;
}

function isViewerIdentity(identity = '') {
  return identity.startsWith('buyer:') || identity.startsWith('guest:');
}

async function markViewerJoined(liveId, identity) {
  if (!liveId || !isViewerIdentity(identity)) return 0;
  await redis.sadd(viewerSetKey(liveId), identity);
  return redis.scard(viewerSetKey(liveId));
}

async function markViewerLeft(liveId, identity) {
  if (!liveId || !isViewerIdentity(identity)) return 0;
  await redis.srem(viewerSetKey(liveId), identity);
  return redis.scard(viewerSetKey(liveId));
}

async function flushLiveStats() {
  const activeLives = await LiveSession.find({ status: { $in: ['starting', 'live', 'paused'] } }).limit(200);
  await Promise.all(activeLives.map(async (live) => {
    const viewerCount = await redis.scard(viewerSetKey(String(live._id)));
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
    if (activeRoomNames.has(live.providerRoomId)) return;
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
  markViewerLeft
};
