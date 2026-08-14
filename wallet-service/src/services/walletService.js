const { sequelize } = require('../config/db');
const { Op } = require('sequelize');
const { Wallet, WalletBalance, WalletLedgerEntry, AccountBalance, OutboxEvent } = require('../models');
const {
  getBuyerWalletAccount,
  getSystemAccount,
  getAccountBalance,
  transfer
} = require('./accountLedgerService');
const { fundPlatformClearingFromCapital } = require('./platformFinanceService');

const DEFAULT_WALLET_BALANCE = Number(process.env.WALLET_DEFAULT_BALANCE || 0);
const DEFAULT_CURRENCY = process.env.WALLET_DEFAULT_CURRENCY || 'VND';

function toMoney(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return 0;
  return Number(number.toFixed(2));
}

function toPublicWallet(wallet, balance) {
  return {
    id: wallet.id,
    user_id: wallet.user_id,
    userId: wallet.user_id,
    currency: wallet.currency,
    status: wallet.status,
    balance: toMoney(balance.available_balance),
    availableBalance: toMoney(balance.available_balance),
    lockedBalance: toMoney(balance.locked_balance),
    created_at: wallet.created_at,
    updated_at: wallet.updated_at
  };
}

function ledgerToPublic(entry) {
  const row = entry?.toJSON ? entry.toJSON() : entry;
  return {
    id: row.id,
    user_id: row.user_id,
    userId: row.user_id,
    order_id: row.order_id,
    orderId: row.order_id,
    type: row.type,
    direction: row.direction,
    amount: toMoney(row.amount),
    status: row.status,
    reason: row.reason,
    idempotency_key: row.reference_id,
    referenceId: row.reference_id,
    balance_before: toMoney(row.available_before),
    balance_after: toMoney(row.available_after),
    availableBefore: toMoney(row.available_before),
    availableAfter: toMoney(row.available_after),
    lockedBefore: toMoney(row.locked_before),
    lockedAfter: toMoney(row.locked_after),
    metadata: row.metadata || {},
    sagaId: row.saga_id || null,
    correlationId: row.correlation_id || null,
    created_at: row.created_at
  };
}

async function enqueueWalletEvent(transaction, topic, eventType, key, payload) {
  await OutboxEvent.create(
    {
      aggregate_type: 'wallet',
      aggregate_id: String(payload.walletId || payload.userId || key),
      event_type: eventType,
      topic,
      event_key: String(key),
      payload: {
        ...payload,
        eventId: payload.eventId || `${eventType}:${payload.referenceId || payload.orderId || Date.now()}`,
        eventType,
        occurredAt: payload.occurredAt || new Date().toISOString()
      },
      headers: {
        sagaId: payload.sagaId || '',
        correlationId: payload.correlationId || ''
      },
      saga_id: payload.sagaId || null,
      correlation_id: payload.correlationId || null
    },
    { transaction }
  );
}

async function ensureBuyerOpeningBalance(userId, legacyBalance, transaction) {
  const buyerAccount = await getBuyerWalletAccount(userId, transaction);
  const accountBalance = await getAccountBalance(buyerAccount.id, transaction, true);
  const legacyAvailable = toMoney(legacyBalance.available_balance);
  const accountAvailable = toMoney(accountBalance.available_balance);
  if (legacyAvailable <= 0 || accountAvailable !== 0) return buyerAccount;

  const externalAccount = await getSystemAccount('external_bank', transaction);
  await transfer({
    fromAccount: externalAccount,
    toAccount: buyerAccount,
    amount: legacyAvailable,
    referenceId: `migration:buyer_wallet:${userId}`,
    idempotencyKey: `migration:buyer_wallet:${userId}`,
    type: 'opening_balance',
    metadata: { source: 'legacy_wallet_balance', userId },
    transaction
  });
  return buyerAccount;
}

async function getOrCreateWallet(userId, transaction, currency = DEFAULT_CURRENCY) {
  let wallet = await Wallet.findOne({
    where: { user_id: String(userId), currency },
    transaction,
    lock: transaction ? transaction.LOCK.UPDATE : undefined
  });
  if (!wallet) {
    wallet = await Wallet.create(
      {
        user_id: String(userId),
        currency,
        status: 'active'
      },
      { transaction }
    );
    await WalletBalance.create(
      {
        wallet_id: wallet.id,
        available_balance: toMoney(DEFAULT_WALLET_BALANCE),
        locked_balance: 0,
        version: 0
      },
      { transaction }
    );
  }

  const balance = await WalletBalance.findOne({
    where: { wallet_id: wallet.id },
    transaction,
    lock: transaction ? transaction.LOCK.UPDATE : undefined
  });
  await ensureBuyerOpeningBalance(userId, balance, transaction);
  return { wallet, balance };
}

