const { Sequelize } = require('sequelize');

const databaseName = process.env.PG_DATABASE || 'wallet_service';
const dbUser = process.env.PG_USER || 'postgres';
const dbPassword = process.env.PG_PASSWORD || 'postgres';
const dbHost = process.env.PG_HOST || 'localhost';
const dbPort = process.env.PG_PORT ? Number(process.env.PG_PORT) : 5432;

const sequelize = new Sequelize(
  databaseName,
  dbUser,
  dbPassword,
  {
    host: dbHost,
    port: dbPort,
    dialect: 'postgres',
    logging: false
  }
);

function assertSafeDatabaseName(name) {
  if (!/^[a-zA-Z0-9_-]+$/.test(name)) {
    throw new Error(`Unsafe database name: ${name}`);
  }
}

async function ensureDatabase() {
  assertSafeDatabaseName(databaseName);
  const admin = new Sequelize(
    process.env.PG_ADMIN_DATABASE || 'postgres',
    dbUser,
    dbPassword,
    {
      host: dbHost,
      port: dbPort,
      dialect: 'postgres',
      logging: false
    }
  );

  try {
    const escapedName = databaseName.replace(/"/g, '""');
    await admin.query(`CREATE DATABASE "${escapedName}"`);
    console.log(`Created PostgreSQL database ${databaseName}`);
  } catch (err) {
    if (err?.original?.code !== '42P04' && err?.parent?.code !== '42P04') {
      throw err;
    }
  } finally {
    await admin.close();
  }
}

async function ensureLedgerIntegritySchema() {
  await sequelize.query(`
    ALTER TABLE ledger_transactions
      ADD COLUMN IF NOT EXISTS debit_amount DECIMAL(18, 2) NOT NULL DEFAULT 0,
      ADD COLUMN IF NOT EXISTS credit_amount DECIMAL(18, 2) NOT NULL DEFAULT 0,
      ADD COLUMN IF NOT EXISTS entry_count INTEGER NOT NULL DEFAULT 0
  `);

  await sequelize.query(`
    UPDATE ledger_transactions lt
    SET
      debit_amount = COALESCE(s.debit_amount, 0),
      credit_amount = COALESCE(s.credit_amount, 0),
      entry_count = COALESCE(s.entry_count, 0)
    FROM (
      SELECT
        transaction_id,
        SUM(CASE WHEN direction = 'debit' THEN amount ELSE 0 END) AS debit_amount,
        SUM(CASE WHEN direction = 'credit' THEN amount ELSE 0 END) AS credit_amount,
        COUNT(*) AS entry_count
      FROM ledger_entries
      GROUP BY transaction_id
    ) s
    WHERE lt.id = s.transaction_id
  `);

  await sequelize.query(`
    DO $$
    BEGIN
      IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ledger_entries_direction_check'
      ) THEN
        ALTER TABLE ledger_entries
          ADD CONSTRAINT ledger_entries_direction_check CHECK (direction IN ('debit', 'credit'));
      END IF;

      IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ledger_entries_amount_positive_check'
      ) THEN
        ALTER TABLE ledger_entries
          ADD CONSTRAINT ledger_entries_amount_positive_check CHECK (amount > 0);
      END IF;

      IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ledger_transactions_completed_totals_check'
      ) THEN
        ALTER TABLE ledger_transactions
          ADD CONSTRAINT ledger_transactions_completed_totals_check CHECK (
            status <> 'completed'
            OR (
              entry_count >= 2
              AND debit_amount = credit_amount
              AND debit_amount = amount
            )
          );
      END IF;
    END
    $$;
  `);
}

async function initDb() {
  await ensureDatabase();
  await sequelize.authenticate();
  await sequelize.sync();
  await ensureLedgerIntegritySchema();
  console.log('Wallet Service connected to PostgreSQL');
}

module.exports = { sequelize, initDb };
