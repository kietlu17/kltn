const LiveSession = require('../models/LiveSession');
const LivePinnedProduct = require('../models/LivePinnedProduct');
const { publishEvent } = require('../kafka/producer');
const {
  buildRoomName,
  ensureRoom,
  endRoom,
  dispatchAiCohost,
  startHlsEgress,
  stopHlsEgress,
  createToken,
  publicUrl,
  receiveWebhook
} = require('../services/mediaProvider');
const { getProduct } = require('../services/productClient');
const {
  markViewerJoined,
  markViewerLeft,
  markViewerHeartbeat,
  countActiveViewers
} = require('../services/liveMaintenance');

function requester(req) {
  return {
    userId: req.headers['x-user-id'] || '',
    role: req.headers['x-user-role'] || '',
    shopId: req.headers['x-user-shop-id'] || ''
  };
}

function normalizeLive(live) {
  const obj = live.toObject({ getters: false, virtuals: false });
  return { id: String(obj._id), ...obj };
}

function normalizePinned(product) {
  const obj = product.toObject({ getters: false, virtuals: false });
  return { id: String(obj._id), ...obj };
}

function canManageLive(req, live) {
  const current = requester(req);
  if (current.role === 'admin') return true;
  return current.role === 'seller' && String(current.shopId) === String(live.shopId);
}

async function createLive(req, res) {
  try {
    const current = requester(req);
    const shopId = req.body?.shopId || current.shopId;
    if (!current.userId || current.role !== 'seller') {
      return res.status(403).json({ message: 'Only sellers can create livestreams' });
    }
    if (!shopId || String(shopId) !== String(current.shopId)) {
      return res.status(403).json({ message: 'Cannot create livestream for another shop' });
    }
    const title = String(req.body?.title || '').trim();
    if (!title) {
      return res.status(400).json({ message: 'title is required' });
    }

    const live = await LiveSession.create({
      shopId,
      sellerId: current.userId,
      title,
      description: req.body?.description || '',
      coverImage: req.body?.coverImage || '',
      visibility: req.body?.visibility || 'public',
      scheduledAt: req.body?.scheduledAt || null,
      providerRoomId: `pending_${Date.now()}`
    });
    live.providerRoomId = buildRoomName(String(live._id));
    await live.save();

    await publishEvent('live.session.created.v1', {
      liveId: String(live._id),
      shopId,
      sellerId: current.userId,
      status: live.status
    });

    return res.status(201).json(normalizeLive(live));
  } catch (err) {
    return res.status(500).json({ message: 'Create live failed', error: err.message });
  }
}

async function listLives(req, res) {
  try {
    const { shopId, status } = req.query;
    const filter = {};
    if (shopId) filter.shopId = shopId;
    if (status) filter.status = status;
    if (!status && req.path.includes('/active')) filter.status = 'live';
    const list = await LiveSession.find(filter).sort({ createdAt: -1 }).limit(50);
    return res.json(list.map(normalizeLive));
  } catch (err) {
    return res.status(500).json({ message: 'List lives failed', error: err.message });
  }
}

async function listSellerLives(req, res) {
  try {
    const current = requester(req);
    if (current.role !== 'seller' || !current.shopId) {
      return res.status(403).json({ message: 'Only sellers can view seller livestreams' });
    }
    const list = await LiveSession.find({ shopId: current.shopId }).sort({ createdAt: -1 }).limit(50);
    return res.json(list.map(normalizeLive));
  } catch (err) {
    return res.status(500).json({ message: 'List seller lives failed', error: err.message });
  }
}

async function getLive(req, res) {
  try {
    const live = await LiveSession.findById(req.params.liveId);
    if (!live) return res.status(404).json({ message: 'Live not found' });
    return res.json(normalizeLive(live));
  } catch (err) {
    return res.status(500).json({ message: 'Get live failed', error: err.message });
  }
}