async function getWallet(userId) {
  return sequelize.transaction(async (transaction) => {
    const { wallet, balance } = await getOrCreateWallet(userId, transaction);
    return toPublicWallet(wallet, balance);
  });
}

async function listTransactions(userId, limit = 50) {
  const rows = await WalletLedgerEntry.findAll({
    where: { user_id: String(userId) },
    order: [['created_at', 'DESC']],
    limit: Math.max(1, Math.min(Number(limit) || 50, 200))
  });
  return rows.map(ledgerToPublic);
}

async function createLedgerEntry({
  transaction,
  wallet,
  balance,
  type,
  direction,
  amount,
  status,
  reason,
  referenceId,
  orderId = null,
  metadata = {},
  sagaId = null,
  correlationId = null,
  availableAfter,
  lockedAfter
}) {
  return WalletLedgerEntry.create(
    {
      wallet_id: wallet.id,
      user_id: wallet.user_id,
      order_id: orderId == null ? null : Number(orderId),
      type,
      direction,
      amount: toMoney(amount),
      status,
      reason,
      reference_id: referenceId,
      available_before: toMoney(balance.available_balance),
      available_after: toMoney(availableAfter),
      locked_before: toMoney(balance.locked_balance),
      locked_after: toMoney(lockedAfter),
      metadata,
      saga_id: sagaId,
      correlation_id: correlationId
    },
    { transaction }
  );
}

async function creditWallet(userId, amount, metadata = {}, options = {}) {
  const creditAmount = toMoney(amount);
  if (creditAmount <= 0) throw new Error('amount must be greater than 0');

  const referenceId = String(
    options.idempotencyKey ||
    options.referenceId ||
    `credit:${userId}:${Date.now()}:${Math.random().toString(36).slice(2, 8)}`
  );
  const reason = options.reason || 'wallet_credit';
  const type = options.type || 'credit';

  return sequelize.transaction(async (transaction) => {
    const existing = await WalletLedgerEntry.findOne({
      where: { reference_id: referenceId },
      transaction,
      lock: transaction.LOCK.UPDATE
    });
    if (existing) {
      const { wallet, balance } = await getOrCreateWallet(userId, transaction);
      return { wallet: toPublicWallet(wallet, balance), transaction: ledgerToPublic(existing), reused: true };
    }

    const { wallet, balance } = await getOrCreateWallet(userId, transaction);
    const buyerAccount = await getBuyerWalletAccount(userId, transaction);
    const externalAccount = await getSystemAccount('external_bank', transaction);
    const ledgerResult = await transfer({
      fromAccount: externalAccount,
      toAccount: buyerAccount,
      amount: creditAmount,
      referenceId: `ledger:${referenceId}`,
      idempotencyKey: `ledger:${referenceId}`,
      type,
      metadata: { ...metadata, reason, userId },
      sagaId: options.sagaId,
      correlationId: options.correlationId,
      transaction
    });
    const availableAfter = toMoney(balance.available_balance) + creditAmount;
    balance.available_balance = toMoney(availableAfter);
    balance.version += 1;
    await balance.save({ transaction });

    const entry = await createLedgerEntry({
      transaction,
      wallet,
      balance: {
        available_balance: toMoney(availableAfter - creditAmount),
        locked_balance: balance.locked_balance
      },
      type,
      direction: 'credit',
      amount: creditAmount,
      status: 'completed',
      reason,
      referenceId,
      orderId: options.orderId,
      metadata,
      sagaId: options.sagaId,
      correlationId: options.correlationId,
      availableAfter,
      lockedAfter: balance.locked_balance
    });

    await enqueueWalletEvent(transaction, 'wallet.credited', 'WalletCredited', wallet.user_id, {
      walletId: wallet.id,
      userId: wallet.user_id,
      orderId: options.orderId || null,
      amount: creditAmount,
      transactionId: entry.id,
      ledgerTransactionId: ledgerResult.transaction.id,
      referenceId,
      reason,
      metadata,
      sagaId: options.sagaId || null,
      correlationId: options.correlationId || null
    });

    return { wallet: toPublicWallet(wallet, balance), transaction: ledgerToPublic(entry) };
  });
}

async function topupWallet(userId, amount, metadata = {}, options = {}) {
  return creditWallet(userId, amount, metadata, {
    ...options,
    type: 'topup',
    reason: options.reason || 'manual_topup'
  });
}

