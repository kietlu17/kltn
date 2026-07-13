const { getWallet, topupWallet, listTransactions } = require('../services/walletService');

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
    const idempotencyKey = req.headers['idempotency-key'] || req.body?.idempotencyKey || '';
    const result = await topupWallet(
      userId,
      amount,
      { source: req.body?.source || 'api_topup' },
      {
        idempotencyKey: idempotencyKey || undefined,
        reason: 'manual_topup',
        correlationId: req.headers['x-correlation-id'] || null
      }
    );
    return res.status(result.reused ? 200 : 201).json(result);
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

module.exports = { getWalletByUser, topup, getWalletTransactions };
