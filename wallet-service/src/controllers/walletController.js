const { getWallet, topupWallet, listTransactions } = require('../services/walletService');
const {
  getShopBalance,
  listShopLedger,
  settleOrderToShop,
  requestPayout,
  completePayout,
  failPayout,
  listPayouts
} = require('../services/shopFinanceService');

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

async function getShopFinanceBalance(req, res) {
  try {
    const { shopId } = req.params;
    if (!shopId) return res.status(400).json({ message: 'shopId is required' });
    return res.json(await getShopBalance(shopId));
  } catch (err) {
    return res.status(500).json({ message: 'Get shop balance failed', error: err.message });
  }
}

async function getShopFinanceLedger(req, res) {
  try {
    const { shopId } = req.params;
    if (!shopId) return res.status(400).json({ message: 'shopId is required' });
    return res.json(await listShopLedger(shopId, Number(req.query.limit || 50)));
  } catch (err) {
    return res.status(500).json({ message: 'Get shop ledger failed', error: err.message });
  }
}

async function settleShopOrder(req, res) {
  try {
    const { shopId } = req.params;
    const amount = Number(req.body?.amount);
    if (!shopId) return res.status(400).json({ message: 'shopId is required' });
    if (!Number.isFinite(amount) || amount <= 0) {
      return res.status(400).json({ message: 'amount must be greater than 0' });
    }
    const result = await settleOrderToShop({
      shopId,
      orderId: req.body?.orderId,
      amount,
      referenceId: req.body?.referenceId,
      metadata: req.body?.metadata || {},
      sagaId: req.body?.sagaId || null,
      correlationId: req.headers['x-correlation-id'] || req.body?.correlationId || null
    });
    return res.status(result.reused ? 200 : 201).json(result);
  } catch (err) {
    return res.status(500).json({ message: 'Settle shop order failed', error: err.message });
  }
}

async function withdrawShopBalance(req, res) {
  try {
    const { shopId } = req.params;
    const amount = Number(req.body?.amount);
    if (!shopId) return res.status(400).json({ message: 'shopId is required' });
    if (!Number.isFinite(amount) || amount <= 0) {
      return res.status(400).json({ message: 'amount must be greater than 0' });
    }
    const idempotencyKey = req.headers['idempotency-key'] || req.body?.referenceId || req.body?.idempotencyKey;
    const result = await requestPayout({
      shopId,
      amount,
      bankAccount: req.body?.bankAccount || {},
      referenceId: idempotencyKey,
      metadata: req.body?.metadata || {},
      sagaId: req.body?.sagaId || null,
      correlationId: req.headers['x-correlation-id'] || req.body?.correlationId || null
    });
    return res.status(result.reused ? 200 : 201).json(result);
  } catch (err) {
    const status = String(err.message || '').startsWith('insufficient_balance') ? 409 : 500;
    return res.status(status).json({ message: 'Withdraw shop balance failed', error: err.message });
  }
}

async function completeShopPayout(req, res) {
  try {
    const result = await completePayout(req.params.referenceId, req.body?.metadata || {});
    return res.status(result.ok ? 200 : 404).json(result);
  } catch (err) {
    return res.status(500).json({ message: 'Complete payout failed', error: err.message });
  }
}

async function failShopPayout(req, res) {
  try {
    const result = await failPayout(req.params.referenceId, req.body?.reason, req.body?.metadata || {});
    return res.status(result.ok ? 200 : 404).json(result);
  } catch (err) {
    return res.status(500).json({ message: 'Fail payout failed', error: err.message });
  }
}

async function getShopPayouts(req, res) {
  try {
    const { shopId } = req.params;
    if (!shopId) return res.status(400).json({ message: 'shopId is required' });
    return res.json(await listPayouts(shopId, Number(req.query.limit || 50)));
  } catch (err) {
    return res.status(500).json({ message: 'Get payouts failed', error: err.message });
  }
}

module.exports = {
  getWalletByUser,
  topup,
  getWalletTransactions,
  getShopFinanceBalance,
  getShopFinanceLedger,
  settleShopOrder,
  withdrawShopBalance,
  completeShopPayout,
  failShopPayout,
  getShopPayouts
};
