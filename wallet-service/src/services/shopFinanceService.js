const { sequelize } = require('../config/db');
const { Op } = require('sequelize');
const { LedgerTransaction, PayoutRequest, SettlementJob } = require('../models');
const {
  toMoney,
  getSystemAccount,
  getShopBalanceAccount,
  getShopPayoutPendingAccount,
  getAccountSnapshot,
  listAccountLedger,
  transfer
} = require('./accountLedgerService');

async function getShopBalance(shopId) {
  return sequelize.transaction(async (transaction) => {
    const sellerAccount = await getShopBalanceAccount(shopId, transaction);
    const payoutPendingAccount = await getShopPayoutPendingAccount(shopId, transaction);
    const sellerBalance = await getAccountSnapshot(sellerAccount, transaction);
    const payoutPending = await getAccountSnapshot(payoutPendingAccount, transaction);
    const pendingJobs = await SettlementJob.findAll({
      where: {
        shop_id: String(shopId),
        status: { [Op.in]: ['pending', 'awaiting_remittance'] }
      },
      transaction
    });
    const completedPayouts = await PayoutRequest.findAll({
      where: {
        shop_id: String(shopId),
        status: 'completed'
      },
      transaction
    });
    const completedPayoutAmount = completedPayouts.reduce((sum, payout) => toMoney(sum + Number(payout.amount || 0)), 0);
    const now = new Date();
    const incomingSettlements = pendingJobs.reduce(
      (summary, job) => {
        const amount = toMoney(job.amount);
        const status = String(job.status || '').toLowerCase();
        const eligibleAt = job.eligible_at ? new Date(job.eligible_at) : null;
        summary.totalAmount = toMoney(summary.totalAmount + amount);
        summary.count += 1;
        if (status === 'awaiting_remittance') {
          summary.codAwaitingRemittanceAmount = toMoney(summary.codAwaitingRemittanceAmount + amount);
          summary.codAwaitingRemittanceCount += 1;
        } else if (eligibleAt && eligibleAt > now) {
          summary.scheduledAmount = toMoney(summary.scheduledAmount + amount);
          summary.scheduledCount += 1;
        } else {
          summary.readyAmount = toMoney(summary.readyAmount + amount);
          summary.readyCount += 1;
        }
        return summary;
      },
      {
        totalAmount: 0,
        count: 0,
        readyAmount: 0,
        readyCount: 0,
        scheduledAmount: 0,
        scheduledCount: 0,
        codAwaitingRemittanceAmount: 0,
        codAwaitingRemittanceCount: 0
      }
    );
    return { shopId: String(shopId), sellerBalance, payoutPending, completedPayoutAmount, incomingSettlements };
  });
}

async function listShopLedger(shopId, limit = 50) {
  const sellerAccount = await sequelize.transaction(async (transaction) => (
    getShopBalanceAccount(shopId, transaction)
  ));
  return listAccountLedger(sellerAccount.id, limit);
}

async function settleOrderToShop({
  shopId,
  orderId,
  amount,
  referenceId,
  metadata = {},
  sagaId = null,
  correlationId = null
}) {
  const settlementAmount = toMoney(amount);
  if (settlementAmount <= 0) return { ok: false, reason: 'invalid_amount' };
  const settlementReference = referenceId || `order:${orderId}:shop:${shopId}:settlement`;

  return sequelize.transaction(async (transaction) => {
    const platformAccount = await getSystemAccount('platform_clearing', transaction);
    const sellerAccount = await getShopBalanceAccount(shopId, transaction);
    const ledgerResult = await transfer({
      fromAccount: platformAccount,
      toAccount: sellerAccount,
      amount: settlementAmount,
      referenceId: `ledger:${settlementReference}`,
      idempotencyKey: `ledger:${settlementReference}`,
      type: 'shop_settlement',
      metadata: { shopId, orderId, ...metadata },
      sagaId,
      correlationId,
      transaction
    });
    return {
      ok: true,
      reused: ledgerResult.reused,
      ledgerTransactionId: ledgerResult.transaction.id,
      balance: await getAccountSnapshot(sellerAccount, transaction)
    };
  });
}

async function reverseOrderSettlement({
  shopId,
  orderId,
  amount,
  reason = 'order_refund',
  metadata = {},
  sagaId = null,
  correlationId = null
}) {
  const reversalAmount = toMoney(amount);
  if (reversalAmount <= 0) return { ok: false, reason: 'invalid_amount' };
  const settlementReference = `ledger:order:${orderId}:shop:${shopId}:settlement`;
  const reversalReference = `ledger:order:${orderId}:shop:${shopId}:settlement_reversal`;

  return sequelize.transaction(async (transaction) => {
    const settlement = await LedgerTransaction.findOne({
      where: { reference_id: settlementReference, status: 'completed' },
      transaction
    });
    if (!settlement) return { ok: true, skipped: true, reason: 'settlement_not_found' };

    const existingReversal = await LedgerTransaction.findOne({
      where: { reference_id: reversalReference, status: 'completed' },
      transaction
    });
    if (existingReversal) return { ok: true, reused: true, ledgerTransactionId: existingReversal.id };

    const sellerAccount = await getShopBalanceAccount(shopId, transaction);
    const platformAccount = await getSystemAccount('platform_clearing', transaction);
    const ledgerResult = await transfer({
      fromAccount: sellerAccount,
      toAccount: platformAccount,
      amount: reversalAmount,
      referenceId: reversalReference,
      idempotencyKey: reversalReference,
      type: 'shop_settlement_reversal',
      metadata: { shopId, orderId, reason, ...metadata },
      sagaId,
      correlationId,
      transaction
    });
    return {
      ok: true,
      reused: ledgerResult.reused,
      ledgerTransactionId: ledgerResult.transaction.id
    };
  });
}

