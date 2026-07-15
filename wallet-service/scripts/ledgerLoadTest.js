require('dotenv').config();
require('../src/models');

const { Op } = require('sequelize');
const { sequelize, initDb } = require('../src/config/db');
const { Account, AccountBalance } = require('../src/models');
const {
  findOrCreateAccount,
  getSystemAccount,
  getAccountBalance,
  transfer,
  toMoney
} = require('../src/services/accountLedgerService');

const ACCOUNT_COUNT = Number(process.env.LOAD_ACCOUNT_COUNT || 100);
const TRANSACTION_COUNT = Number(process.env.LOAD_TRANSACTION_COUNT || 1000);
const CONCURRENCY = Number(process.env.LOAD_CONCURRENCY || 50);
const SEED_AMOUNT = Number(process.env.LOAD_SEED_AMOUNT || 1000000);
const MAX_TRANSFER_AMOUNT = Number(process.env.LOAD_MAX_TRANSFER_AMOUNT || 100);
const RUN_ID = process.env.LOAD_RUN_ID || `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

async function seedAccounts() {
  const accounts = [];
  for (let index = 0; index < ACCOUNT_COUNT; index += 1) {
    await sequelize.transaction(async (transaction) => {
      const account = await findOrCreateAccount(
        {
          ownerType: 'load_test',
          ownerId: `${RUN_ID}:${index}`,
          accountType: 'test_wallet'
        },
        transaction
      );
      accounts.push(account);

      const balance = await getAccountBalance(account.id, transaction, true);
      if (toMoney(balance.available_balance) === 0) {
        const external = await getSystemAccount('external_bank', transaction);
        await transfer({
          fromAccount: external,
          toAccount: account,
          amount: SEED_AMOUNT,
          referenceId: `load:${RUN_ID}:seed:${index}`,
          idempotencyKey: `load:${RUN_ID}:seed:${index}`,
          type: 'load_seed',
          metadata: { runId: RUN_ID, index },
          transaction
        });
      }
    });
  }
  return accounts;
}

function pickTransfer(accounts, index) {
  const fromIndex = index % accounts.length;
  let toIndex = Math.floor(Math.random() * accounts.length);
  if (toIndex === fromIndex) toIndex = (toIndex + 1) % accounts.length;
  return {
    fromAccount: accounts[fromIndex],
    toAccount: accounts[toIndex],
    amount: Math.max(1, Math.floor(Math.random() * MAX_TRANSFER_AMOUNT)),
    referenceId: `load:${RUN_ID}:transfer:${index}`
  };
}

async function runTransfers(accounts) {
  let completed = 0;
  let failed = 0;
  const startedAt = Date.now();

  async function worker(offset) {
    for (let index = offset; index < TRANSACTION_COUNT; index += CONCURRENCY) {
      const tx = pickTransfer(accounts, index);
      try {
        await transfer({
          ...tx,
          idempotencyKey: tx.referenceId,
          type: 'load_transfer',
          metadata: { runId: RUN_ID, index }
        });
        completed += 1;
      } catch (err) {
        failed += 1;
        console.error('[ledger-load-test] transfer failed', { index, error: err.message });
      }
    }
  }

  await Promise.all(Array.from({ length: CONCURRENCY }, (_, index) => worker(index)));
  const elapsedMs = Date.now() - startedAt;
  return {
    completed,
    failed,
    elapsedMs,
    tps: Number((completed / (elapsedMs / 1000)).toFixed(2))
  };
}

async function verify(accounts) {
  const accountIds = accounts.map((account) => account.id);
  const balances = await AccountBalance.findAll({
    where: { account_id: { [Op.in]: accountIds } },
    include: [{ model: Account }]
  });

  const total = balances.reduce((sum, balance) => sum + toMoney(balance.available_balance), 0);
  const negative = balances.filter((balance) => toMoney(balance.available_balance) < 0);
  return {
    total: toMoney(total),
    expectedTotal: toMoney(ACCOUNT_COUNT * SEED_AMOUNT),
    negativeBalances: negative.length,
    ok: toMoney(total) === toMoney(ACCOUNT_COUNT * SEED_AMOUNT) && negative.length === 0
  };
}

async function main() {
  await initDb();
  console.log('[ledger-load-test] starting', {
    runId: RUN_ID,
    accountCount: ACCOUNT_COUNT,
    transactionCount: TRANSACTION_COUNT,
    concurrency: CONCURRENCY
  });
  const accounts = await seedAccounts();
  const result = await runTransfers(accounts);
  const verification = await verify(accounts);
  console.log('[ledger-load-test] result', { ...result, verification });
  if (!verification.ok || result.failed > 0) process.exitCode = 1;
}

main()
  .catch((err) => {
    console.error('[ledger-load-test] fatal', err);
    process.exitCode = 1;
  })
  .finally(async () => {
    await sequelize.close();
  });
