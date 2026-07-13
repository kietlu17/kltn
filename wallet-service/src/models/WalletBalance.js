const { DataTypes } = require('sequelize');
const { sequelize } = require('../config/db');

const WalletBalance = sequelize.define(
  'WalletBalance',
  {
    wallet_id: { type: DataTypes.UUID, primaryKey: true },
    available_balance: { type: DataTypes.DECIMAL(14, 2), allowNull: false, defaultValue: 0 },
    locked_balance: { type: DataTypes.DECIMAL(14, 2), allowNull: false, defaultValue: 0 },
    version: { type: DataTypes.INTEGER, allowNull: false, defaultValue: 0 }
  },
  {
    tableName: 'wallet_balances',
    timestamps: true,
    createdAt: false,
    updatedAt: 'updated_at'
  }
);

module.exports = WalletBalance;
