const { DataTypes } = require('sequelize');
const { sequelize } = require('../config/db');

const SettlementJob = sequelize.define(
  'SettlementJob',
  {
    id: { type: DataTypes.UUID, primaryKey: true, defaultValue: DataTypes.UUIDV4 },
    order_id: { type: DataTypes.INTEGER, allowNull: false },
    shop_id: { type: DataTypes.STRING(96), allowNull: false },
    amount: { type: DataTypes.DECIMAL(18, 2), allowNull: false },
    currency: { type: DataTypes.STRING(8), allowNull: false, defaultValue: 'VND' },
    status: { type: DataTypes.STRING(24), allowNull: false, defaultValue: 'pending' },
    eligible_at: { type: DataTypes.DATE, allowNull: false },
    settled_at: { type: DataTypes.DATE, allowNull: true },
    reference_id: { type: DataTypes.STRING(180), allowNull: false, unique: true },
    metadata: { type: DataTypes.JSONB, allowNull: false, defaultValue: {} },
    saga_id: { type: DataTypes.STRING(128), allowNull: true },
    correlation_id: { type: DataTypes.STRING(128), allowNull: true }
  },
  {
    tableName: 'settlement_jobs',
    timestamps: true,
    createdAt: 'created_at',
    updatedAt: 'updated_at',
    indexes: [
      { fields: ['order_id'] },
      { fields: ['shop_id'] },
      { fields: ['status', 'eligible_at'] }
    ]
  }
);

module.exports = SettlementJob;
