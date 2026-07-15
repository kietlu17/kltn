const { DataTypes } = require('sequelize');
const { sequelize } = require('../config/db');

const LedgerEntry = sequelize.define(
  'LedgerEntry',
  {
    id: { type: DataTypes.UUID, primaryKey: true, defaultValue: DataTypes.UUIDV4 },
    transaction_id: { type: DataTypes.UUID, allowNull: false },
    account_id: { type: DataTypes.UUID, allowNull: false },
    direction: {
      type: DataTypes.STRING(12),
      allowNull: false,
      validate: { isIn: [['debit', 'credit']] }
    },
    amount: {
      type: DataTypes.DECIMAL(18, 2),
      allowNull: false,
      validate: { min: 0.01 }
    },
    currency: { type: DataTypes.STRING(8), allowNull: false, defaultValue: 'VND' },
    available_before: { type: DataTypes.DECIMAL(18, 2), allowNull: false, defaultValue: 0 },
    available_after: { type: DataTypes.DECIMAL(18, 2), allowNull: false, defaultValue: 0 },
    locked_before: { type: DataTypes.DECIMAL(18, 2), allowNull: false, defaultValue: 0 },
    locked_after: { type: DataTypes.DECIMAL(18, 2), allowNull: false, defaultValue: 0 },
    metadata: { type: DataTypes.JSONB, allowNull: false, defaultValue: {} }
  },
  {
    tableName: 'ledger_entries',
    timestamps: true,
    createdAt: 'created_at',
    updatedAt: false,
    indexes: [
      { fields: ['transaction_id'] },
      { fields: ['account_id'] },
      { fields: ['direction'] }
    ]
  }
);

module.exports = LedgerEntry;