async function recordExternalPaymentForOrder({ orderId, userId, amount, paymentMethod = 'bank_transfer', metadata = {}, sagaId, correlationId }) {
  const paidAmount = toMoney(amount);
  if (paidAmount <= 0) return { ok: false, reason: 'invalid_amount' };
  const referenceId = `order:${orderId}:external_payment`;

  return sequelize.transaction(async (transaction) => {
    const existing = await WalletLedgerEntry.findOne({
      where: { reference_id: referenceId },
      transaction,
      lock: transaction.LOCK.UPDATE
    });
    if (existing) return { ok: true, reason: 'already_recorded', transaction: ledgerToPublic(existing) };

    const { wallet, balance } = await getOrCreateWallet(userId, transaction);
    const platformAccount = await getSystemAccount('platform_clearing', transaction);
    const externalAccount = await getSystemAccount('external_bank', transaction);
    const ledgerResult = await transfer({
      fromAccount: externalAccount,
      toAccount: platformAccount,
      amount: paidAmount,
      referenceId: `ledger:${referenceId}`,
      idempotencyKey: `ledger:${referenceId}`,
      type: 'external_payment_order',
      metadata: { paymentMethod, orderId, userId, ...metadata },
      sagaId,
      correlationId,
      transaction
    });
    const entry = await createLedgerEntry({
      transaction,
      wallet,
      balance,
      type: 'external_payment_order',
      direction: 'none',
      amount: paidAmount,
      status: 'completed',
      reason: 'bank_transfer_paid',
      referenceId,
      orderId,
      metadata: { paymentMethod, ...metadata },
      sagaId,
      correlationId,
      availableAfter: balance.available_balance,
      lockedAfter: balance.locked_balance
    });

    await enqueueWalletEvent(transaction, 'wallet.external_payment_recorded', 'WalletExternalPaymentRecorded', orderId, {
      walletId: wallet.id,
      userId,
      orderId,
      amount: paidAmount,
      transactionId: entry.id,
      ledgerTransactionId: ledgerResult.transaction.id,
      referenceId,
      paymentMethod,
      metadata,
      sagaId: sagaId || null,
      correlationId: correlationId || null
    });

    return { ok: true, transaction: ledgerToPublic(entry) };
  });
}

async function debitForOrder({ orderId, userId, amount, paymentMethod, sagaId, correlationId }) {
  const debitAmount = toMoney(amount);
  if (debitAmount <= 0) return { ok: false, reason: 'invalid_amount' };
  const referenceId = `order:${orderId}:debit`;

  return sequelize.transaction(async (transaction) => {
    const existing = await WalletLedgerEntry.findOne({
      where: { reference_id: referenceId },
      transaction,
      lock: transaction.LOCK.UPDATE
    });
    if (existing) {
      return {
        ok: existing.status === 'completed',
        reason: existing.status === 'completed' ? 'already_debited' : existing.reason || 'debit_failed',
        transaction: ledgerToPublic(existing)
      };
    }

    const { wallet, balance } = await getOrCreateWallet(userId, transaction);
    const availableBefore = toMoney(balance.available_balance);
    if (availableBefore < debitAmount) {
      const failedEntry = await createLedgerEntry({
        transaction,
        wallet,
        balance,
        type: 'debit_order',
        direction: 'debit',
        amount: debitAmount,
        status: 'failed',
        reason: 'insufficient_wallet_balance',
        referenceId,
        orderId,
        metadata: { paymentMethod },
        sagaId,
        correlationId,
        availableAfter: balance.available_balance,
        lockedAfter: balance.locked_balance
      });
      await enqueueWalletEvent(transaction, 'wallet.debit_failed', 'WalletDebitFailed', orderId, {
        userId,
        orderId,
        amount: debitAmount,
        transactionId: failedEntry.id,
        referenceId,
        paymentMethod,
        reason: 'insufficient_wallet_balance',
        sagaId: sagaId || null,
        correlationId: correlationId || null
      });
      return { ok: false, reason: 'insufficient_wallet_balance', transaction: ledgerToPublic(failedEntry) };
    }

    const buyerAccount = await getBuyerWalletAccount(userId, transaction);
    const platformAccount = await getSystemAccount('platform_clearing', transaction);
    const ledgerResult = await transfer({
      fromAccount: buyerAccount,
      toAccount: platformAccount,
      amount: debitAmount,
      referenceId: `ledger:${referenceId}`,
      idempotencyKey: `ledger:${referenceId}`,
      type: 'order_payment',
      metadata: { paymentMethod, orderId, userId },
      sagaId,
      correlationId,
      transaction
    });

    const availableAfter = toMoney(availableBefore - debitAmount);
    balance.available_balance = availableAfter;
    balance.version += 1;
    await balance.save({ transaction });

    const debitEntry = await createLedgerEntry({
      transaction,
      wallet,
      balance: {
        available_balance: availableBefore,
        locked_balance: balance.locked_balance
      },
      type: 'debit_order',
      direction: 'debit',
      amount: debitAmount,
      status: 'completed',
      reason: 'order_payment',
      referenceId,
      orderId,
      metadata: { paymentMethod },
      sagaId,
      correlationId,
      availableAfter,
      lockedAfter: balance.locked_balance
    });

    await enqueueWalletEvent(transaction, 'wallet.debited', 'WalletDebited', orderId, {
      walletId: wallet.id,
      userId,
      orderId,
      amount: debitAmount,
      transactionId: debitEntry.id,
      ledgerTransactionId: ledgerResult.transaction.id,
      referenceId,
      paymentMethod,
      sagaId: sagaId || null,
      correlationId: correlationId || null
    });

    return { ok: true, transaction: ledgerToPublic(debitEntry), wallet: toPublicWallet(wallet, balance) };
  });
}

