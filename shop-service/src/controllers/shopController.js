const Shop = require('../models/Shop');

const INVOICE_REQUEST_MODES = new Set(['checkout_form', 'chat_required', 'off']);

function cleanText(value, maxLength) {
  if (typeof value !== 'string') return '';
  return value.trim().slice(0, maxLength);
}

function canAccessShop(req, shop) {
  const actorRole = req.headers['x-user-role'] || '';
  const actorUserId = req.headers['x-user-id'] || '';
  const actorShopId = req.headers['x-user-shop-id'] || '';
  if (actorRole === 'admin') return true;
  if (actorRole !== 'seller') return false;
  return String(shop?._id || shop?.id) === String(actorShopId) || String(shop?.ownerId) === String(actorUserId);
}

async function createShop(req, res) {
  try {
    const {
      name,
      ownerId,
      description,
      invoiceEligible,
      invoiceRequestMode,
      legalEntityType,
      taxCode,
      invoiceProvider
    } = req.body;
    if (!name || !ownerId) {
      return res.status(400).json({ message: 'name and ownerId are required' });
    }
    const normalizedMode = ['checkout_form', 'chat_required', 'off'].includes(invoiceRequestMode)
      ? invoiceRequestMode
      : 'chat_required';
    const normalizedEntityType = ['company', 'business_household', 'individual', 'unknown'].includes(legalEntityType)
      ? legalEntityType
      : 'unknown';
    const shop = await Shop.create({
      name,
      ownerId,
      description,
      invoiceEligible: invoiceEligible !== false,
      invoiceRequestMode: normalizedMode,
      legalEntityType: normalizedEntityType,
      taxCode: typeof taxCode === 'string' ? taxCode.trim().slice(0, 32) : '',
      invoiceProvider: typeof invoiceProvider === 'string' ? invoiceProvider.trim().slice(0, 80) : '',
      invoiceFeatureStatus: normalizedMode === 'off' ? 'off' : 'active'
    });
    return res.status(201).json(shop);
  } catch (err) {
    return res.status(500).json({ message: 'Create shop failed', error: err.message });
  }
}

async function getShops(req, res) {
  try {
    const shops = await Shop.find();
    return res.json(shops);
  } catch (err) {
    return res.status(500).json({ message: 'Get shops failed', error: err.message });
  }
}

async function getShopById(req, res) {
  try {
    const shop = await Shop.findById(req.params.id);
    if (!shop) {
      return res.status(404).json({ message: 'Shop not found' });
    }
    return res.json(shop);
  } catch (err) {
    return res.status(500).json({ message: 'Get shop failed', error: err.message });
  }
}

async function getInvoiceFeature(req, res) {
  try {
    const shop = await Shop.findById(req.params.id);
    if (!shop) return res.status(404).json({ message: 'Shop not found' });
    if (!canAccessShop(req, shop)) return res.status(403).json({ message: 'Forbidden' });
    return res.json({
      shopId: shop._id,
      invoiceEligible: shop.invoiceEligible,
      invoiceRequestMode: shop.invoiceRequestMode,
      invoiceFeatureStatus: shop.invoiceFeatureStatus,
      legalEntityType: shop.legalEntityType,
      taxCode: shop.taxCode,
      invoiceProvider: shop.invoiceProvider,
      requests: (shop.invoiceFeatureRequests || []).slice().sort((a, b) => new Date(b.requestedAt) - new Date(a.requestedAt))
    });
  } catch (err) {
    return res.status(500).json({ message: 'Get invoice feature failed', error: err.message });
  }
}

