const { sequelize } = require('../config/db');
const { toMoney } = require('./accountLedgerService');

function rowToIssue(row) {
  const amount = toMoney(row.amount);
  const storedDebitAmount = toMoney(row.stored_debit_amount);
  const storedCreditAmount = toMoney(row.stored_credit_amount);
  const computedDebitAmount = toMoney(row.computed_debit_amount);
  const computedCreditAmount = toMoney(row.computed_credit_amount);
  const storedEntryCount = Number(row.stored_entry_count || 0);
  const computedEntryCount = Number(row.computed_entry_count || 0);

  return {
    transactionId: row.id,
    referenceId: row.reference_id,
    type: row.type,
    status: row.status,
    amount,
    stored: {
      debitAmount: storedDebitAmount,
      creditAmount: storedCreditAmount,
      entryCount: storedEntryCount
    },
    computed: {
      debitAmount: computedDebitAmount,
      creditAmount: computedCreditAmount,
      entryCount: computedEntryCount
    },
    problems: [
      computedEntryCount < 2 ? 'entry_count_lt_2' : null,
      computedDebitAmount !== computedCreditAmount ? 'computed_debit_credit_mismatch' : null,
      computedDebitAmount !== amount ? 'computed_total_mismatch_amount' : null,
      storedDebitAmount !== computedDebitAmount ? 'stored_debit_mismatch' : null,
      storedCreditAmount !== computedCreditAmount ? 'stored_credit_mismatch' : null,
      storedEntryCount !== computedEntryCount ? 'stored_entry_count_mismatch' : null
    ].filter(Boolean)
  };
}

async function reconcileLedgerTransactions({ limit = 100, offset = 0 } = {}) {
  const [rows] = await sequelize.query(
    `
      WITH entry_totals AS (
        SELECT
          transaction_id,
          COALESCE(SUM(CASE WHEN direction = 'debit' THEN amount ELSE 0 END), 0) AS computed_debit_amount,
          COALESCE(SUM(CASE WHEN direction = 'credit' THEN amount ELSE 0 END), 0) AS computed_credit_amount,
          COUNT(*) AS computed_entry_count
        FROM ledger_entries
        GROUP BY transaction_id
      )
      SELECT
        lt.id,
        lt.reference_id,
        lt.type,
        lt.status,
        lt.amount,
        lt.debit_amount AS stored_debit_amount,
        lt.credit_amount AS stored_credit_amount,
        lt.entry_count AS stored_entry_count,
        COALESCE(et.computed_debit_amount, 0) AS computed_debit_amount,
        COALESCE(et.computed_credit_amount, 0) AS computed_credit_amount,
        COALESCE(et.computed_entry_count, 0) AS computed_entry_count
      FROM ledger_transactions lt
      LEFT JOIN entry_totals et ON et.transaction_id = lt.id
      WHERE lt.status = 'completed'
        AND (
          COALESCE(et.computed_entry_count, 0) < 2
          OR COALESCE(et.computed_debit_amount, 0) <> COALESCE(et.computed_credit_amount, 0)
          OR COALESCE(et.computed_debit_amount, 0) <> lt.amount
          OR lt.debit_amount <> COALESCE(et.computed_debit_amount, 0)
          OR lt.credit_amount <> COALESCE(et.computed_credit_amount, 0)
          OR lt.entry_count <> COALESCE(et.computed_entry_count, 0)
        )
      ORDER BY lt.created_at ASC
      LIMIT :limit OFFSET :offset
    `,
    {
      replacements: {
        limit: Math.max(1, Math.min(Number(limit) || 100, 1000)),
        offset: Math.max(0, Number(offset) || 0)
      }
    }
  );

  const [countRows] = await sequelize.query(
    `
      WITH entry_totals AS (
        SELECT
          transaction_id,
          COALESCE(SUM(CASE WHEN direction = 'debit' THEN amount ELSE 0 END), 0) AS computed_debit_amount,
          COALESCE(SUM(CASE WHEN direction = 'credit' THEN amount ELSE 0 END), 0) AS computed_credit_amount,
          COUNT(*) AS computed_entry_count
        FROM ledger_entries
        GROUP BY transaction_id
      )
      SELECT COUNT(*) AS count
      FROM ledger_transactions lt
      LEFT JOIN entry_totals et ON et.transaction_id = lt.id
      WHERE lt.status = 'completed'
        AND (
          COALESCE(et.computed_entry_count, 0) < 2
          OR COALESCE(et.computed_debit_amount, 0) <> COALESCE(et.computed_credit_amount, 0)
          OR COALESCE(et.computed_debit_amount, 0) <> lt.amount
          OR lt.debit_amount <> COALESCE(et.computed_debit_amount, 0)
          OR lt.credit_amount <> COALESCE(et.computed_credit_amount, 0)
          OR lt.entry_count <> COALESCE(et.computed_entry_count, 0)
        )
    `
  );

  const issues = rows.map(rowToIssue);
  return {
    ok: issues.length === 0 && Number(countRows[0]?.count || 0) === 0,
    issueCount: Number(countRows[0]?.count || 0),
    returned: issues.length,
    issues
  };
}

module.exports = { reconcileLedgerTransactions };
