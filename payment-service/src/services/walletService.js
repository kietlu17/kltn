const { sequelize } = require('../config/db');
const { Wallet, WalletTransaction } = require('../models');

const DEFAULT_WALLET_BALANCE = Number(process.env.WALLET_DEFAULT_BALANCE || 0);

function toMoney(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return 0;
  return Number(number.toFixed(2));
}

async function getOrCreateWallet(userId, transaction) {
  let wallet = await Wallet.findOne({
    where: { user_id: String(userId) },
    transaction,
    lock: transaction ? transaction.LOCK.UPDATE : undefined
  });
  if (!wallet) {
    wallet = await Wallet.create(
      {
        user_id: String(userId),
        balance: toMoney(DEFAULT_WALLET_BALANCE)
      },
      { transaction }
    );
  }
  return wallet;
}

async function listTransactions(userId, limit = 50) {
  const rows = await WalletTransaction.findAll({
    where: { user_id: String(userId) },
    order: [['created_at', 'DESC']],
    limit: Math.max(1, Math.min(Number(limit) || 50, 200))
  });
  return rows.map((row) => row.toJSON());
}

async function getWallet(userId) {
  const wallet = await getOrCreateWallet(userId, null);
  return wallet.toJSON();
}

async function topupWallet(userId, amount, metadata = {}) {
  const topupAmount = toMoney(amount);
  if (topupAmount <= 0) {
    throw new Error('amount must be greater than 0');
  }

  return sequelize.transaction(async (transaction) => {
    const wallet = await getOrCreateWallet(userId, transaction);
    const before = toMoney(wallet.balance);
    const after = toMoney(before + topupAmount);
    wallet.balance = after;
    await wallet.save({ transaction });

    const tx = await WalletTransaction.create(
      {
        user_id: String(userId),
        order_id: null,
        type: 'topup',
        amount: topupAmount,
        balance_before: before,
        balance_after: after,
        status: 'completed',
        reason: 'manual_topup',
        idempotency_key: `topup:${userId}:${Date.now()}:${Math.random().toString(36).slice(2, 8)}`,
        metadata
      },
      { transaction }
    );

    return { wallet: wallet.toJSON(), transaction: tx.toJSON() };
  });
}

async function debitForOrder({ orderId, userId, amount, paymentMethod }) {
  const debitAmount = toMoney(amount);
  if (debitAmount <= 0) {
    return { ok: false, reason: 'invalid_amount' };
  }
  const idempotencyKey = `order:${orderId}:debit`;

  return sequelize.transaction(async (transaction) => {
    const existing = await WalletTransaction.findOne({
      where: { idempotency_key: idempotencyKey },
      transaction,
      lock: transaction.LOCK.UPDATE
    });
    if (existing) {
      if (existing.status === 'completed') {
        const existingRefund = await WalletTransaction.findOne({
          where: {
            order_id: Number(orderId),
            type: 'refund_order',
            status: 'completed'
          },
          transaction,
          lock: transaction.LOCK.UPDATE
        });
        if (existingRefund) {
          return {
            ok: false,
            reason: 'already_refunded',
            transaction: existing.toJSON()
          };
        }
      }
      return {
        ok: existing.status === 'completed',
        reason: existing.status === 'completed' ? 'already_debited' : existing.reason || 'debit_failed',
        transaction: existing.toJSON()
      };
    }

    const wallet = await getOrCreateWallet(userId, transaction);
    const before = toMoney(wallet.balance);
    if (before < debitAmount) {
      const failedTx = await WalletTransaction.create(
        {
          user_id: String(userId),
          order_id: Number(orderId),
          type: 'debit_order',
          amount: debitAmount,
          balance_before: before,
          balance_after: before,
          status: 'failed',
          reason: 'insufficient_wallet_balance',
          idempotency_key: idempotencyKey,
          metadata: { paymentMethod }
        },
        { transaction }
      );
      return { ok: false, reason: 'insufficient_wallet_balance', transaction: failedTx.toJSON() };
    }

    const after = toMoney(before - debitAmount);
    wallet.balance = after;
    await wallet.save({ transaction });
    const debitTx = await WalletTransaction.create(
      {
        user_id: String(userId),
        order_id: Number(orderId),
        type: 'debit_order',
        amount: debitAmount,
        balance_before: before,
        balance_after: after,
        status: 'completed',
        reason: 'order_payment',
        idempotency_key: idempotencyKey,
        metadata: { paymentMethod }
      },
      { transaction }
    );
    return { ok: true, transaction: debitTx.toJSON(), wallet: wallet.toJSON() };
  });
}

async function refundOrderToWallet({ orderId, userId, amount, reason, allowWithoutDebit = false }) {
  const refundAmount = toMoney(amount);
  if (refundAmount <= 0) {
    return { ok: false, reason: 'invalid_amount' };
  }
  const refundKey = `order:${orderId}:refund`;

  return sequelize.transaction(async (transaction) => {
    const existingRefund = await WalletTransaction.findOne({
      where: { idempotency_key: refundKey },
      transaction,
      lock: transaction.LOCK.UPDATE
    });
    if (existingRefund) {
      return { ok: true, reason: 'already_refunded', transaction: existingRefund.toJSON() };
    }

    const debitTx = await WalletTransaction.findOne({
      where: {
        order_id: Number(orderId),
        type: 'debit_order',
        status: 'completed'
      },
      transaction,
      lock: transaction.LOCK.UPDATE
    });
    if (!debitTx && !allowWithoutDebit) {
      return { ok: false, reason: 'no_debit_found' };
    }

    const wallet = await getOrCreateWallet(userId, transaction);
    const before = toMoney(wallet.balance);
    const after = toMoney(before + refundAmount);
    wallet.balance = after;
    await wallet.save({ transaction });

    const refundTx = await WalletTransaction.create(
      {
        user_id: String(userId),
        order_id: Number(orderId),
        type: 'refund_order',
        amount: refundAmount,
        balance_before: before,
        balance_after: after,
        status: 'completed',
        reason: reason || 'order_cancelled',
        idempotency_key: refundKey,
        metadata: {}
      },
      { transaction }
    );

    return { ok: true, transaction: refundTx.toJSON(), wallet: wallet.toJSON() };
  });
}

module.exports = {
  getWallet,
  topupWallet,
  listTransactions,
  debitForOrder,
  refundOrderToWallet
};