async function startLive(req, res) {
  try {
    const live = await LiveSession.findById(req.params.liveId);
    if (!live) return res.status(404).json({ message: 'Live not found' });
    if (!canManageLive(req, live)) return res.status(403).json({ message: 'Forbidden' });
    if (['ended', 'banned'].includes(live.status)) {
      return res.status(409).json({ message: `Cannot start a ${live.status} live` });
    }

    live.status = 'starting';
    live.playbackUrl = '';
    live.hlsPlaybackUrl = '';
    live.hlsPlaylistPath = '';
    live.egressId = '';
    live.egressStatus = '';
    await live.save();
    await ensureRoom(live.providerRoomId);
    if (process.env.LIVEKIT_AI_COHOST_IN_ROOM_ENABLED === 'true') {
      dispatchAiCohost(live.providerRoomId, {
        liveId: String(live._id),
        shopId: live.shopId,
        sellerId: live.sellerId,
        activePinnedProductId: live.activePinnedProductId || null
      }).catch((err) => {
        console.error('AI co-host dispatch failed', err.message);
        publishEvent('live.ai_cohost.dispatch_failed.v1', {
          liveId: String(live._id),
          shopId: live.shopId,
          providerRoomId: live.providerRoomId,
          error: err.message
        }).catch(() => {});
      });
    }

    live.status = 'live';
    live.startedAt = live.startedAt || new Date();
    await live.save();

    await publishEvent('live.session.started.v1', {
      liveId: String(live._id),
      shopId: live.shopId,
      sellerId: live.sellerId,
      providerRoomId: live.providerRoomId
    });

    const token = await createToken({
      roomName: live.providerRoomId,
      identity: `seller:${requester(req).userId}`,
      displayName: req.body?.displayName || 'Seller',
      role: 'seller'
    });

    return res.json({ live: normalizeLive(live), livekit: { url: publicUrl, token, roomName: live.providerRoomId } });
  } catch (err) {
    return res.status(500).json({ message: 'Start live failed', error: err.message });
  }
}

async function endLive(req, res) {
  try {
    const live = await LiveSession.findById(req.params.liveId);
    if (!live) return res.status(404).json({ message: 'Live not found' });
    if (!canManageLive(req, live)) return res.status(403).json({ message: 'Forbidden' });

    live.status = 'ending';
    await live.save();
    await stopHlsEgress(live.egressId).catch((err) => {
      console.error('LiveKit HLS egress stop failed', err.message);
      publishEvent('live.hls_egress.stop_failed.v1', {
        liveId: String(live._id),
        shopId: live.shopId,
        providerRoomId: live.providerRoomId,
        egressId: live.egressId,
        error: err.message
      }).catch(() => {});
    });
    await endRoom(live.providerRoomId);

    live.status = 'ended';
    live.egressStatus = live.egressId ? 'ended' : live.egressStatus;
    live.endedAt = new Date();
    await live.save();

    await publishEvent('live.session.ended.v1', {
      liveId: String(live._id),
      shopId: live.shopId,
      sellerId: live.sellerId
    });

    return res.json(normalizeLive(live));
  } catch (err) {
    return res.status(500).json({ message: 'End live failed', error: err.message });
  }
}

async function startHlsPlayback(req, res) {
  try {
    const live = await LiveSession.findById(req.params.liveId);
    if (!live) return res.status(404).json({ message: 'Live not found' });
    if (!canManageLive(req, live)) return res.status(403).json({ message: 'Forbidden' });
    if (!['starting', 'live'].includes(live.status)) {
      return res.status(409).json({ message: 'Live must be active before starting HLS egress' });
    }

    if (live.egressId && !['ended', 'failed', 'aborted'].includes(String(live.egressStatus || '').toLowerCase())) {
      await stopHlsEgress(live.egressId).catch(() => null);
    }

    await ensureRoom(live.providerRoomId);
    const hlsInfo = await startHlsEgress(live.providerRoomId, String(live._id), `seller:${live.sellerId}`);
    if (!hlsInfo) {
      live.egressStatus = 'disabled';
      await live.save();
      return res.json({ live: normalizeLive(live), hls: null });
    }

    live.hlsPlaybackUrl = hlsInfo.hlsPlaybackUrl;
    live.hlsPlaylistPath = hlsInfo.hlsPlaylistPath;
    live.egressId = hlsInfo.egressId;
    live.egressStatus = hlsInfo.egressStatus;
    live.playbackUrl = hlsInfo.hlsPlaybackUrl;
    await live.save();

    await publishEvent('live.hls_egress.started.v1', {
      liveId: String(live._id),
      shopId: live.shopId,
      providerRoomId: live.providerRoomId,
      egressId: live.egressId,
      hlsPlaybackUrl: live.hlsPlaybackUrl
    });

    return res.json({ live: normalizeLive(live), hls: hlsInfo });
  } catch (err) {
    await publishEvent('live.hls_egress.start_failed.v1', {
      liveId: req.params.liveId,
      error: err.message
    }).catch(() => {});
    return res.status(500).json({ message: 'Start HLS egress failed', error: err.message });
  }
}

async function createSellerToken(req, res) {
  try {
    const live = await LiveSession.findById(req.params.liveId);
    if (!live) return res.status(404).json({ message: 'Live not found' });
    if (!canManageLive(req, live)) return res.status(403).json({ message: 'Forbidden' });
    await ensureRoom(live.providerRoomId);
    const token = await createToken({
      roomName: live.providerRoomId,
      identity: `seller:${requester(req).userId}`,
      displayName: req.body?.displayName || 'Seller',
      role: 'seller'
    });
    return res.json({ url: publicUrl, token, roomName: live.providerRoomId });
  } catch (err) {
    return res.status(500).json({ message: 'Create seller token failed', error: err.message });
  }
}