async function refundOrderToWallet({ orderId, userId, amount, reason, allowWithoutDebit = false, sagaId, correlationId }) {
  const refundAmount = toMoney(amount);
  if (refundAmount <= 0) return { ok: false, reason: 'invalid_amount' };
  const referenceId = `order:${orderId}:refund`;

  return sequelize.transaction(async (transaction) => {
    const existingRefund = await WalletLedgerEntry.findOne({
      where: { reference_id: referenceId },
      transaction,
      lock: transaction.LOCK.UPDATE
    });
    if (existingRefund) {
      return { ok: true, reason: 'already_refunded', transaction: ledgerToPublic(existingRefund) };
    }

    const paidEntry = await WalletLedgerEntry.findOne({
      where: {
        order_id: Number(orderId),
        type: { [Op.in]: ['debit_order', 'external_payment_order'] },
        status: 'completed'
      },
      transaction,
      lock: transaction.LOCK.UPDATE
    });

    if (!paidEntry && !allowWithoutDebit) return { ok: false, reason: 'no_debit_found' };

    const { wallet, balance } = await getOrCreateWallet(userId, transaction);
    const availableBefore = toMoney(balance.available_balance);
    const buyerAccount = await getBuyerWalletAccount(userId, transaction);
    const platformAccount = await getSystemAccount('platform_clearing', transaction);
    const platformBalance = await AccountBalance.findOne({
      where: { account_id: platformAccount.id },
      transaction,
      lock: transaction.LOCK.UPDATE
    });
    const platformAvailable = toMoney(platformBalance?.available_balance || 0);
    if (platformAvailable < refundAmount) {
      const fundingAmount = toMoney(refundAmount - platformAvailable);
      await fundPlatformClearingFromCapital({
        amount: fundingAmount,
        orderId,
        userId,
        reason,
        sagaId,
        correlationId,
        transaction
      });
    }
    const ledgerResult = await transfer({
      fromAccount: platformAccount,
      toAccount: buyerAccount,
      amount: refundAmount,
      referenceId: `ledger:${referenceId}`,
      idempotencyKey: `ledger:${referenceId}`,
      type: 'order_refund',
      metadata: { orderId, userId, reason: reason || 'order_cancelled' },
      sagaId,
      correlationId,
      transaction
    });
    const availableAfter = toMoney(availableBefore + refundAmount);
    balance.available_balance = availableAfter;
    balance.version += 1;
    await balance.save({ transaction });

    const refundEntry = await createLedgerEntry({
      transaction,
      wallet,
      balance: {
        available_balance: availableBefore,
        locked_balance: balance.locked_balance
      },
      type: 'refund_order',
      direction: 'credit',
      amount: refundAmount,
      status: 'completed',
      reason: reason || 'order_cancelled',
      referenceId,
      orderId,
      metadata: {},
      sagaId,
      correlationId,
      availableAfter,
      lockedAfter: balance.locked_balance
    });

    await enqueueWalletEvent(transaction, 'wallet.refunded', 'WalletRefunded', orderId, {
      walletId: wallet.id,
      userId,
      orderId,
      amount: refundAmount,
      transactionId: refundEntry.id,
      ledgerTransactionId: ledgerResult.transaction.id,
      referenceId,
      reason: reason || 'order_cancelled',
      sagaId: sagaId || null,
      correlationId: correlationId || null
    });

    return { ok: true, transaction: ledgerToPublic(refundEntry), wallet: toPublicWallet(wallet, balance) };
  });
}

module.exports = {
  getWallet,
  topupWallet,
  creditWallet,
  recordExternalPaymentForOrder,
  listTransactions,
  debitForOrder,
  refundOrderToWallet
};
