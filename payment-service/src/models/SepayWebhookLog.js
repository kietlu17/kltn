const { DataTypes } = require('sequelize');
const { sequelize } = require('../config/db');

const SepayWebhookLog = sequelize.define(
  'SepayWebhookLog',
  {
    id: { type: DataTypes.INTEGER, primaryKey: true, autoIncrement: true },
    sepay_transaction_id: { type: DataTypes.STRING(64), allowNull: false, unique: true },
    request_code: { type: DataTypes.STRING(80), allowNull: true },
    transfer_type: { type: DataTypes.STRING(12), allowNull: true },
    transfer_amount: { type: DataTypes.DECIMAL(14, 2), allowNull: true },
    payload: { type: DataTypes.JSONB, allowNull: false, defaultValue: {} }
  },
  {
    tableName: 'sepay_webhook_logs',
    timestamps: true,
    createdAt: 'created_at',
    updatedAt: false
  }
);

module.exports = SepayWebhookLog;