async function createInvoiceFeatureRequest(req, res) {
  try {
    const shop = await Shop.findById(req.params.id);
    if (!shop) return res.status(404).json({ message: 'Shop not found' });
    if (!canAccessShop(req, shop)) return res.status(403).json({ message: 'Forbidden' });

    const requestedMode = req.body?.requestedMode;
    if (!INVOICE_REQUEST_MODES.has(requestedMode)) {
      return res.status(400).json({ message: 'requestedMode is invalid' });
    }
    const pending = (shop.invoiceFeatureRequests || []).find((item) => item.status === 'pending');
    if (pending) {
      return res.status(409).json({ message: 'Shop already has a pending invoice feature request' });
    }
    if (requestedMode === shop.invoiceRequestMode) {
      return res.status(400).json({ message: 'Requested mode is already active' });
    }

    shop.invoiceFeatureRequests.push({
      requestedMode,
      reason: cleanText(req.body?.reason, 500),
      requestedBy: req.headers['x-user-id'] || '',
      status: 'pending',
      requestedAt: new Date()
    });
    shop.invoiceFeatureStatus = 'pending_review';
    await shop.save();
    return res.status(201).json(shop.invoiceFeatureRequests[shop.invoiceFeatureRequests.length - 1]);
  } catch (err) {
    return res.status(500).json({ message: 'Create invoice feature request failed', error: err.message });
  }
}

async function getAdminInvoiceFeatureRequests(req, res) {
  try {
    const shops = await Shop.find({ 'invoiceFeatureRequests.0': { $exists: true } }).sort({ updatedAt: -1 });
    const requests = [];
    shops.forEach((shop) => {
      (shop.invoiceFeatureRequests || []).forEach((request) => {
        requests.push({
          ...request.toObject(),
          shopId: shop._id,
          shopName: shop.name,
          ownerId: shop.ownerId,
          currentMode: shop.invoiceRequestMode,
          invoiceFeatureStatus: shop.invoiceFeatureStatus,
          legalEntityType: shop.legalEntityType,
          taxCode: shop.taxCode,
          invoiceProvider: shop.invoiceProvider
        });
      });
    });
    requests.sort((a, b) => new Date(b.requestedAt) - new Date(a.requestedAt));
    return res.json(requests);
  } catch (err) {
    return res.status(500).json({ message: 'Get invoice feature requests failed', error: err.message });
  }
}

async function reviewInvoiceFeatureRequest(req, res) {
  try {
    const requestId = req.params.requestId;
    const action = req.body?.action;
    if (!['approve', 'reject'].includes(action)) {
      return res.status(400).json({ message: 'action must be approve or reject' });
    }
    const shop = await Shop.findOne({ 'invoiceFeatureRequests._id': requestId });
    if (!shop) return res.status(404).json({ message: 'Request not found' });
    const request = shop.invoiceFeatureRequests.id(requestId);
    if (!request) return res.status(404).json({ message: 'Request not found' });
    if (request.status !== 'pending') {
      return res.status(400).json({ message: 'Request is already reviewed' });
    }

    request.status = action === 'approve' ? 'approved' : 'rejected';
    request.adminNote = cleanText(req.body?.adminNote, 500);
    request.reviewedBy = req.headers['x-user-id'] || '';
    request.reviewedAt = new Date();

    if (action === 'approve') {
      shop.invoiceRequestMode = request.requestedMode;
      shop.invoiceEligible = request.requestedMode !== 'off';
      shop.invoiceFeatureStatus = request.requestedMode === 'off' ? 'off' : 'active';
    } else {
      shop.invoiceFeatureStatus = 'rejected';
    }

    await shop.save();
    return res.json({
      ...request.toObject(),
      shopId: shop._id,
      shopName: shop.name,
      currentMode: shop.invoiceRequestMode,
      invoiceFeatureStatus: shop.invoiceFeatureStatus
    });
  } catch (err) {
    return res.status(500).json({ message: 'Review invoice feature request failed', error: err.message });
  }
}

module.exports = {
  createShop,
  getShops,
  getShopById,
  getInvoiceFeature,
  createInvoiceFeatureRequest,
  getAdminInvoiceFeatureRequests,
  reviewInvoiceFeatureRequest
};
