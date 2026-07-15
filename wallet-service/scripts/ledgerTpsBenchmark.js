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

const ACCOUNT_COUNT = Number(process.env.TPS_ACCOUNT_COUNT || 1000);
const DURATION_SECONDS = Number(process.env.TPS_DURATION_SECONDS || 30);
const WARMUP_SECONDS = Number(process.env.TPS_WARMUP_SECONDS || 3);
const CONCURRENCY = Number(process.env.TPS_CONCURRENCY || 100);
const SEED_AMOUNT = Number(process.env.TPS_SEED_AMOUNT || 1000000);
const MAX_TRANSFER_AMOUNT = Number(process.env.TPS_MAX_TRANSFER_AMOUNT || 100);
const LATENCY_SAMPLE_LIMIT = Number(process.env.TPS_LATENCY_SAMPLE_LIMIT || 200000);
const RETRY_LIMIT = Number(process.env.TPS_RETRY_LIMIT || 3);
const RECONCILE_RUN = String(process.env.TPS_RECONCILE || 'true').toLowerCase() !== 'false';
const HOT_ACCOUNT_MODE = String(process.env.TPS_HOT_ACCOUNT || '').toLowerCase() === 'true';
const RUN_ID = process.env.TPS_RUN_ID || `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

let sequence = 0;

function nextSequence() {
  sequence += 1;
  return sequence;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function percentile(sortedValues, percentileValue) {
  if (!sortedValues.length) return 0;
  const index = Math.ceil((percentileValue / 100) * sortedValues.length) - 1;
  return sortedValues[Math.max(0, Math.min(index, sortedValues.length - 1))];
}

function isRetryableDbError(err) {
  const code = err?.parent?.code || err?.original?.code;
  return ['40001', '40P01', '55P03'].includes(code);
}

function addLatencySample(samples, value) {
  if (samples.length < LATENCY_SAMPLE_LIMIT) {
    samples.push(value);
    return;
  }
  const index = Math.floor(Math.random() * (samples.length + 1));
  if (index < samples.length) samples[index] = value;
}

async function seedAccounts() {
  const accounts = [];
  for (let index = 0; index < ACCOUNT_COUNT; index += 1) {
    await sequelize.transaction(async (transaction) => {
      const account = await findOrCreateAccount(
        {
          ownerType: 'tps_test',
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
          referenceId: `tps:${RUN_ID}:seed:${index}`,
          idempotencyKey: `tps:${RUN_ID}:seed:${index}`,
          type: 'tps_seed',
          metadata: { runId: RUN_ID, index },
          transaction
        });
      }
    });
  }
  return accounts;
}

function pickTransfer(accounts, index) {
  const fromIndex = HOT_ACCOUNT_MODE ? 0 : index % accounts.length;
  let toIndex = Math.floor(Math.random() * accounts.length);
  if (toIndex === fromIndex) toIndex = (toIndex + 1) % accounts.length;
  return {
    fromAccount: accounts[fromIndex],
    toAccount: accounts[toIndex],
    amount: Math.max(1, Math.floor(Math.random() * MAX_TRANSFER_AMOUNT)),
    referenceId: `tps:${RUN_ID}:transfer:${index}`
  };
}

async function executeTransfer(accounts, index) {
  const tx = pickTransfer(accounts, index);
  for (let attempt = 0; attempt <= RETRY_LIMIT; attempt += 1) {
    try {
      await transfer({
        ...tx,
        idempotencyKey: tx.referenceId,
        type: 'tps_transfer',
        metadata: {
          runId: RUN_ID,
          index,
          attempt,
          hotAccountMode: HOT_ACCOUNT_MODE
        }
      });
      return { retried: attempt > 0, retryCount: attempt };
    } catch (err) {
      if (!isRetryableDbError(err) || attempt === RETRY_LIMIT) throw err;
      await sleep(Math.min(100, 10 * 2 ** attempt));
    }
  }
  return { retried: false, retryCount: 0 };
}

async function runPhase(accounts, durationMs, collectMetrics) {
  const endsAt = Date.now() + durationMs;
  const metrics = {
    completed: 0,
    failed: 0,
    retryCount: 0,
    latencySamples: [],
    errorCodes: new Map()
  };

  async function worker() {
    while (Date.now() < endsAt) {
      const index = nextSequence();
      const startedAt = process.hrtime.bigint();
      try {
        const result = await executeTransfer(accounts, index);
        if (collectMetrics) {
          metrics.completed += 1;
          metrics.retryCount += result.retryCount;
          const elapsedMs = Number(process.hrtime.bigint() - startedAt) / 1e6;
          addLatencySample(metrics.latencySamples, elapsedMs);
        }
      } catch (err) {
        if (collectMetrics) {
          metrics.failed += 1;
          const code = err?.parent?.code || err?.original?.code || err.name || 'unknown';
          metrics.errorCodes.set(code, (metrics.errorCodes.get(code) || 0) + 1);
        }
      }
    }
  }

  const startedAt = Date.now();
  await Promise.all(Array.from({ length: CONCURRENCY }, () => worker()));
  metrics.elapsedMs = Date.now() - startedAt;
  return metrics;
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

async function verifyDoubleEntryForRun() {
  const [summaryRows] = await sequelize.query(
    `
      WITH entry_totals AS (
        SELECT
          transaction_id,
          COALESCE(SUM(CASE WHEN direction = 'debit' THEN amount ELSE 0 END), 0) AS debit_amount,
          COALESCE(SUM(CASE WHEN direction = 'credit' THEN amount ELSE 0 END), 0) AS credit_amount,
          COUNT(*) AS entry_count
        FROM ledger_entries
        GROUP BY transaction_id
      )
      SELECT
        COUNT(*) AS transaction_count,
        COALESCE(SUM(lt.amount), 0) AS transaction_amount,
        COALESCE(SUM(et.debit_amount), 0) AS debit_amount,
        COALESCE(SUM(et.credit_amount), 0) AS credit_amount,
        COALESCE(SUM(et.entry_count), 0) AS entry_count
      FROM ledger_transactions lt
      LEFT JOIN entry_totals et ON et.transaction_id = lt.id
      WHERE lt.reference_id LIKE :referencePrefix
        AND lt.status = 'completed'
    `,
    {
      replacements: { referencePrefix: `tps:${RUN_ID}:%` }
    }
  );

  const [issueRows] = await sequelize.query(
    `
      WITH entry_totals AS (
        SELECT
          transaction_id,
          COALESCE(SUM(CASE WHEN direction = 'debit' THEN amount ELSE 0 END), 0) AS debit_amount,
          COALESCE(SUM(CASE WHEN direction = 'credit' THEN amount ELSE 0 END), 0) AS credit_amount,
          COUNT(*) AS entry_count
        FROM ledger_entries
        GROUP BY transaction_id
      )
      SELECT
        lt.reference_id,
        lt.amount,
        lt.debit_amount AS stored_debit_amount,
        lt.credit_amount AS stored_credit_amount,
        lt.entry_count AS stored_entry_count,
        COALESCE(et.debit_amount, 0) AS computed_debit_amount,
        COALESCE(et.credit_amount, 0) AS computed_credit_amount,
        COALESCE(et.entry_count, 0) AS computed_entry_count
      FROM ledger_transactions lt
      LEFT JOIN entry_totals et ON et.transaction_id = lt.id
      WHERE lt.reference_id LIKE :referencePrefix
        AND lt.status = 'completed'
        AND (
          COALESCE(et.entry_count, 0) < 2
          OR COALESCE(et.debit_amount, 0) <> COALESCE(et.credit_amount, 0)
          OR COALESCE(et.debit_amount, 0) <> lt.amount
          OR lt.debit_amount <> COALESCE(et.debit_amount, 0)
          OR lt.credit_amount <> COALESCE(et.credit_amount, 0)
          OR lt.entry_count <> COALESCE(et.entry_count, 0)
        )
      ORDER BY lt.created_at ASC
      LIMIT 20
    `,
    {
      replacements: { referencePrefix: `tps:${RUN_ID}:%` }
    }
  );

  const summary = summaryRows[0] || {};
  return {
    ok: issueRows.length === 0,
    transactionCount: Number(summary.transaction_count || 0),
    entryCount: Number(summary.entry_count || 0),
    transactionAmount: toMoney(summary.transaction_amount),
    debitAmount: toMoney(summary.debit_amount),
    creditAmount: toMoney(summary.credit_amount),
    issueCount: issueRows.length,
    sampleIssues: issueRows.map((row) => ({
      referenceId: row.reference_id,
      amount: toMoney(row.amount),
      storedDebitAmount: toMoney(row.stored_debit_amount),
      storedCreditAmount: toMoney(row.stored_credit_amount),
      storedEntryCount: Number(row.stored_entry_count || 0),
      computedDebitAmount: toMoney(row.computed_debit_amount),
      computedCreditAmount: toMoney(row.computed_credit_amount),
      computedEntryCount: Number(row.computed_entry_count || 0)
    }))
  };
}

function summarize(metrics, verification, doubleEntryVerification) {
  const sortedLatency = [...metrics.latencySamples].sort((a, b) => a - b);
  const total = metrics.completed + metrics.failed;
  const elapsedSeconds = metrics.elapsedMs / 1000;
  return {
    runId: RUN_ID,
    accountCount: ACCOUNT_COUNT,
    concurrency: CONCURRENCY,
    durationSeconds: DURATION_SECONDS,
    hotAccountMode: HOT_ACCOUNT_MODE,
    reconcileRun: RECONCILE_RUN,
    completed: metrics.completed,
    failed: metrics.failed,
    totalAttempts: total,
    retryCount: metrics.retryCount,
    tps: Number((metrics.completed / elapsedSeconds).toFixed(2)),
    attemptedTps: Number((total / elapsedSeconds).toFixed(2)),
    latencyMs: {
      samples: sortedLatency.length,
      min: Number((sortedLatency[0] || 0).toFixed(2)),
      p50: Number(percentile(sortedLatency, 50).toFixed(2)),
      p95: Number(percentile(sortedLatency, 95).toFixed(2)),
      p99: Number(percentile(sortedLatency, 99).toFixed(2)),
      max: Number((sortedLatency[sortedLatency.length - 1] || 0).toFixed(2))
    },
    errorCodes: Object.fromEntries(metrics.errorCodes.entries()),
    verification,
    doubleEntryVerification
  };
}

async function main() {
  if (ACCOUNT_COUNT < 2) throw new Error('TPS_ACCOUNT_COUNT must be at least 2');
  if (CONCURRENCY < 1) throw new Error('TPS_CONCURRENCY must be at least 1');
  if (DURATION_SECONDS < 1) throw new Error('TPS_DURATION_SECONDS must be at least 1');

  await initDb();
  console.log('[ledger-tps] preparing', {
    runId: RUN_ID,
    accountCount: ACCOUNT_COUNT,
    concurrency: CONCURRENCY,
    durationSeconds: DURATION_SECONDS,
    warmupSeconds: WARMUP_SECONDS,
    reconcileRun: RECONCILE_RUN,
    hotAccountMode: HOT_ACCOUNT_MODE
  });

  const accounts = await seedAccounts();
  if (WARMUP_SECONDS > 0) {
    console.log('[ledger-tps] warmup starting');
    await runPhase(accounts, WARMUP_SECONDS * 1000, false);
  }

  console.log('[ledger-tps] benchmark starting');
  const metrics = await runPhase(accounts, DURATION_SECONDS * 1000, true);
  const verification = await verify(accounts);
  const doubleEntryVerification = RECONCILE_RUN
    ? await verifyDoubleEntryForRun()
    : { ok: true, skipped: true };
  const summary = summarize(metrics, verification, doubleEntryVerification);
  console.log('[ledger-tps] summary');
  console.log(JSON.stringify(summary, null, 2));
  if (!verification.ok || !doubleEntryVerification.ok || metrics.failed > 0) process.exitCode = 1;
}

main()
  .catch((err) => {
    console.error('[ledger-tps] fatal', err);
    process.exitCode = 1;
  })
  .finally(async () => {
    await sequelize.close();
  });