async function createViewerToken(req, res) {
  try {
    const live = await LiveSession.findById(req.params.liveId);
    if (!live) return res.status(404).json({ message: 'Live not found' });
    if (live.status !== 'live') return res.status(409).json({ message: 'Live is not active' });
    const current = requester(req);
    const identity = current.userId ? `buyer:${current.userId}` : `guest:${Date.now()}`;
    const token = await createToken({
      roomName: live.providerRoomId,
      identity,
      displayName: req.body?.displayName || 'Viewer',
      role: 'buyer'
    });
    return res.json({ url: publicUrl, token, roomName: live.providerRoomId });
  } catch (err) {
    return res.status(500).json({ message: 'Create viewer token failed', error: err.message });
  }
}

function hlsViewerIdentity(req) {
  const current = requester(req);
  if (current.userId && current.role === 'buyer') return `buyer:${current.userId}`;
  const rawViewerId = String(req.body?.viewerId || req.headers['x-live-viewer-id'] || '').trim();
  const safeViewerId = rawViewerId.replace(/[^a-zA-Z0-9:_-]/g, '').slice(0, 80);
  return `hls:${safeViewerId || req.ip || Date.now()}`;
}

async function recordViewerHeartbeat(req, res) {
  try {
    const live = await LiveSession.findById(req.params.liveId);
    if (!live) return res.status(404).json({ message: 'Live not found' });
    if (!['starting', 'live'].includes(live.status)) {
      return res.json({ liveId: String(live._id), viewerCount: 0, status: live.status });
    }
    const identity = hlsViewerIdentity(req);
    const viewerCount = await markViewerHeartbeat(String(live._id), identity);
    return res.json({ liveId: String(live._id), viewerCount, status: live.status });
  } catch (err) {
    return res.status(500).json({ message: 'Viewer heartbeat failed', error: err.message });
  }
}

async function getViewerCount(req, res) {
  try {
    const live = await LiveSession.findById(req.params.liveId);
    if (!live) return res.status(404).json({ message: 'Live not found' });
    const viewerCount = await countActiveViewers(String(live._id));
    return res.json({ liveId: String(live._id), viewerCount, status: live.status });
  } catch (err) {
    return res.status(500).json({ message: 'Get viewer count failed', error: err.message });
  }
}

async function listPinnedProducts(req, res) {
  try {
    const list = await LivePinnedProduct.find({ liveId: req.params.liveId, unpinnedAt: null }).sort({ sortOrder: 1 });
    return res.json(list.map(normalizePinned));
  } catch (err) {
    return res.status(500).json({ message: 'List pinned products failed', error: err.message });
  }
}

async function pinProduct(req, res) {
  try {
    const live = await LiveSession.findById(req.params.liveId);
    if (!live) return res.status(404).json({ message: 'Live not found' });
    if (!canManageLive(req, live)) return res.status(403).json({ message: 'Forbidden' });

    const productId = req.body?.productId;
    if (!productId) return res.status(400).json({ message: 'productId is required' });
    const product = await getProduct(productId, {
      'x-user-role': requester(req).role,
      'x-user-id': requester(req).userId,
      'x-user-shop-id': requester(req).shopId
    });
    if (String(product.shopId) !== String(live.shopId)) {
      return res.status(400).json({ message: 'Product does not belong to this shop' });
    }

    const image = Array.isArray(product.images) ? product.images[0] : product.imageUrl;
    const pinned = await LivePinnedProduct.findOneAndUpdate(
      { liveId: String(live._id), productId: String(productId) },
      {
        liveId: String(live._id),
        shopId: live.shopId,
        productId: String(productId),
        nameSnapshot: product.name,
        priceSnapshot: Number(product.price || 0),
        imageSnapshot: image || '',
        stockSnapshot: Number(product.quantity || 0),
        sortOrder: Number(req.body?.sortOrder || 0),
        isActive: req.body?.isActive !== false,
        pinnedAt: new Date(),
        unpinnedAt: null
      },
      { upsert: true, new: true, setDefaultsOnInsert: true }
    );

    if (pinned.isActive) {
      await LivePinnedProduct.updateMany(
        { liveId: String(live._id), productId: { $ne: String(productId) } },
        { isActive: false }
      );
      live.activePinnedProductId = String(productId);
      await live.save();
      await publishEvent('live.product.active_changed.v1', {
        liveId: String(live._id),
        shopId: live.shopId,
        productId: String(productId),
        changedBy: requester(req).userId
      });
    }

    await publishEvent('live.product.pinned.v1', {
      liveId: String(live._id),
      shopId: live.shopId,
      productId: String(productId)
    });

    return res.status(201).json(normalizePinned(pinned));
  } catch (err) {
    return res.status(500).json({ message: 'Pin product failed', error: err.message });
  }
}

