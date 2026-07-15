const { DataTypes } = require('sequelize');
const { sequelize } = require('../config/db');

const LedgerTransaction = sequelize.define(
  'LedgerTransaction',
  {
    id: { type: DataTypes.UUID, primaryKey: true, defaultValue: DataTypes.UUIDV4 },
    reference_id: { type: DataTypes.STRING(180), allowNull: false, unique: true },
    idempotency_key: { type: DataTypes.STRING(180), allowNull: true, unique: true },
    type: { type: DataTypes.STRING(48), allowNull: false },
    status: { type: DataTypes.STRING(24), allowNull: false, defaultValue: 'pending' },
    amount: { type: DataTypes.DECIMAL(18, 2), allowNull: false, defaultValue: 0 },
    debit_amount: { type: DataTypes.DECIMAL(18, 2), allowNull: false, defaultValue: 0 },
    credit_amount: { type: DataTypes.DECIMAL(18, 2), allowNull: false, defaultValue: 0 },
    entry_count: { type: DataTypes.INTEGER, allowNull: false, defaultValue: 0 },
    currency: { type: DataTypes.STRING(8), allowNull: false, defaultValue: 'VND' },
    metadata: { type: DataTypes.JSONB, allowNull: false, defaultValue: {} },
    saga_id: { type: DataTypes.STRING(128), allowNull: true },
    correlation_id: { type: DataTypes.STRING(128), allowNull: true },
    completed_at: { type: DataTypes.DATE, allowNull: true },
    failed_reason: { type: DataTypes.STRING(180), allowNull: true }
  },
  {
    tableName: 'ledger_transactions',
    validate: {
      balancedWhenCompleted() {
        if (this.status !== 'completed') return;
        const amount = Number(this.amount);
        const debitAmount = Number(this.debit_amount);
        const creditAmount = Number(this.credit_amount);
        if (this.entry_count < 2) throw new Error('completed ledger transaction requires at least two entries');
        if (Math.abs(debitAmount - creditAmount) >= 0.01) throw new Error('completed ledger transaction is not balanced');
        if (Math.abs(debitAmount - amount) >= 0.01) throw new Error('completed ledger transaction total does not match amount');
      }
    },
    timestamps: true,
    createdAt: 'created_at',
    updatedAt: 'updated_at',
    indexes: [
      { fields: ['type'] },
      { fields: ['status'] },
      { fields: ['saga_id'] },
      { fields: ['correlation_id'] }
    ]
  }
);

module.exports = LedgerTransaction;
