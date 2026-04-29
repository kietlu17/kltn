const { DataTypes } = require('sequelize');
const { sequelize } = require('../config/db');

const Order = sequelize.define(
  'Order',
  {
    id: { type: DataTypes.INTEGER, primaryKey: true, autoIncrement: true },
    user_id: { type: DataTypes.STRING(64), allowNull: false },
    products: { type: DataTypes.JSONB, allowNull: false },
    total_price: { type: DataTypes.DECIMAL(12, 2), allowNull: false },
    status: { type: DataTypes.STRING(40), allowNull: false, defaultValue: 'pending_payment' },
    idempotency_key: { type: DataTypes.STRING(128), allowNull: true, unique: true },
    idempotency_request_hash: { type: DataTypes.STRING(64), allowNull: true },
    shipping_address: { type: DataTypes.JSONB, allowNull: true },
    payment_method: { type: DataTypes.STRING(40), allowNull: true },
    created_at: { type: DataTypes.DATE, allowNull: false, defaultValue: DataTypes.NOW }
  },
  {
    tableName: 'orders',
    timestamps: false
  }
);

module.exports = Order;
