const { sequelize } = require('../config/db');
const { UserWithdrawalRequest, Wallet, WalletBalance, WalletLedgerEntry } = require('../models');
const {
  toMoney,
  getBuyerWalletAccount,
  getUserWithdrawalPendingAccount,
  getSystemAccount,
  getAccountSnapshot,
  transfer
} = require('./accountLedgerService');

async function getLockedLegacyWallet(userId, transaction) {
  const wallet = await Wallet.findOne({
    where: { user_id: String(userId), currency: 'VND' },
    transaction,
    lock: transaction.LOCK.UPDATE
  });
  if (!wallet) throw new Error('insufficient_balance:buyer_wallet');
  const balance = await WalletBalance.findOne({
    where: { wallet_id: wallet.id },
    transaction,
    lock: transaction.LOCK.UPDATE
  });
  if (!balance) throw new Error('insufficient_balance:buyer_wallet');
  return { wallet, balance };
}

async function requestUserWithdrawal({
  userId,
  amount,
  bankAccount = {},
  referenceId,
  metadata = {},
  sagaId = null,
  correlationId = null
}) {
  const withdrawalAmount = toMoney(amount);
  if (withdrawalAmount <= 0) return { ok: false, reason: 'invalid_amount' };
  const withdrawalReference = referenceId || `user-withdrawal:${userId}:${Date.now()}:${Math.random().toString(36).slice(2, 8)}`;

  return sequelize.transaction(async (transaction) => {
    const existing = await UserWithdrawalRequest.findOne({
      where: { reference_id: withdrawalReference },
      transaction,
      lock: transaction.LOCK.UPDATE
    });
    if (existing) return { ok: true, reused: true, withdrawal: existing.toJSON() };

    const buyerAccount = await getBuyerWalletAccount(userId, transaction);
    const pendingAccount = await getUserWithdrawalPendingAccount(userId, transaction);
    const { wallet, balance } = await getLockedLegacyWallet(userId, transaction);
    const availableBefore = toMoney(balance.available_balance);
    if (availableBefore < withdrawalAmount) throw new Error('insufficient_balance:buyer_wallet');
    const ledgerResult = await transfer({
      fromAccount: buyerAccount,
      toAccount: pendingAccount,
      amount: withdrawalAmount,
      referenceId: `ledger:${withdrawalReference}:hold`,
      idempotencyKey: `ledger:${withdrawalReference}:hold`,
      type: 'user_withdrawal_hold',
      metadata: { userId, ...metadata },
      sagaId,
      correlationId,
      transaction
    });

    const availableAfter = toMoney(availableBefore - withdrawalAmount);
    balance.available_balance = availableAfter;
    balance.version += 1;
    await balance.save({ transaction });
    await WalletLedgerEntry.create(
      {
        wallet_id: wallet.id,
        user_id: String(userId),
        order_id: null,
        type: 'user_withdrawal_hold',
        direction: 'debit',
        amount: withdrawalAmount,
        status: 'completed',
        reason: 'user_withdrawal_requested',
        reference_id: `${withdrawalReference}:legacy_hold`,
        available_before: availableBefore,
        available_after: availableAfter,
        locked_before: balance.locked_balance,
        locked_after: balance.locked_balance,
        metadata,
        saga_id: sagaId,
        correlation_id: correlationId
      },
      { transaction }
    );

    const withdrawal = await UserWithdrawalRequest.create(
      {
        user_id: String(userId),
        account_id: buyerAccount.id,
        amount: withdrawalAmount,
        currency: buyerAccount.currency,
        status: 'processing',
        reference_id: withdrawalReference,
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
      withdrawal: withdrawal.toJSON(),
      balance: await getAccountSnapshot(buyerAccount, transaction)
    };
  });
}

async function completeUserWithdrawal(referenceId, metadata = {}) {
  return sequelize.transaction(async (transaction) => {
    const withdrawal = await UserWithdrawalRequest.findOne({
      where: { reference_id: referenceId },
      transaction,
      lock: transaction.LOCK.UPDATE
    });
    if (!withdrawal) return { ok: false, reason: 'withdrawal_not_found' };
    if (withdrawal.status === 'completed') return { ok: true, reused: true, withdrawal: withdrawal.toJSON() };
    if (withdrawal.status !== 'processing') return { ok: false, reason: `invalid_withdrawal_status:${withdrawal.status}` };

    const pendingAccount = await getUserWithdrawalPendingAccount(withdrawal.user_id, transaction);
    const externalAccount = await getSystemAccount('external_bank', transaction);
    const ledgerResult = await transfer({
      fromAccount: pendingAccount,
      toAccount: externalAccount,
      amount: withdrawal.amount,
      referenceId: `ledger:${referenceId}:complete`,
      idempotencyKey: `ledger:${referenceId}:complete`,
      type: 'user_withdrawal_complete',
      metadata: { withdrawalId: withdrawal.id, ...metadata },
      sagaId: withdrawal.saga_id,
      correlationId: withdrawal.correlation_id,
      transaction
    });

    withdrawal.status = 'completed';
    withdrawal.completed_at = new Date();
    withdrawal.metadata = { ...(withdrawal.metadata || {}), completedLedgerTransactionId: ledgerResult.transaction.id };
    await withdrawal.save({ transaction });
    return { ok: true, reused: false, withdrawal: withdrawal.toJSON() };
  });
}

async function failUserWithdrawal(referenceId, reason = 'bank_transfer_failed', metadata = {}) {
  return sequelize.transaction(async (transaction) => {
    const withdrawal = await UserWithdrawalRequest.findOne({
      where: { reference_id: referenceId },
      transaction,
      lock: transaction.LOCK.UPDATE
    });
    if (!withdrawal) return { ok: false, reason: 'withdrawal_not_found' };
    if (withdrawal.status === 'failed') return { ok: true, reused: true, withdrawal: withdrawal.toJSON() };
    if (withdrawal.status !== 'processing') return { ok: false, reason: `invalid_withdrawal_status:${withdrawal.status}` };

    const pendingAccount = await getUserWithdrawalPendingAccount(withdrawal.user_id, transaction);
    const buyerAccount = await getBuyerWalletAccount(withdrawal.user_id, transaction);
    const { wallet, balance } = await getLockedLegacyWallet(withdrawal.user_id, transaction);
    const availableBefore = toMoney(balance.available_balance);
    const ledgerResult = await transfer({
      fromAccount: pendingAccount,
      toAccount: buyerAccount,
      amount: withdrawal.amount,
      referenceId: `ledger:${referenceId}:fail`,
      idempotencyKey: `ledger:${referenceId}:fail`,
      type: 'user_withdrawal_failed_return',
      metadata: { withdrawalId: withdrawal.id, reason, ...metadata },
      sagaId: withdrawal.saga_id,
      correlationId: withdrawal.correlation_id,
      transaction
    });

    const availableAfter = toMoney(availableBefore + Number(withdrawal.amount || 0));
    balance.available_balance = availableAfter;
    balance.version += 1;
    await balance.save({ transaction });
    await WalletLedgerEntry.create(
      {
        wallet_id: wallet.id,
        user_id: String(withdrawal.user_id),
        order_id: null,
        type: 'user_withdrawal_failed_return',
        direction: 'credit',
        amount: withdrawal.amount,
        status: 'completed',
        reason,
        reference_id: `${referenceId}:legacy_fail`,
        available_before: availableBefore,
        available_after: availableAfter,
        locked_before: balance.locked_balance,
        locked_after: balance.locked_balance,
        metadata,
        saga_id: withdrawal.saga_id,
        correlation_id: withdrawal.correlation_id
      },
      { transaction }
    );

    withdrawal.status = 'failed';
    withdrawal.failure_reason = reason;
    withdrawal.metadata = { ...(withdrawal.metadata || {}), failedLedgerTransactionId: ledgerResult.transaction.id };
    await withdrawal.save({ transaction });
    return { ok: true, reused: false, withdrawal: withdrawal.toJSON() };
  });
}

async function listUserWithdrawals(userId, limit = 50) {
  const rows = await UserWithdrawalRequest.findAll({
    where: { user_id: String(userId) },
    order: [['created_at', 'DESC']],
    limit: Math.max(1, Math.min(Number(limit) || 50, 200))
  });
  return rows.map((row) => row.toJSON());
}

module.exports = {
  requestUserWithdrawal,
  completeUserWithdrawal,
  failUserWithdrawal,
  listUserWithdrawals
};
