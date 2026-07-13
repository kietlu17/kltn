const {
  createSepayTopupRequest,
  createSepayOrderRequest,
  getSepayRequestById,
  processSepayWebhook
} = require('../services/sepayService');

async function createSepayTopupQr(req, res) {
  try {
    const userId = req.params.userId;
    const amount = Number(req.body?.amount);
    if (!userId) return res.status(400).json({ message: 'userId is required' });
    if (!Number.isFinite(amount) || amount <= 0) return res.status(400).json({ message: 'amount must be greater than 0' });
    const qr = await createSepayTopupRequest({
      userId,
      amount,
      correlationId: req.headers['x-correlation-id'] || null
    });
    return res.status(201).json(qr);
  } catch (err) {
    const status = err.status || 500;
    return res.status(status).json({ message: 'Create SePay topup QR failed', error: err.message });
  }
}

async function createSepayOrderQr(req, res) {
  try {
    const actorRole = req.headers['x-user-role'] || '';
    const actorUserId = req.headers['x-user-id'] || '';
    const orderId = Number(req.params.orderId);
    const amount = Number(req.body?.amount);
    const userId = String(req.body?.userId || '');

    if (!Number.isFinite(orderId)) return res.status(400).json({ message: 'orderId is invalid' });
    if (!userId) return res.status(400).json({ message: 'userId is required' });
    if (!Number.isFinite(amount) || amount <= 0) return res.status(400).json({ message: 'amount must be greater than 0' });
    if (actorRole === 'buyer' && String(actorUserId) !== String(userId)) return res.status(403).json({ message: 'Forbidden' });

    const qr = await createSepayOrderRequest({
      orderId,
      userId,
      amount,
      correlationId: req.headers['x-correlation-id'] || null
    });
    return res.status(201).json(qr);
  } catch (err) {
    const status = err.status || 500;
    return res.status(status).json({ message: 'Create SePay order QR failed', error: err.message });
  }
}

async function getSepayRequestStatus(req, res) {
  try {
    const id = Number(req.params.id);
    if (!Number.isFinite(id)) return res.status(400).json({ message: 'id is invalid' });
    const request = await getSepayRequestById(id);
    if (!request) return res.status(404).json({ message: 'SePay request not found' });

    const actorRole = req.headers['x-user-role'] || '';
    const actorUserId = req.headers['x-user-id'] || '';
    if (actorRole === 'buyer' && String(actorUserId) !== String(request.userId)) return res.status(403).json({ message: 'Forbidden' });
    return res.json(request);
  } catch (err) {
    return res.status(500).json({ message: 'Get SePay request failed', error: err.message });
  }
}

async function receiveSepayWebhook(req, res) {
  try {
    const result = await processSepayWebhook(req.body || {}, req.headers || {});
    return res.status(200).json({
      success: true,
      duplicate: Boolean(result?.duplicate),
      matched: Boolean(result?.matched),
      paid: Boolean(result?.paid),
      reason: result?.reason || null
    });
  } catch (err) {
    const status = err.status || 500;
    return res.status(status).json({ success: false, message: err.message || 'Webhook handling failed' });
  }
}

module.exports = {
  createSepayTopupQr,
  createSepayOrderQr,
  getSepayRequestStatus,
  receiveSepayWebhook
};
