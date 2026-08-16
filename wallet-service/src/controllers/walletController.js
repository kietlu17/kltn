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
const {
  processDueSettlements,
  listSettlementJobs,
  recordCodRemittance
} = require('../services/settlementService');
const {
  requestUserWithdrawal,
  completeUserWithdrawal,
  failUserWithdrawal,
  listUserWithdrawals
} = require('../services/userWithdrawalService');
const { getPlatformWallet } = require('../services/platformFinanceService');

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

async function getPlatformFinanceWallet(req, res) {
  try {
    return res.json(await getPlatformWallet());
  } catch (err) {
    return res.status(500).json({ message: 'Get platform wallet failed', error: err.message });
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

async function getSettlementJobs(req, res) {
  try {
    return res.json(await listSettlementJobs(req.query.shopId, Number(req.query.limit || 50)));
  } catch (err) {
    return res.status(500).json({ message: 'Get settlement jobs failed', error: err.message });
  }
}

async function runSettlements(req, res) {
  try {
    const result = await processDueSettlements({
      force: req.query.force === 'true' || req.body?.force === true,
      limit: Number(req.query.limit || req.body?.limit || 50)
    });
    return res.json({ ok: true, settled: result.length, jobs: result });
  } catch (err) {
    return res.status(500).json({ message: 'Run settlements failed', error: err.message });
  }
}

async function receiveCodRemittance(req, res) {
  try {
    const amount = Number(req.body?.amount);
    if (!Number.isFinite(amount) || amount <= 0) {
      return res.status(400).json({ message: 'amount must be greater than 0' });
    }
    const result = await recordCodRemittance({
      orderId: req.body?.orderId,
      shopId: req.body?.shopId,
      amount,
      carrier: req.body?.carrier || 'mock_carrier',
      referenceId: req.headers['idempotency-key'] || req.body?.referenceId || req.body?.idempotencyKey || null,
      metadata: req.body?.metadata || {},
      sagaId: req.body?.sagaId || null,
      correlationId: req.headers['x-correlation-id'] || req.body?.correlationId || null
    });
    return res.status(result.reused ? 200 : 201).json(result);
  } catch (err) {
    const message = String(err.message || '');
    const status = message.includes('not_found') ? 404 : (message.includes('amount_mismatch') || message.includes('not_payable') ? 409 : 500);
    return res.status(status).json({ message: 'Record COD remittance failed', error: err.message });
  }
}

async function withdrawUserBalance(req, res) {
  try {
    const { userId } = req.params;
    const amount = Number(req.body?.amount);
    if (!userId) return res.status(400).json({ message: 'userId is required' });
    if (!Number.isFinite(amount) || amount <= 0) {
      return res.status(400).json({ message: 'amount must be greater than 0' });
    }
    const idempotencyKey = req.headers['idempotency-key'] || req.body?.referenceId || req.body?.idempotencyKey;
    const result = await requestUserWithdrawal({
      userId,
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
    return res.status(status).json({ message: 'Withdraw user balance failed', error: err.message });
  }
}

async function getUserWithdrawals(req, res) {
  try {
    const { userId } = req.params;
    if (!userId) return res.status(400).json({ message: 'userId is required' });
    return res.json(await listUserWithdrawals(userId, Number(req.query.limit || 50)));
  } catch (err) {
    return res.status(500).json({ message: 'Get user withdrawals failed', error: err.message });
  }
}

async function completeUserWithdrawalRequest(req, res) {
  try {
    const result = await completeUserWithdrawal(req.params.referenceId, req.body?.metadata || {});
    return res.status(result.ok ? 200 : 404).json(result);
  } catch (err) {
    return res.status(500).json({ message: 'Complete user withdrawal failed', error: err.message });
  }
}

async function failUserWithdrawalRequest(req, res) {
  try {
    const result = await failUserWithdrawal(req.params.referenceId, req.body?.reason, req.body?.metadata || {});
    return res.status(result.ok ? 200 : 404).json(result);
  } catch (err) {
    return res.status(500).json({ message: 'Fail user withdrawal failed', error: err.message });
  }
}

module.exports = {
  getWalletByUser,
  topup,
  getWalletTransactions,
  getPlatformFinanceWallet,
  getShopFinanceBalance,
  getShopFinanceLedger,
  settleShopOrder,
  withdrawShopBalance,
  completeShopPayout,
  failShopPayout,
  getShopPayouts,
  getSettlementJobs,
  runSettlements,
  receiveCodRemittance,
  withdrawUserBalance,
  getUserWithdrawals,
  completeUserWithdrawalRequest,
  failUserWithdrawalRequest
};
