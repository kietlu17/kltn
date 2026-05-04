const {
  getWallet,
  topupWallet,
  listTransactions,
  recordExternalPaymentForOrder
} = require('../services/walletService');
const {
  createSepayTopupRequest,
  createSepayOrderRequest,
  getSepayRequestById,
  processSepayWebhook,
  markOrderRequestEventPublished
} = require('../services/sepayService');
const { publishPaymentEvent } = require('../kafka/producer');

async function getWalletByUser(req, res) {
  try {
    const userId = req.params.userId;
    if (!userId) return res.status(400).json({ message: 'userId is required' });
    const wallet = await getWallet(userId);
    return res.json(wallet);
  } catch (err) {
    return res.status(500).json({ message: 'Get wallet failed', error: err.message });
  }
}

async function topup(req, res) {
  try {
    const userId = req.params.userId;
    const amount = Number(req.body?.amount);
    if (!userId) return res.status(400).json({ message: 'userId is required' });
    if (!Number.isFinite(amount) || amount <= 0) {
      return res.status(400).json({ message: 'amount must be greater than 0' });
    }
    const result = await topupWallet(userId, amount, {
      source: req.body?.source || 'api_topup'
    });
    return res.status(201).json(result);
  } catch (err) {
    return res.status(500).json({ message: 'Topup wallet failed', error: err.message });
  }
}

async function getWalletTransactions(req, res) {
  try {
    const userId = req.params.userId;
    if (!userId) return res.status(400).json({ message: 'userId is required' });
    const limit = Number(req.query.limit || 50);
    const rows = await listTransactions(userId, limit);
    return res.json(rows);
  } catch (err) {
    return res.status(500).json({ message: 'Get wallet transactions failed', error: err.message });
  }
}

async function createSepayTopupQr(req, res) {
  try {
    const userId = req.params.userId;
    const amount = Number(req.body?.amount);
    if (!userId) return res.status(400).json({ message: 'userId is required' });
    if (!Number.isFinite(amount) || amount <= 0) {
      return res.status(400).json({ message: 'amount must be greater than 0' });
    }
    const qr = await createSepayTopupRequest({ userId, amount });
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
    if (!Number.isFinite(amount) || amount <= 0) {
      return res.status(400).json({ message: 'amount must be greater than 0' });
    }
    if (actorRole === 'buyer' && String(actorUserId) !== String(userId)) {
      return res.status(403).json({ message: 'Forbidden' });
    }
    const qr = await createSepayOrderRequest({ orderId, userId, amount });
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
    if (actorRole === 'buyer' && String(actorUserId) !== String(request.userId)) {
      return res.status(403).json({ message: 'Forbidden' });
    }
    return res.json(request);
  } catch (err) {
    return res.status(500).json({ message: 'Get SePay request failed', error: err.message });
  }
}

async function receiveSepayWebhook(req, res) {
  try {
    const result = await processSepayWebhook(req.body || {}, req.headers || {});

    if (result?.paid && result?.request?.purpose === 'order_payment' && result?.request?.orderId) {
      await recordExternalPaymentForOrder({
        orderId: result.request.orderId,
        userId: result.request.userId,
        amount: result.request.amount,
        paymentMethod: 'bank_transfer',
        metadata: {
          requestCode: result.request.requestCode
        }
      });
    }

    if (result?.shouldPublishOrderEvent && result?.request?.orderId) {
      await publishPaymentEvent('payment.succeeded', {
        orderId: result.request.orderId,
        status: 'paid',
        paymentMethod: 'bank_transfer',
        userId: result.request.userId || null,
        totalPrice: result.request.amount,
        eventAt: new Date().toISOString()
      });
      await markOrderRequestEventPublished(result.request.id);
    }

    return res.status(200).json({
      success: true,
      duplicate: Boolean(result?.duplicate),
      matched: Boolean(result?.matched),
      paid: Boolean(result?.paid)
    });
  } catch (err) {
    const status = err.status || 500;
    return res.status(status).json({ success: false, message: err.message || 'Webhook handling failed' });
  }
}

module.exports = {
  getWalletByUser,
  topup,
  getWalletTransactions,
  createSepayTopupQr,
  createSepayOrderQr,
  getSepayRequestStatus,
  receiveSepayWebhook
};
