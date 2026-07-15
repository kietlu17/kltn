const { DataTypes } = require('sequelize');
const { sequelize } = require('../config/db');

const AccountBalance = sequelize.define(
  'AccountBalance',
  {
    account_id: { type: DataTypes.UUID, primaryKey: true },
    available_balance: { type: DataTypes.DECIMAL(18, 2), allowNull: false, defaultValue: 0 },
    locked_balance: { type: DataTypes.DECIMAL(18, 2), allowNull: false, defaultValue: 0 },
    version: { type: DataTypes.INTEGER, allowNull: false, defaultValue: 0 }
  },
  {
    tableName: 'account_balances',
    timestamps: true,
    createdAt: false,
    updatedAt: 'updated_at',
    indexes: [{ fields: ['available_balance'] }]
  }
);

module.exports = AccountBalance;
