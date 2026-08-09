const { DataTypes } = require('sequelize');
const { sequelize } = require('../config/db');

const Voucher = sequelize.define(
  'Voucher',
  {
    id: { type: DataTypes.INTEGER, primaryKey: true, autoIncrement: true },
    code: { type: DataTypes.STRING(40), allowNull: false, unique: true },
    name: { type: DataTypes.STRING(160), allowNull: false },
    type: { type: DataTypes.STRING(20), allowNull: false },
    shop_id: { type: DataTypes.STRING(64), allowNull: true },
    discount_type: { type: DataTypes.STRING(20), allowNull: false, defaultValue: 'percent' },
    discount_value: { type: DataTypes.DECIMAL(10, 2), allowNull: false },
    max_discount_amount: { type: DataTypes.DECIMAL(12, 2), allowNull: true },
    min_order_amount: { type: DataTypes.DECIMAL(12, 2), allowNull: false, defaultValue: 0 },
    quantity: { type: DataTypes.INTEGER, allowNull: false, defaultValue: 0 },
    used_count: { type: DataTypes.INTEGER, allowNull: false, defaultValue: 0 },
    usage_limit_per_user: { type: DataTypes.INTEGER, allowNull: false, defaultValue: 1 },
    start_at: { type: DataTypes.DATE, allowNull: false },
    end_at: { type: DataTypes.DATE, allowNull: false },
    status: { type: DataTypes.STRING(20), allowNull: false, defaultValue: 'active' },
    created_by: { type: DataTypes.STRING(64), allowNull: true },
    created_by_role: { type: DataTypes.STRING(20), allowNull: true },
    created_at: { type: DataTypes.DATE, allowNull: false, defaultValue: DataTypes.NOW },
    updated_at: { type: DataTypes.DATE, allowNull: false, defaultValue: DataTypes.NOW }
  },
  {
    tableName: 'vouchers',
    timestamps: false,
    indexes: [
      { fields: ['type'] },
      { fields: ['shop_id'] },
      { fields: ['status'] }
    ]
  }
);

module.exports = Voucher;
