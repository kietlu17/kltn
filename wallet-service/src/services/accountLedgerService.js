const { Op } = require('sequelize');
const { sequelize } = require('../config/db');
const {
  Account,
  AccountBalance,
  LedgerTransaction,
  LedgerEntry
} = require('../models');

const DEFAULT_CURRENCY = process.env.WALLET_DEFAULT_CURRENCY || 'VND';
const SYSTEM_OWNER_ID = 'marketplace';

function toMoney(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return 0;
  return Number(number.toFixed(2));
}

function sameAmount(left, right) {
  return Math.abs(toMoney(left) - toMoney(right)) < 0.01;
}

function normalizeLedgerEntries(entries) {
  return entries.map((entry) => ({
    ...entry,
    accountId: String(entry.accountId),
    direction: String(entry.direction || '').toLowerCase(),
    amount: toMoney(entry.amount)
  }));
}

function summarizeLedgerEntries(entries) {
  const debitTotal = entries
    .filter((entry) => entry.direction === 'debit')
    .reduce((sum, entry) => sum + toMoney(entry.amount), 0);
  const creditTotal = entries
    .filter((entry) => entry.direction === 'credit')
    .reduce((sum, entry) => sum + toMoney(entry.amount), 0);
  return {
    debitTotal: toMoney(debitTotal),
    creditTotal: toMoney(creditTotal),
    entryCount: entries.length
  };
}

function assertBalancedEntries(entries, amount) {
  if (!Array.isArray(entries) || entries.length < 2) {
    throw new Error('double-entry transaction requires at least two entries');
  }
  for (const entry of entries) {
    if (!['debit', 'credit'].includes(entry.direction)) throw new Error('invalid ledger direction');
    if (entry.amount <= 0) throw new Error('ledger entry amount must be greater than 0');
  }
  const { debitTotal, creditTotal, entryCount } = summarizeLedgerEntries(entries);
  if (entryCount < 2 || !sameAmount(debitTotal, creditTotal) || !sameAmount(debitTotal, amount)) {
    throw new Error('ledger transaction is not balanced');
  }
  return { debitTotal, creditTotal, entryCount };
}

async function verifyLedgerTransactionBalance(transactionId, transaction) {
  const [rows] = await sequelize.query(
    `
      SELECT
        COALESCE(SUM(CASE WHEN direction = 'debit' THEN amount ELSE 0 END), 0) AS debit_amount,
        COALESCE(SUM(CASE WHEN direction = 'credit' THEN amount ELSE 0 END), 0) AS credit_amount,
        COUNT(*) AS entry_count
      FROM ledger_entries
      WHERE transaction_id = :transactionId
    `,
    {
      replacements: { transactionId },
      transaction
    }
  );
  const row = rows[0] || {};
  const debitAmount = toMoney(row.debit_amount);
  const creditAmount = toMoney(row.credit_amount);
  const entryCount = Number(row.entry_count || 0);
  return {
    debitAmount,
    creditAmount,
    entryCount,
    balanced: entryCount >= 2 && sameAmount(debitAmount, creditAmount)
  };
}

function publicAccount(account, balance) {
  return {
    id: account.id,
    ownerType: account.owner_type,
    ownerId: account.owner_id,
    accountType: account.account_type,
    currency: account.currency,
    status: account.status,
    availableBalance: toMoney(balance.available_balance),
    lockedBalance: toMoney(balance.locked_balance),
    allowNegative: Boolean(account.allow_negative),
    metadata: account.metadata || {}
  };
}

async function inTransaction(existingTransaction, work) {
  if (existingTransaction) return work(existingTransaction);
  return sequelize.transaction(work);
}

async function findOrCreateAccount({
  ownerType,
  ownerId,
  accountType,
  currency = DEFAULT_CURRENCY,
  allowNegative = false,
  metadata = {}
}, transaction) {
  const where = {
    owner_type: String(ownerType),
    owner_id: String(ownerId),
    account_type: String(accountType),
    currency
  };

  let account = await Account.findOne({
    where,
    transaction,
    lock: transaction ? transaction.LOCK.UPDATE : undefined
  });

  if (!account) {
    try {
      account = await Account.create(
        {
          ...where,
          status: 'active',
          allow_negative: Boolean(allowNegative),
          metadata
        },
        { transaction }
      );
      await AccountBalance.create(
        {
          account_id: account.id,
          available_balance: 0,
          locked_balance: 0,
          version: 0
        },
        { transaction }
      );
    } catch (err) {
      if (err?.name !== 'SequelizeUniqueConstraintError') throw err;
      account = await Account.findOne({
        where,
        transaction,
        lock: transaction ? transaction.LOCK.UPDATE : undefined
      });
    }
  }

  return account;
}

