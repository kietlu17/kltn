const { DataTypes } = require('sequelize');
const { sequelize } = require('../config/db');

const CheckoutQuote = sequelize.define(
  'CheckoutQuote',
  {
    id: { type: DataTypes.UUID, primaryKey: true, defaultValue: DataTypes.UUIDV4 },
    user_id: { type: DataTypes.STRING(64), allowNull: false },
    session_id: { type: DataTypes.STRING(128), allowNull: true },
    products: { type: DataTypes.JSONB, allowNull: false },
    shipping_address: { type: DataTypes.JSONB, allowNull: false },
    payment_method: { type: DataTypes.STRING(40), allowNull: false },
    voucher_code: { type: DataTypes.STRING(40), allowNull: true },
    subtotal_price: { type: DataTypes.DECIMAL(12, 2), allowNull: false },
    total_price: { type: DataTypes.DECIMAL(12, 2), allowNull: false },
    confirmation_digest: { type: DataTypes.STRING(64), allowNull: false },
    status: { type: DataTypes.STRING(24), allowNull: false, defaultValue: 'open' },
    order_ids: { type: DataTypes.JSONB, allowNull: false, defaultValue: [] },
    expires_at: { type: DataTypes.DATE, allowNull: false },
    created_at: { type: DataTypes.DATE, allowNull: false, defaultValue: DataTypes.NOW }
  },
  { tableName: 'checkout_quotes', timestamps: false }
);

module.exports = CheckoutQuote;
