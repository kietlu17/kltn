const { DataTypes } = require('sequelize');
const { sequelize } = require('../config/db');

const SepayPaymentRequest = sequelize.define(
  'SepayPaymentRequest',
  {
    id: { type: DataTypes.INTEGER, primaryKey: true, autoIncrement: true },
    request_code: { type: DataTypes.STRING(80), allowNull: false, unique: true },
    purpose: { type: DataTypes.STRING(32), allowNull: false }, // wallet_topup | order_payment
    user_id: { type: DataTypes.STRING(64), allowNull: false },
    order_id: { type: DataTypes.INTEGER, allowNull: true },
    amount: { type: DataTypes.DECIMAL(14, 2), allowNull: false },
    bank_code: { type: DataTypes.STRING(64), allowNull: false },
    account_number: { type: DataTypes.STRING(64), allowNull: false },
    account_name: { type: DataTypes.STRING(128), allowNull: true },
    qr_url: { type: DataTypes.TEXT, allowNull: false },
    status: { type: DataTypes.STRING(20), allowNull: false, defaultValue: 'pending' }, // pending | paid | expired
    paid_at: { type: DataTypes.DATE, allowNull: true },
    event_published_at: { type: DataTypes.DATE, allowNull: true },
    sepay_transaction_id: { type: DataTypes.STRING(64), allowNull: true },
    metadata: { type: DataTypes.JSONB, allowNull: false, defaultValue: {} }
  },
  {
    tableName: 'sepay_payment_requests',
    timestamps: true,
    createdAt: 'created_at',
    updatedAt: 'updated_at'
  }
);

module.exports = SepayPaymentRequest;
