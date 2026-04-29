const { DataTypes } = require('sequelize');
const { sequelize } = require('../config/db');

const WalletTransaction = sequelize.define(
  'WalletTransaction',
  {
    id: { type: DataTypes.INTEGER, primaryKey: true, autoIncrement: true },
    user_id: { type: DataTypes.STRING(64), allowNull: false },
    order_id: { type: DataTypes.INTEGER, allowNull: true },
    type: { type: DataTypes.STRING(32), allowNull: false },
    amount: { type: DataTypes.DECIMAL(14, 2), allowNull: false },
    balance_before: { type: DataTypes.DECIMAL(14, 2), allowNull: false, defaultValue: 0 },
    balance_after: { type: DataTypes.DECIMAL(14, 2), allowNull: false, defaultValue: 0 },
    status: { type: DataTypes.STRING(32), allowNull: false, defaultValue: 'completed' },
    reason: { type: DataTypes.STRING(128), allowNull: true },
    idempotency_key: { type: DataTypes.STRING(128), allowNull: false, unique: true },
    metadata: { type: DataTypes.JSONB, allowNull: false, defaultValue: {} }
  },
  {
    tableName: 'wallet_transactions',
    timestamps: true,
    createdAt: 'created_at',
    updatedAt: false
  }
);

module.exports = WalletTransaction;
