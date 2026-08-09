const { DataTypes } = require('sequelize');
const { sequelize } = require('../config/db');

const VoucherReservation = sequelize.define(
  'VoucherReservation',
  {
    id: { type: DataTypes.INTEGER, primaryKey: true, autoIncrement: true },
    voucher_id: { type: DataTypes.INTEGER, allowNull: false },
    order_id: { type: DataTypes.INTEGER, allowNull: false },
    user_id: { type: DataTypes.STRING(64), allowNull: false },
    discount_amount: { type: DataTypes.DECIMAL(12, 2), allowNull: false, defaultValue: 0 },
    status: { type: DataTypes.STRING(20), allowNull: false, defaultValue: 'reserved' },
    created_at: { type: DataTypes.DATE, allowNull: false, defaultValue: DataTypes.NOW },
    updated_at: { type: DataTypes.DATE, allowNull: false, defaultValue: DataTypes.NOW }
  },
  {
    tableName: 'voucher_reservations',
    timestamps: false,
    indexes: [
      {
        unique: true,
        fields: ['voucher_id', 'order_id']
      },
      { fields: ['user_id'] },
      { fields: ['status'] }
    ]
  }
);

module.exports = VoucherReservation;