async function requestPayout({
  shopId,
  amount,
  bankAccount = {},
  referenceId,
  metadata = {},
  sagaId = null,
  correlationId = null
}) {
  const payoutAmount = toMoney(amount);
  if (payoutAmount <= 0) return { ok: false, reason: 'invalid_amount' };
  const payoutReference = referenceId || `payout:${shopId}:${Date.now()}:${Math.random().toString(36).slice(2, 8)}`;

  return sequelize.transaction(async (transaction) => {
    const existing = await PayoutRequest.findOne({
      where: { reference_id: payoutReference },
      transaction,
      lock: transaction.LOCK.UPDATE
    });
    if (existing) {
      return { ok: true, reused: true, payout: existing.toJSON() };
    }

    const sellerAccount = await getShopBalanceAccount(shopId, transaction);
    const payoutPendingAccount = await getShopPayoutPendingAccount(shopId, transaction);
    const ledgerResult = await transfer({
      fromAccount: sellerAccount,
      toAccount: payoutPendingAccount,
      amount: payoutAmount,
      referenceId: `ledger:${payoutReference}:hold`,
      idempotencyKey: `ledger:${payoutReference}:hold`,
      type: 'payout_hold',
      metadata: { shopId, ...metadata },
      sagaId,
      correlationId,
      transaction
    });

    const payout = await PayoutRequest.create(
      {
        shop_id: String(shopId),
        account_id: sellerAccount.id,
        amount: payoutAmount,
        currency: sellerAccount.currency,
        status: 'processing',
        reference_id: payoutReference,
        bank_account_snapshot: bankAccount || {},
        metadata: { ...metadata, ledgerTransactionId: ledgerResult.transaction.id },
        saga_id: sagaId,
        correlation_id: correlationId
      },
      { transaction }
    );

    return {
      ok: true,
      reused: false,
      payout: payout.toJSON(),
      balance: await getAccountSnapshot(sellerAccount, transaction)
    };
  });
}

async function completePayout(referenceId, metadata = {}) {
  return sequelize.transaction(async (transaction) => {
    const payout = await PayoutRequest.findOne({
      where: { reference_id: referenceId },
      transaction,
      lock: transaction.LOCK.UPDATE
    });
    if (!payout) return { ok: false, reason: 'payout_not_found' };
    if (payout.status === 'completed') return { ok: true, reused: true, payout: payout.toJSON() };
    if (payout.status !== 'processing') return { ok: false, reason: `invalid_payout_status:${payout.status}` };

    const payoutPendingAccount = await getShopPayoutPendingAccount(payout.shop_id, transaction);
    const externalAccount = await getSystemAccount('external_bank', transaction);
    const ledgerResult = await transfer({
      fromAccount: payoutPendingAccount,
      toAccount: externalAccount,
      amount: payout.amount,
      referenceId: `ledger:${referenceId}:complete`,
      idempotencyKey: `ledger:${referenceId}:complete`,
      type: 'payout_complete',
      metadata: { payoutId: payout.id, ...metadata },
      sagaId: payout.saga_id,
      correlationId: payout.correlation_id,
      transaction
    });

    payout.status = 'completed';
    payout.completed_at = new Date();
    payout.metadata = { ...(payout.metadata || {}), completedLedgerTransactionId: ledgerResult.transaction.id };
    await payout.save({ transaction });
    return { ok: true, reused: false, payout: payout.toJSON() };
  });
}

async function failPayout(referenceId, reason = 'bank_transfer_failed', metadata = {}) {
  return sequelize.transaction(async (transaction) => {
    const payout = await PayoutRequest.findOne({
      where: { reference_id: referenceId },
      transaction,
      lock: transaction.LOCK.UPDATE
    });
    if (!payout) return { ok: false, reason: 'payout_not_found' };
    if (payout.status === 'failed') return { ok: true, reused: true, payout: payout.toJSON() };
    if (payout.status !== 'processing') return { ok: false, reason: `invalid_payout_status:${payout.status}` };

    const payoutPendingAccount = await getShopPayoutPendingAccount(payout.shop_id, transaction);
    const sellerAccount = await getShopBalanceAccount(payout.shop_id, transaction);
    const ledgerResult = await transfer({
      fromAccount: payoutPendingAccount,
      toAccount: sellerAccount,
      amount: payout.amount,
      referenceId: `ledger:${referenceId}:fail`,
      idempotencyKey: `ledger:${referenceId}:fail`,
      type: 'payout_failed_return',
      metadata: { payoutId: payout.id, reason, ...metadata },
      sagaId: payout.saga_id,
      correlationId: payout.correlation_id,
      transaction
    });

    payout.status = 'failed';
    payout.failure_reason = reason;
    payout.metadata = { ...(payout.metadata || {}), failedLedgerTransactionId: ledgerResult.transaction.id };
    await payout.save({ transaction });
    return { ok: true, reused: false, payout: payout.toJSON() };
  });
}

async function listPayouts(shopId, limit = 50) {
  const rows = await PayoutRequest.findAll({
    where: { shop_id: String(shopId) },
    order: [['created_at', 'DESC']],
    limit: Math.max(1, Math.min(Number(limit) || 50, 200))
  });
  return rows.map((row) => row.toJSON());
}

module.exports = {
  getShopBalance,
  listShopLedger,
  settleOrderToShop,
  reverseOrderSettlement,
  requestPayout,
  completePayout,
  failPayout,
  listPayouts
};
