const { DataTypes } = require('sequelize');
const { sequelize } = require('../config/db');

const WalletLedgerEntry = sequelize.define(
  'WalletLedgerEntry',
  {
    id: { type: DataTypes.UUID, primaryKey: true, defaultValue: DataTypes.UUIDV4 },
    wallet_id: { type: DataTypes.UUID, allowNull: false },
    user_id: { type: DataTypes.STRING(64), allowNull: false },
    order_id: { type: DataTypes.INTEGER, allowNull: true },
    type: { type: DataTypes.STRING(40), allowNull: false },
    direction: { type: DataTypes.STRING(12), allowNull: false },
    amount: { type: DataTypes.DECIMAL(14, 2), allowNull: false },
    status: { type: DataTypes.STRING(24), allowNull: false },
    reason: { type: DataTypes.STRING(128), allowNull: true },
    reference_id: { type: DataTypes.STRING(160), allowNull: false, unique: true },
    available_before: { type: DataTypes.DECIMAL(14, 2), allowNull: false, defaultValue: 0 },
    available_after: { type: DataTypes.DECIMAL(14, 2), allowNull: false, defaultValue: 0 },
    locked_before: { type: DataTypes.DECIMAL(14, 2), allowNull: false, defaultValue: 0 },
    locked_after: { type: DataTypes.DECIMAL(14, 2), allowNull: false, defaultValue: 0 },
    metadata: { type: DataTypes.JSONB, allowNull: false, defaultValue: {} },
    saga_id: { type: DataTypes.STRING(128), allowNull: true },
    correlation_id: { type: DataTypes.STRING(128), allowNull: true }
  },
  {
    tableName: 'wallet_ledger_entries',
    timestamps: true,
    createdAt: 'created_at',
    updatedAt: false,
    indexes: [
      { fields: ['wallet_id'] },
      { fields: ['user_id'] },
      { fields: ['order_id'] }
    ]
  }
);

module.exports = WalletLedgerEntry;
