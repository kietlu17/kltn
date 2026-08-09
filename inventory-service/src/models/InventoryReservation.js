const { DataTypes } = require('sequelize');
const { sequelize } = require('../config/db');

const InventoryReservation = sequelize.define(
  'InventoryReservation',
  {
    id: { type: DataTypes.INTEGER, primaryKey: true, autoIncrement: true },
    order_id: { type: DataTypes.STRING(64), allowNull: false },
    product_id: { type: DataTypes.STRING(64), allowNull: false },
    variant_id: { type: DataTypes.STRING(64), allowNull: false, defaultValue: '' },
    quantity: { type: DataTypes.INTEGER, allowNull: false },
    status: {
      type: DataTypes.STRING(24),
      allowNull: false,
      defaultValue: 'reserved'
    },
    created_at: { type: DataTypes.DATE, allowNull: false, defaultValue: DataTypes.NOW },
    updated_at: { type: DataTypes.DATE, allowNull: false, defaultValue: DataTypes.NOW }
  },
  {
    tableName: 'inventory_reservations',
    timestamps: false,
    indexes: [
      {
        unique: true,
        fields: ['order_id', 'product_id', 'variant_id']
      },
      { fields: ['order_id', 'status'] }
    ]
  }
);

module.exports = InventoryReservation;
