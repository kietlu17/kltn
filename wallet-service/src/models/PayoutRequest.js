const { DataTypes } = require('sequelize');
const { sequelize } = require('../config/db');

const PayoutRequest = sequelize.define(
  'PayoutRequest',
  {
    id: { type: DataTypes.UUID, primaryKey: true, defaultValue: DataTypes.UUIDV4 },
    shop_id: { type: DataTypes.STRING(96), allowNull: false },
    account_id: { type: DataTypes.UUID, allowNull: false },
    amount: { type: DataTypes.DECIMAL(18, 2), allowNull: false },
    currency: { type: DataTypes.STRING(8), allowNull: false, defaultValue: 'VND' },
    status: { type: DataTypes.STRING(24), allowNull: false, defaultValue: 'requested' },
    reference_id: { type: DataTypes.STRING(180), allowNull: false, unique: true },
    bank_account_snapshot: { type: DataTypes.JSONB, allowNull: false, defaultValue: {} },
    failure_reason: { type: DataTypes.STRING(180), allowNull: true },
    completed_at: { type: DataTypes.DATE, allowNull: true },
    metadata: { type: DataTypes.JSONB, allowNull: false, defaultValue: {} },
    saga_id: { type: DataTypes.STRING(128), allowNull: true },
    correlation_id: { type: DataTypes.STRING(128), allowNull: true }
  },
  {
    tableName: 'payout_requests',
    timestamps: true,
    createdAt: 'created_at',
    updatedAt: 'updated_at',
    indexes: [
      { fields: ['shop_id'] },
      { fields: ['account_id'] },
      { fields: ['status'] }
    ]
  }
);

module.exports = PayoutRequest;