async function getSystemAccount(accountType, transaction) {
  return findOrCreateAccount(
    {
      ownerType: accountType === 'external_bank' ? 'external' : 'platform',
      ownerId: SYSTEM_OWNER_ID,
      accountType,
      allowNegative: accountType === 'external_bank',
      metadata: { system: true }
    },
    transaction
  );
}

async function getBuyerWalletAccount(userId, transaction) {
  return findOrCreateAccount(
    {
      ownerType: 'buyer',
      ownerId: userId,
      accountType: 'buyer_wallet'
    },
    transaction
  );
}

async function getShopBalanceAccount(shopId, transaction) {
  return findOrCreateAccount(
    {
      ownerType: 'shop',
      ownerId: shopId,
      accountType: 'seller_balance'
    },
    transaction
  );
}

async function getShopPayoutPendingAccount(shopId, transaction) {
  return findOrCreateAccount(
    {
      ownerType: 'shop',
      ownerId: shopId,
      accountType: 'payout_pending'
    },
    transaction
  );
}

async function getAccountBalance(accountId, transaction, lock = false) {
  return AccountBalance.findOne({
    where: { account_id: accountId },
    transaction,
    lock: lock && transaction ? transaction.LOCK.UPDATE : undefined
  });
}

async function getAccountSnapshot(account, transaction) {
  const balance = await getAccountBalance(account.id, transaction);
  return publicAccount(account, balance);
}

async function getAccountByOwner(ownerType, ownerId, accountType, currency = DEFAULT_CURRENCY) {
  return sequelize.transaction(async (transaction) => {
    const account = await findOrCreateAccount({ ownerType, ownerId, accountType, currency }, transaction);
    return getAccountSnapshot(account, transaction);
  });
}

async function postDoubleEntryTransaction({
  referenceId,
  idempotencyKey = null,
  type,
  amount,
  currency = DEFAULT_CURRENCY,
  entries,
  metadata = {},
  sagaId = null,
  correlationId = null,
  transaction: existingTransaction = null
}) {
  return inTransaction(existingTransaction, async (transaction) => {
    const normalizedAmount = toMoney(amount);
    if (normalizedAmount <= 0) throw new Error('amount must be greater than 0');
    if (!referenceId) throw new Error('referenceId is required');
    const normalizedEntries = normalizeLedgerEntries(entries || []);
    const expectedTotals = assertBalancedEntries(normalizedEntries, normalizedAmount);

    let ledgerTx = await LedgerTransaction.findOne({
      where: {
        [Op.or]: [
          { reference_id: String(referenceId) },
          ...(idempotencyKey ? [{ idempotency_key: String(idempotencyKey) }] : [])
        ]
      },
      transaction,
      lock: transaction.LOCK.UPDATE
    });

    if (ledgerTx?.status === 'completed') {
      const balanceCheck = await verifyLedgerTransactionBalance(ledgerTx.id, transaction);
      if (!balanceCheck.balanced || !sameAmount(balanceCheck.debitAmount, ledgerTx.amount)) {
        throw new Error(`completed ledger transaction is imbalanced:${ledgerTx.reference_id}`);
      }
      const existingEntries = await LedgerEntry.findAll({
        where: { transaction_id: ledgerTx.id },
        transaction,
        order: [['created_at', 'ASC']]
      });
      return { transaction: ledgerTx, entries: existingEntries, reused: true };
    }
    if (ledgerTx && ledgerTx.status !== 'pending') {
      throw new Error(`ledger transaction is not reusable:${ledgerTx.reference_id}:${ledgerTx.status}`);
    }

    if (!ledgerTx) {
      ledgerTx = await LedgerTransaction.create(
        {
          reference_id: String(referenceId),
          idempotency_key: idempotencyKey ? String(idempotencyKey) : null,
          type,
          status: 'pending',
          amount: normalizedAmount,
          debit_amount: 0,
          credit_amount: 0,
          entry_count: 0,
          currency,
          metadata,
          saga_id: sagaId,
          correlation_id: correlationId
        },
        { transaction }
      );
    } else {
      const pendingEntryCount = await LedgerEntry.count({
        where: { transaction_id: ledgerTx.id },
        transaction
      });
      if (pendingEntryCount > 0) {
        throw new Error(`pending ledger transaction has existing entries:${ledgerTx.reference_id}`);
      }
    }

    const accountIds = [...new Set(normalizedEntries.map((entry) => entry.accountId))].sort();
    const balances = await AccountBalance.findAll({
      where: { account_id: accountIds },
      order: [['account_id', 'ASC']],
      transaction,
      lock: transaction.LOCK.UPDATE
    });
    const accounts = await Account.findAll({
      where: { id: accountIds },
      order: [['id', 'ASC']],
      transaction
    });

    const balanceByAccount = new Map(balances.map((balance) => [String(balance.account_id), balance]));
    const accountById = new Map(accounts.map((account) => [String(account.id), account]));
    if (balances.length !== accountIds.length || accounts.length !== accountIds.length) {
      throw new Error('account balance not found');
    }

    const createdEntries = [];
    for (const entry of normalizedEntries) {
      const accountId = entry.accountId;
      const balance = balanceByAccount.get(accountId);
      const account = accountById.get(accountId);
      if (account.currency !== currency) {
        throw new Error(`account currency mismatch:${account.owner_type}:${account.owner_id}:${account.account_type}`);
      }
      const entryAmount = entry.amount;
      const availableBefore = toMoney(balance.available_balance);
      const lockedBefore = toMoney(balance.locked_balance);
      let availableAfter = availableBefore;

      if (entry.direction === 'debit') availableAfter = toMoney(availableBefore - entryAmount);
      if (entry.direction === 'credit') availableAfter = toMoney(availableBefore + entryAmount);
      if (availableAfter < 0 && !account.allow_negative) {
        throw new Error(`insufficient_balance:${account.owner_type}:${account.owner_id}:${account.account_type}`);
      }

      balance.available_balance = availableAfter;
      balance.version += 1;
      await balance.save({ transaction });

      createdEntries.push(
        await LedgerEntry.create(
          {
            transaction_id: ledgerTx.id,
            account_id: accountId,
            direction: entry.direction,
            amount: entryAmount,
            currency,
            available_before: availableBefore,
            available_after: availableAfter,
            locked_before: lockedBefore,
            locked_after: lockedBefore,
            metadata: entry.metadata || {}
          },
          { transaction }
        )
      );
    }

    const actualTotals = await verifyLedgerTransactionBalance(ledgerTx.id, transaction);
    if (
      !actualTotals.balanced ||
      !sameAmount(actualTotals.debitAmount, expectedTotals.debitTotal) ||
      !sameAmount(actualTotals.creditAmount, expectedTotals.creditTotal) ||
      actualTotals.entryCount !== expectedTotals.entryCount
    ) {
      throw new Error(`ledger transaction verification failed:${ledgerTx.reference_id}`);
    }

    ledgerTx.debit_amount = actualTotals.debitAmount;
    ledgerTx.credit_amount = actualTotals.creditAmount;
    ledgerTx.entry_count = actualTotals.entryCount;
    ledgerTx.status = 'completed';
    ledgerTx.completed_at = new Date();
    await ledgerTx.save({ transaction });

    return { transaction: ledgerTx, entries: createdEntries, reused: false };
  });
}

