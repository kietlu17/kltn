require('dotenv').config();
require('../src/models');

const { sequelize, initDb } = require('../src/config/db');
const { reconcileLedgerTransactions } = require('../src/services/ledgerReconciliationService');

const LIMIT = Number(process.env.RECONCILE_LIMIT || 100);
const OFFSET = Number(process.env.RECONCILE_OFFSET || 0);

async function main() {
  await initDb();
  const result = await reconcileLedgerTransactions({ limit: LIMIT, offset: OFFSET });
  console.log('[ledger-reconcile] summary');
  console.log(JSON.stringify(result, null, 2));
  if (!result.ok) process.exitCode = 1;
}

main()
  .catch((err) => {
    console.error('[ledger-reconcile] fatal', err);
    process.exitCode = 1;
  })
  .finally(async () => {
    await sequelize.close();
  });