async function setActiveProduct(req, res) {
  try {
    const live = await LiveSession.findById(req.params.liveId);
    if (!live) return res.status(404).json({ message: 'Live not found' });
    if (!canManageLive(req, live)) return res.status(403).json({ message: 'Forbidden' });
    const productId = req.body?.productId;
    const pinned = await LivePinnedProduct.findOne({ liveId: String(live._id), productId, unpinnedAt: null });
    if (!pinned) return res.status(404).json({ message: 'Pinned product not found' });

    await LivePinnedProduct.updateMany({ liveId: String(live._id) }, { isActive: false });
    pinned.isActive = true;
    await pinned.save();
    live.activePinnedProductId = String(productId);
    await live.save();

    await publishEvent('live.product.active_changed.v1', {
      liveId: String(live._id),
      shopId: live.shopId,
      productId: String(productId),
      changedBy: requester(req).userId
    });

    return res.json(normalizePinned(pinned));
  } catch (err) {
    return res.status(500).json({ message: 'Set active product failed', error: err.message });
  }
}

async function unpinProduct(req, res) {
  try {
    const live = await LiveSession.findById(req.params.liveId);
    if (!live) return res.status(404).json({ message: 'Live not found' });
    if (!canManageLive(req, live)) return res.status(403).json({ message: 'Forbidden' });
    const productId = req.params.productId;
    const pinned = await LivePinnedProduct.findOne({ liveId: String(live._id), productId });
    if (!pinned) return res.status(404).json({ message: 'Pinned product not found' });
    pinned.unpinnedAt = new Date();
    pinned.isActive = false;
    await pinned.save();
    if (String(live.activePinnedProductId) === String(productId)) {
      live.activePinnedProductId = null;
      await live.save();
    }
    await publishEvent('live.product.unpinned.v1', {
      liveId: String(live._id),
      shopId: live.shopId,
      productId: String(productId)
    });
    return res.json({ message: 'Product unpinned' });
  } catch (err) {
    return res.status(500).json({ message: 'Unpin product failed', error: err.message });
  }
}

async function handleLivekitWebhook(req, res) {
  try {
    const authHeader = req.headers.authorization || '';
    const event = await receiveWebhook(req.rawBody || JSON.stringify(req.body || {}), authHeader);
    await publishEvent('live.provider.webhook.v1', { provider: 'livekit', payload: event }, event?.room?.name);
    if ((event?.event === 'participant_joined' || event?.event === 'participant_left') && event?.room?.name) {
      const live = await LiveSession.findOne({ providerRoomId: event.room.name });
      const identity = event?.participant?.identity || '';
      if (live && event.event === 'participant_joined') {
        const viewerCount = await markViewerJoined(String(live._id), identity);
        await publishEvent('live.viewer.joined.v1', {
          liveId: String(live._id),
          shopId: live.shopId,
          identity,
          viewerCount
        });
      }
      if (live && event.event === 'participant_left') {
        const viewerCount = await markViewerLeft(String(live._id), identity);
        await publishEvent('live.viewer.left.v1', {
          liveId: String(live._id),
          shopId: live.shopId,
          identity,
          viewerCount
        });
      }
    }
    if (event?.event === 'room_finished' && event?.room?.name) {
      const live = await LiveSession.findOne({ providerRoomId: event.room.name, status: { $in: ['starting', 'live', 'paused'] } });
      if (live) {
        live.status = 'ended';
        live.endedAt = live.endedAt || new Date();
        await live.save();
        await publishEvent('live.session.ended.v1', {
          liveId: String(live._id),
          shopId: live.shopId,
          sellerId: live.sellerId,
          source: 'livekit_webhook'
        });
      }
    }
    return res.json({ ok: true });
  } catch (err) {
    return res.status(401).json({ message: 'Invalid LiveKit webhook', error: err.message });
  }
}

module.exports = {
  createLive,
  listLives,
  listSellerLives,
  getLive,
  startLive,
  startHlsPlayback,
  endLive,
  createSellerToken,
  createViewerToken,
  recordViewerHeartbeat,
  getViewerCount,
  listPinnedProducts,
  pinProduct,
  setActiveProduct,
  unpinProduct,
  handleLivekitWebhook
};