async function transfer({
  fromAccount,
  toAccount,
  amount,
  referenceId,
  idempotencyKey,
  type,
  metadata = {},
  sagaId,
  correlationId,
  transaction
}) {
  return postDoubleEntryTransaction({
    referenceId,
    idempotencyKey,
    type,
    amount,
    metadata,
    sagaId,
    correlationId,
    transaction,
    entries: [
      {
        accountId: fromAccount.id,
        direction: 'debit',
        amount,
        metadata: { role: 'source', ...metadata }
      },
      {
        accountId: toAccount.id,
        direction: 'credit',
        amount,
        metadata: { role: 'destination', ...metadata }
      }
    ]
  });
}

async function listAccountLedger(accountId, limit = 50) {
  const rows = await LedgerEntry.findAll({
    where: { account_id: accountId },
    include: [{ model: LedgerTransaction }],
    order: [['created_at', 'DESC']],
    limit: Math.max(1, Math.min(Number(limit) || 50, 200))
  });

  return rows.map((row) => {
    const entry = row.toJSON();
    return {
      id: entry.id,
      transactionId: entry.transaction_id,
      accountId: entry.account_id,
      direction: entry.direction,
      amount: toMoney(entry.amount),
      currency: entry.currency,
      availableBefore: toMoney(entry.available_before),
      availableAfter: toMoney(entry.available_after),
      metadata: entry.metadata || {},
      transaction: entry.LedgerTransaction
        ? {
            id: entry.LedgerTransaction.id,
            referenceId: entry.LedgerTransaction.reference_id,
            type: entry.LedgerTransaction.type,
            status: entry.LedgerTransaction.status,
            metadata: entry.LedgerTransaction.metadata || {},
            createdAt: entry.LedgerTransaction.created_at
          }
        : null,
      createdAt: entry.created_at
    };
  });
}

module.exports = {
  toMoney,
  publicAccount,
  findOrCreateAccount,
  getSystemAccount,
  getBuyerWalletAccount,
  getShopBalanceAccount,
  getShopPayoutPendingAccount,
  getAccountBalance,
  getAccountSnapshot,
  getAccountByOwner,
  postDoubleEntryTransaction,
  verifyLedgerTransactionBalance,
  transfer,
  listAccountLedger
};
